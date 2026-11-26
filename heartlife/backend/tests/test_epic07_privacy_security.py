from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.core.deps import require_role
from app.core.security import hash_token
from app.db.models import (
    Article,
    Bookmark,
    Challenge,
    ChallengeMembership,
    Checkin,
    Comment,
    FamilyGrant,
    FamilyInvite,
    JournalEntry,
    ModerationAction,
    Notification,
    Plan,
    PlanVersion,
    Post,
    Reaction,
    ReadingDailyLog,
    ReadingHistory,
    TopicFollow,
    User,
    UserBadge,
    UserBlock,
    UserSession,
)


def _register_and_login(
    client: TestClient,
    account: str,
    password: str = "SafePassword123!",
    nickname: str = "测试用户",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": password, "nickname": nickname},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": password},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    return data["user"], data["csrf_token"]


def test_t0701_export_returns_only_owner_data_and_never_leaks_secrets(
    app_instance,
    db_session: Session,
):
    """T-0701: GET /me/export returns owner's profile, journals, plans, current_weekly_report without secrets or others' data."""
    with TestClient(app_instance) as ca, TestClient(app_instance) as cb:
        ua, _ = _register_and_login(ca, "export_alice", nickname="阿狸")
        ub, _ = _register_and_login(cb, "export_bob", nickname="阿博")

        p_a = Plan(owner_id=ua["id"], title="阿狸的晨走", active=True)
        p_b = Plan(owner_id=ub["id"], title="阿博的冥想", active=True)
        db_session.add_all([p_a, p_b])
        db_session.flush()

        db_session.add_all(
            [
                PlanVersion(
                    plan_id=p_a.id,
                    version_num=1,
                    effective_from=date(2026, 11, 23),
                    weekday_mask=127,
                    active=True,
                    start_date=date(2026, 11, 23),
                ),
                Checkin(plan_id=p_a.id, local_date=date(2026, 11, 25), completed=True),
                JournalEntry(
                    user_id=ua["id"],
                    local_date=date(2026, 11, 25),
                    sleep_minutes=460,
                    activity_minutes=35,
                    mood="平静",
                    symptom_tags_json=json.dumps(["无不适"]),
                    note="阿狸私密记录",
                ),
                JournalEntry(
                    user_id=ub["id"],
                    local_date=date(2026, 11, 25),
                    sleep_minutes=300,
                    activity_minutes=10,
                    mood="疲惫",
                    note="阿博绝密记录不应泄露",
                ),
            ]
        )
        db_session.commit()

        res = ca.get("/api/v1/me/export")
        assert res.status_code == 200, res.text
        exported = res.json()

        assert set(exported.keys()) >= {"exported_at", "profile", "journals", "plans", "current_weekly_report"}
        assert exported["profile"]["nickname"] == "阿狸"
        assert "password_hash" not in res.text
        assert "$argon2" not in res.text
        assert "csrf_token" not in res.text
        assert "export_alice" not in res.text  # account excluded from profile export
        assert "阿博绝密记录不应泄露" not in res.text
        assert "阿博的冥想" not in res.text
        assert len(exported["journals"]) == 1
        assert exported["journals"][0]["note"] == "阿狸私密记录"
        assert len(exported["plans"]) == 1
        assert exported["plans"][0]["title"] == "阿狸的晨走"


def test_t0702_delete_account_requires_exact_confirm_text_password_and_csrf(
    app_instance,
    db_session: Session,
):
    """T-0702: POST /me/delete rejects bad confirm_text (422), wrong password (401), missing CSRF (403), extra fields (422)."""
    with TestClient(app_instance) as client:
        u, csrf = _register_and_login(client, "guard_del", password="MyPassword123!", nickname="守门人")
        db_session.add(JournalEntry(user_id=u["id"], local_date=date(2026, 11, 25), sleep_minutes=420))
        db_session.commit()

        # Missing CSRF -> 403
        assert client.post(
            "/api/v1/me/delete",
            json={"password": "MyPassword123!", "confirm_text": "DELETE"},
        ).status_code == 403

        # Wrong confirm_text -> 422
        assert client.post(
            "/api/v1/me/delete",
            json={"password": "MyPassword123!", "confirm_text": "delete"},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 422

        # Extra field -> 422
        assert client.post(
            "/api/v1/me/delete",
            json={"password": "MyPassword123!", "confirm_text": "DELETE", "force": True},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 422

        # Wrong password -> 401
        assert client.post(
            "/api/v1/me/delete",
            json={"password": "WrongPassword999!", "confirm_text": "DELETE"},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 401

        db_session.expire_all()
        still_active = db_session.get(User, u["id"])
        assert still_active is not None and still_active.status == "active"
        assert db_session.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == u["id"])) == 1


def test_t0703_delete_account_purges_private_data_scrubs_posts_and_preserves_audit_fk(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0703: Valid deletion purges all private tables, hides/scrubs posts & comments, anonymizes User, preserves ModerationAction FK."""
    with TestClient(app_instance) as ca, TestClient(app_instance) as cb:
        ua, csrf_a = _register_and_login(ca, "del_target", password="DelPassword123!", nickname="待注销用户")
        ub, _ = _register_and_login(cb, "other_peer", nickname="同伴")
        saved_cookie = ca.cookies.get("hl_session")

        uid = ua["id"]
        plan = Plan(owner_id=uid, title="私密习惯", active=True)
        art = Article(slug="art-1", editor_id=ub["id"], status="published", title="科普", category="睡眠管理", body="正文")
        chal = Challenge(
            slug="chal-del",
            title="七日睡眠",
            description="描述",
            rule_type="journal_sleep",
            target_days=3,
            start_date=date(2026, 11, 20),
            end_date=date(2026, 11, 30),
            badge_title="睡眠之星",
        )
        post = Post(author_id=uid, category="日常心情", title="公开原帖标题", body="公开原帖正文", status="visible")
        peer_post = Post(author_id=ub["id"], category="日常心情", title="同伴帖子", body="内容", status="visible")
        db_session.add_all([plan, art, chal, post, peer_post])
        db_session.flush()

        comment = Comment(post_id=peer_post.id, author_id=uid, body="我的原评论内容", status="visible")
        db_session.add(comment)
        db_session.flush()

        mod_action = ModerationAction(
            actor_id=ub["id"],
            target_type="post",
            target_id=post.id,
            action="restore",
            reason="核查通过",
        )
        db_session.add_all(
            [
                mod_action,
                JournalEntry(user_id=uid, local_date=date(2026, 11, 25), sleep_minutes=400, note="私密备注"),
                PlanVersion(plan_id=plan.id, version_num=1, effective_from=date(2026, 11, 23), start_date=date(2026, 11, 23)),
                Checkin(plan_id=plan.id, local_date=date(2026, 11, 25), completed=True),
                Bookmark(user_id=uid, target_type="post", target_id=peer_post.id),
                Reaction(user_id=uid, target_type="post", target_id=peer_post.id),
                ReadingHistory(user_id=uid, article_id=art.id),
                ReadingDailyLog(user_id=uid, local_date=date(2026, 11, 25)),
                Notification(
                    recipient_id=uid,
                    type="post_comment",
                    target_type="post",
                    target_id=post.id,
                    summary="通知",
                    dedup_key="d1",
                    created_at=fake_clock.now(),
                ),
                ChallengeMembership(challenge_id=chal.id, user_id=uid, status="active", joined_date=date(2026, 11, 24)),
                UserBadge(user_id=uid, challenge_id=chal.id, badge_title="睡眠之星", achieved_date=date(2026, 11, 25)),
                TopicFollow(user_id=uid, category="日常心情"),
                UserBlock(blocker_id=uid, blocked_id=ub["id"]),
                FamilyInvite(
                    granter_id=uid,
                    code_hash=hash_token("invite-secret-1"),
                    expires_at=fake_clock.now() + timedelta(hours=24),
                ),
                FamilyGrant(granter_id=uid, viewer_id=ub["id"], status="active"),
            ]
        )
        db_session.commit()
        post_id = post.id
        comment_id = comment.id
        mod_id = mod_action.id

        res = ca.post(
            "/api/v1/me/delete",
            json={"password": "DelPassword123!", "confirm_text": "DELETE"},
            headers={"X-CSRF-Token": csrf_a},
        )
        assert res.status_code == 200, res.text

        # Old session & re-login must both fail
        if saved_cookie:
            ca.cookies.set("hl_session", saved_cookie)
        assert ca.get("/api/v1/me").status_code == 401
        assert cb.post(
            "/api/v1/auth/login",
            json={"account": "del_target", "password": "DelPassword123!"},
        ).status_code == 401
        assert cb.get(f"/api/v1/users/{uid}").status_code == 404

        db_session.expire_all()
        # Private rows physically purged
        for model, col in [
            (UserSession, UserSession.user_id),
            (JournalEntry, JournalEntry.user_id),
            (Plan, Plan.owner_id),
            (Bookmark, Bookmark.user_id),
            (Reaction, Reaction.user_id),
            (ReadingHistory, ReadingHistory.user_id),
            (ReadingDailyLog, ReadingDailyLog.user_id),
            (Notification, Notification.recipient_id),
            (ChallengeMembership, ChallengeMembership.user_id),
            (UserBadge, UserBadge.user_id),
            (TopicFollow, TopicFollow.user_id),
            (UserBlock, UserBlock.blocker_id),
            (FamilyInvite, FamilyInvite.granter_id),
            (FamilyGrant, FamilyGrant.granter_id),
        ]:
            assert db_session.scalar(select(func.count()).where(col == uid)) == 0, f"Residual rows in {model}"

        # Post & Comment scrubbed and hidden
        scrubbed_post = db_session.get(Post, post_id)
        assert scrubbed_post is not None
        assert scrubbed_post.status == "hidden"
        assert scrubbed_post.title == "[已注销内容]"
        assert scrubbed_post.body == "[账号已注销]"

        scrubbed_comment = db_session.get(Comment, comment_id)
        assert scrubbed_comment is not None
        assert scrubbed_comment.status == "hidden"
        assert scrubbed_comment.body == "[账号已注销]"

        # User anonymized while ModerationAction FK remains valid
        anon_user = db_session.get(User, uid)
        assert anon_user is not None
        assert anon_user.status == "deleted"
        assert anon_user.account == f"deleted_{uid}"
        assert anon_user.password_hash == "!"
        assert anon_user.nickname == "已注销用户"
        assert anon_user.bio == ""
        assert db_session.get(ModerationAction, mod_id) is not None


def test_t0704_delete_account_rolls_back_atomically_on_mid_transaction_error(
    app_instance,
    db_session: Session,
    monkeypatch,
):
    """T-0704: Simulated mid-deletion failure rolls back everything so no partial data loss occurs."""
    import app.privacy.service as privacy_service

    with TestClient(app_instance, raise_server_exceptions=False) as client:
        u, csrf = _register_and_login(client, "atomic_user", password="AtomicPassword1!", nickname="原子性测试")
        uid = u["id"]
        post = Post(author_id=uid, category="日常心情", title="保留标题", body="保留正文", status="visible")
        db_session.add_all(
            [
                post,
                JournalEntry(user_id=uid, local_date=date(2026, 11, 25), sleep_minutes=480, note="不能丢失的日记"),
            ]
        )
        db_session.commit()
        post_id = post.id

        def _boom() -> None:
            raise RuntimeError("Simulated mid-transaction crash")

        monkeypatch.setattr(privacy_service, "_DELETION_TEST_HOOK", _boom)

        res = client.post(
            "/api/v1/me/delete",
            json={"password": "AtomicPassword1!", "confirm_text": "DELETE"},
            headers={"X-CSRF-Token": csrf},
        )
        assert res.status_code == 500

        db_session.expire_all()
        kept_user = db_session.get(User, uid)
        assert kept_user is not None and kept_user.status == "active"
        assert kept_user.nickname == "原子性测试"
        assert db_session.scalar(select(func.count()).where(JournalEntry.user_id == uid)) == 1
        assert db_session.scalar(select(func.count()).where(UserSession.user_id == uid)) >= 1
        kept_post = db_session.get(Post, post_id)
        assert kept_post is not None and kept_post.status == "visible" and kept_post.title == "保留标题"


def test_t0705_sql_special_chars_overlong_params_and_html_tags_handled_safely(
    app_instance,
    db_session: Session,
):
    """T-0705: SQL injection payloads, overlong strings, and HTML tags never trigger 500 or corrupt DB."""
    with TestClient(app_instance) as client:
        u, csrf = _register_and_login(client, "sec_input", nickname="安全输入")

        sqli = "' OR 1=1 --"
        assert client.post("/api/v1/auth/login", json={"account": sqli, "password": sqli}).status_code == 401
        assert client.get(f"/api/v1/me/weekly-report?week_start={sqli}").status_code == 422
        assert client.post(
            "/api/v1/me/family/accept",
            json={"invite_code": sqli},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 404

        overlong = "x" * 5000
        assert client.post(
            "/api/v1/me/family/accept",
            json={"invite_code": overlong},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 422

        html_bio = "<script>alert('xss')</script>"
        patch_res = client.patch(
            "/api/v1/me",
            json={"bio": html_bio},
            headers={"X-CSRF-Token": csrf},
        )
        assert patch_res.status_code == 200
        # Stored as literal string, Users table intact
        assert db_session.scalar(select(func.count()).select_from(User).where(User.id == u["id"])) == 1


def test_t0706_moderator_and_editor_cannot_access_private_data_and_member_gets_403_on_staff_guards(
    app_instance,
    db_session: Session,
):
    """T-0706: Moderator/editor cannot access another user's private health data; normal member gets 403 on role guards."""
    with (
        TestClient(app_instance) as c_member,
        TestClient(app_instance) as c_mod,
        TestClient(app_instance) as c_editor,
    ):
        u_mem, _ = _register_and_login(c_member, "normal_mem", nickname="普通成员")
        u_mod, _ = _register_and_login(c_mod, "staff_mod", nickname="审核员")
        u_ed, _ = _register_and_login(c_editor, "staff_ed", nickname="编辑")

        # Grant moderator and editor roles in DB
        mod_row = db_session.get(User, u_mod["id"])
        ed_row = db_session.get(User, u_ed["id"])
        assert mod_row is not None and ed_row is not None
        mod_row.roles = "member,moderator"
        ed_row.roles = "member,editor"
        db_session.add(
            JournalEntry(
                user_id=u_mem["id"],
                local_date=date(2026, 11, 25),
                sleep_minutes=495,
                note="普通成员绝密健康记录",
            )
        )
        db_session.commit()

        # Normal member gets 403 on real moderator & editor endpoints; roles stay separated
        assert c_member.get("/api/v1/moderation/reports").status_code == 403
        assert c_member.get("/api/v1/editor/articles").status_code == 403
        assert c_mod.get("/api/v1/moderation/reports").status_code == 200
        assert c_mod.get("/api/v1/editor/articles").status_code == 403
        assert c_editor.get("/api/v1/editor/articles").status_code == 200
        assert c_editor.get("/api/v1/moderation/reports").status_code == 403

        # Moderator and Editor cannot read normal_mem's private export, weekly-report, dashboard, or family share
        for staff_client in (c_mod, c_editor):
            exp = staff_client.get("/api/v1/me/export")
            assert exp.status_code == 200
            assert "普通成员绝密健康记录" not in exp.text
            assert exp.json()["journals"] == []

            assert staff_client.get(f"/api/v1/me/export?user_id={u_mem['id']}").status_code == 422
            assert staff_client.get(f"/api/v1/me/weekly-report?user_id={u_mem['id']}").status_code == 422
            assert staff_client.get(f"/api/v1/family/shared/{u_mem['id']}").status_code == 403
