from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import (
    Challenge,
    ChallengeMembership,
    Checkin,
    JournalEntry,
    Plan,
    Post,
    ReadingDailyLog,
    UserBadge,
)


def _register_and_login(
    client: TestClient,
    account: str,
    nickname: str = "挑战者",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": "SafePassword123!", "nickname": nickname},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "SafePassword123!"},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    return data["user"], data["csrf_token"]


def test_t0801_list_active_challenges_and_idempotent_join_validation(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0801: GET /challenges returns only active challenges; PUT membership is idempotent and rejects ended/inactive."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    c_active = Challenge(
        slug="sleep-7d",
        title="连续 7 日睡眠记录",
        description="每天记录睡眠时长",
        rule_type="journal_sleep",
        target_days=7,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="好眠伙伴",
        active=True,
    )
    c_ended = Challenge(
        slug="past-walk",
        title="已结束步行挑战",
        description="上月挑战",
        rule_type="plan_checkin",
        target_days=5,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 15),
        badge_title="往期徽章",
        active=True,
    )
    c_inactive = Challenge(
        slug="hidden-chal",
        title="已下线挑战",
        description="不可见",
        rule_type="read_article",
        target_days=3,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="下线徽章",
        active=False,
    )
    db_session.add_all([c_active, c_ended, c_inactive])
    db_session.commit()
    active_id, ended_id, inactive_id = c_active.id, c_ended.id, c_inactive.id

    with TestClient(app_instance) as client:
        res_list = client.get("/api/v1/challenges")
        assert res_list.status_code == 200, res_list.text
        slugs = [c["slug"] for c in res_list.json()["items"]]
        assert "sleep-7d" in slugs
        assert "hidden-chal" not in slugs

        u, csrf = _register_and_login(client, "chal_joiner", "晓风")
        headers = {"X-CSRF-Token": csrf}

        # Join twice -> idempotent, only 1 row
        j1 = client.put(f"/api/v1/challenges/{active_id}/membership", headers=headers)
        assert j1.status_code == 200, j1.text
        j2 = client.put(f"/api/v1/challenges/{active_id}/membership", headers=headers)
        assert j2.status_code == 200, j2.text
        assert j1.json()["membership_id"] == j2.json()["membership_id"]

        count = db_session.scalar(
            select(func.count()).where(
                ChallengeMembership.challenge_id == active_id,
                ChallengeMembership.user_id == u["id"],
            )
        )
        assert count == 1

        # Ended -> 422, Inactive -> 404
        assert client.put(f"/api/v1/challenges/{ended_id}/membership", headers=headers).status_code == 422
        assert client.put(f"/api/v1/challenges/{inactive_id}/membership", headers=headers).status_code == 404


def test_t0802_distinct_daily_progress_across_all_rule_types(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0802: Multiple events on same local_date count as at most 1 day; events before joined_date or null sleep excluded."""
    fake_clock.set(datetime(2026, 11, 24, 8, 0, 0, tzinfo=timezone.utc))

    c_sleep = Challenge(
        slug="rule-sleep",
        title="睡眠记录挑战",
        description="记录睡眠",
        rule_type="journal_sleep",
        target_days=5,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="睡眠达人",
        active=True,
    )
    c_read = Challenge(
        slug="rule-read",
        title="科普阅读挑战",
        description="阅读科普",
        rule_type="read_article",
        target_days=5,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="科普达人",
        active=True,
    )
    c_plan = Challenge(
        slug="rule-plan",
        title="计划打卡挑战",
        description="完成计划",
        rule_type="plan_checkin",
        target_days=5,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="行动达人",
        active=True,
    )
    db_session.add_all([c_sleep, c_read, c_plan])
    db_session.commit()
    sleep_id, read_id, plan_id = c_sleep.id, c_read.id, c_plan.id

    with TestClient(app_instance) as client:
        u, csrf = _register_and_login(client, "chal_progress", "晨曦")
        headers = {"X-CSRF-Token": csrf}

        # Join all 3 on 2026-11-24
        for cid in (sleep_id, read_id, plan_id):
            assert client.put(f"/api/v1/challenges/{cid}/membership", headers=headers).status_code == 200

        # Advance clock to 2026-11-26
        fake_clock.set(datetime(2026, 11, 26, 8, 0, 0, tzinfo=timezone.utc))

        p1 = Plan(owner_id=u["id"], title="散步", active=True)
        p2 = Plan(owner_id=u["id"], title="拉伸", active=True)
        db_session.add_all([p1, p2])
        db_session.flush()

        db_session.add_all(
            [
                # Before joined_date (Nov 23) -> must NOT count
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 23), sleep_minutes=450),
                # Nov 24 valid sleep -> +1
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 24), sleep_minutes=420),
                # Nov 25 sleep_minutes is None -> must NOT count for journal_sleep
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 25), sleep_minutes=None, activity_minutes=20),
                # Nov 26 valid sleep -> +1 (total sleep days = 2)
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 26), sleep_minutes=480),
                # Reading log on Nov 24 & Nov 26 -> 2 days (Nov 22 before join ignored)
                ReadingDailyLog(user_id=u["id"], local_date=date(2026, 11, 22)),
                ReadingDailyLog(user_id=u["id"], local_date=date(2026, 11, 24)),
                ReadingDailyLog(user_id=u["id"], local_date=date(2026, 11, 26)),
                # Multiple plan checkins on SAME date Nov 25 (p1 & p2) -> counts as ONLY 1 day!
                Checkin(plan_id=p1.id, local_date=date(2026, 11, 25), completed=True),
                Checkin(plan_id=p2.id, local_date=date(2026, 11, 25), completed=True),
                # Incomplete checkin on Nov 26 -> does NOT count
                Checkin(plan_id=p1.id, local_date=date(2026, 11, 26), completed=False),
            ]
        )
        db_session.commit()

        res = client.get("/api/v1/me/challenges")
        assert res.status_code == 200, res.text
        by_slug = {item["slug"]: item for item in res.json()["items"]}
        assert by_slug["rule-sleep"]["progress_days"] == 2
        assert by_slug["rule-read"]["progress_days"] == 2
        assert by_slug["rule-plan"]["progress_days"] == 1


def test_t0803_badge_awarded_idempotently_when_reaching_target_days(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0803: Achieving target_days creates UserBadge once and repeated GET /me/challenges never duplicates it."""
    fake_clock.set(datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc))

    chal = Challenge(
        slug="badge-2d",
        title="两日阅读体验",
        description="两天阅读",
        rule_type="read_article",
        target_days=2,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="好学徽章",
        active=True,
    )
    db_session.add(chal)
    db_session.commit()
    chal_id = chal.id

    with TestClient(app_instance) as client:
        u, csrf = _register_and_login(client, "badge_winner", "摘星")
        assert client.put(f"/api/v1/challenges/{chal_id}/membership", headers={"X-CSRF-Token": csrf}).status_code == 200

        fake_clock.set(datetime(2026, 11, 25, 8, 0, 0, tzinfo=timezone.utc))
        db_session.add_all(
            [
                ReadingDailyLog(user_id=u["id"], local_date=date(2026, 11, 23)),
                ReadingDailyLog(user_id=u["id"], local_date=date(2026, 11, 24)),
            ]
        )
        db_session.commit()

        for _ in range(3):
            r = client.get("/api/v1/me/challenges")
            assert r.status_code == 200
            assert len(r.json()["badges"]) == 1
            assert r.json()["badges"][0]["badge_title"] == "好学徽章"

        badge_count = db_session.scalar(select(func.count()).where(UserBadge.user_id == u["id"]))
        assert badge_count == 1


def test_t0804_leaving_challenge_freezes_progress_after_left_date(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0804: DELETE membership sets status='left' and left_date=today; subsequent days' logs do not increment progress."""
    fake_clock.set(datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc))

    chal = Challenge(
        slug="leave-test",
        title="五日睡眠挑战",
        description="描述",
        rule_type="journal_sleep",
        target_days=5,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="坚持徽章",
        active=True,
    )
    db_session.add(chal)
    db_session.commit()
    chal_id = chal.id

    with TestClient(app_instance) as client:
        u, csrf = _register_and_login(client, "leave_user", "云舒")
        headers = {"X-CSRF-Token": csrf}

        assert client.put(f"/api/v1/challenges/{chal_id}/membership", headers=headers).status_code == 200
        db_session.add(JournalEntry(user_id=u["id"], local_date=date(2026, 11, 23), sleep_minutes=450))
        db_session.commit()

        # Advance to Nov 24 and leave
        fake_clock.set(datetime(2026, 11, 24, 8, 0, 0, tzinfo=timezone.utc))
        leave_res = client.delete(f"/api/v1/challenges/{chal_id}/membership", headers=headers)
        assert leave_res.status_code == 200
        assert leave_res.json()["status"] == "left"
        assert leave_res.json()["left_date"] == "2026-11-24"

        # Advance to Nov 26 and log sleep on Nov 25 & Nov 26 -> must NOT count
        fake_clock.set(datetime(2026, 11, 26, 8, 0, 0, tzinfo=timezone.utc))
        db_session.add_all(
            [
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 25), sleep_minutes=460),
                JournalEntry(user_id=u["id"], local_date=date(2026, 11, 26), sleep_minutes=470),
            ]
        )
        db_session.commit()

        me_chal = client.get("/api/v1/me/challenges").json()
        assert me_chal["items"][0]["status"] == "left"
        assert me_chal["items"][0]["progress_days"] == 1


def test_t0805_challenges_private_by_default_and_shared_only_on_explicit_action(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0805: GET /users/{id} never exposes private challenges/badges; only explicit POST /share creates public Post."""
    fake_clock.set(datetime(2026, 11, 24, 8, 0, 0, tzinfo=timezone.utc))

    chal = Challenge(
        slug="share-chal",
        title="温和有氧打卡",
        description="记录日常运动",
        rule_type="journal_sleep",
        target_days=1,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 30),
        badge_title="活力徽章",
        active=True,
    )
    db_session.add(chal)
    db_session.commit()
    chal_id = chal.id

    with TestClient(app_instance) as client, TestClient(app_instance) as viewer:
        u, csrf = _register_and_login(client, "share_owner", "映雪")
        headers = {"X-CSRF-Token": csrf}

        assert client.put(f"/api/v1/challenges/{chal_id}/membership", headers=headers).status_code == 200
        db_session.add(JournalEntry(user_id=u["id"], local_date=date(2026, 11, 24), sleep_minutes=460))
        db_session.commit()

        # Trigger badge computation
        assert len(client.get("/api/v1/me/challenges").json()["badges"]) == 1

        # Public profile before explicit share: no auto post, no challenges/badges fields
        pub_before = viewer.get(f"/api/v1/users/{u['id']}")
        assert pub_before.status_code == 200
        pub_json = pub_before.json()
        assert "challenges" not in pub_json
        assert "badges" not in pub_json
        assert pub_json["recent_posts"] == []
        assert db_session.scalar(select(func.count()).where(Post.author_id == u["id"])) == 0

        # Explicit share creates 201 public Post
        share_res = client.post(f"/api/v1/me/challenges/{chal_id}/share", headers=headers)
        assert share_res.status_code == 201, share_res.text
        assert share_res.json()["post"]["category"] == "运动与习惯"
        assert "温和有氧打卡" in share_res.json()["post"]["title"]

        pub_after = viewer.get(f"/api/v1/users/{u['id']}").json()
        assert "challenges" not in pub_after
        assert "badges" not in pub_after
        assert len(pub_after["recent_posts"]) == 1
