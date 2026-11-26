from __future__ import annotations

import json
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import (
    Article,
    Checkin,
    Comment,
    JournalEntry,
    Notification,
    Plan,
    PlanVersion,
    Post,
)


def _register_and_login(
    client: TestClient,
    account: str,
    nickname: str = "测试用户",
    tz: str = "Asia/Shanghai",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "account": account,
            "password": "SafePassword123!",
            "nickname": nickname,
            "timezone": tz,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "SafePassword123!"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    return body["user"], body["csrf_token"]


def test_t0601_dashboard_unrecorded_never_fakes_zero_and_recommendations_public_order(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0601: Unrecorded today_journal returns recorded=False with None fields (never fake 0);
    recommended_articles strictly follow public published_at DESC order regardless of private journals.
    """
    # 2026-11-25 10:00 UTC -> 2026-11-25 18:00 Asia/Shanghai (Wednesday)
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        user, _ = _register_and_login(client, "dash_user", "晴川")

        # Seed published & draft articles and visible & hidden posts
        a_old = Article(
            slug="diet-guide",
            editor_id=user["id"],
            status="published",
            title="清淡饮食指南",
            summary="减少钠盐摄入",
            category="日常饮食",
            body="正文一",
            published_at=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc),
        )
        a_new = Article(
            slug="walk-guide",
            editor_id=user["id"],
            status="published",
            title="温和步行习惯",
            summary="循序渐进散步",
            category="运动康复",
            body="正文二",
            published_at=datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc),
        )
        a_sleep = Article(
            slug="sleep-guide",
            editor_id=user["id"],
            status="published",
            title="规律作息科普",
            summary="睡前放松环境",
            category="睡眠管理",
            body="正文三",
            published_at=datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc),
        )
        a_draft = Article(
            slug="draft-secret",
            editor_id=user["id"],
            status="draft",
            title="未发布草稿",
            summary="不应展示",
            category="睡眠管理",
            body="草稿",
        )
        p_vis = Post(
            author_id=user["id"],
            category="运动与习惯",
            title="今天傍晚散步二十分钟",
            body="微风很舒服",
            status="visible",
            created_at=datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc),
        )
        p_hid = Post(
            author_id=user["id"],
            category="运动与习惯",
            title="已隐藏帖子",
            body="不应出现在首页精选",
            status="hidden",
            created_at=datetime(2026, 11, 25, 9, 30, tzinfo=timezone.utc),
        )
        p_plan = Plan(owner_id=user["id"], title="晚间拉伸 10 分钟", active=True)
        db_session.add_all([a_old, a_new, a_sleep, a_draft, p_vis, p_hid, p_plan])
        db_session.flush()
        db_session.add(
            PlanVersion(
                plan_id=p_plan.id,
                version_num=1,
                effective_from=date(2026, 11, 23),
                effective_to=None,
                weekday_mask=127,
                active=True,
                start_date=date(2026, 11, 23),
            )
        )
        db_session.add(
            Notification(
                recipient_id=user["id"],
                type="post_comment",
                target_type="post",
                target_id=p_vis.id,
                summary="有人评论了你的分享",
                dedup_key="dash-notif-1",
                created_at=fake_clock.now(),
            )
        )
        # Private journal yesterday mentioning sleep symptoms - must NOT reorder articles
        db_session.add(
            JournalEntry(
                user_id=user["id"],
                local_date=date(2026, 11, 24),
                sleep_minutes=360,
                activity_minutes=20,
                mood="平静",
                symptom_tags_json=json.dumps(["入睡慢", "睡眠管理"]),
                note="私密备注内容",
            )
        )
        db_session.commit()

        res = client.get("/api/v1/me/dashboard")
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["today_journal"] == {
            "recorded": False,
            "local_date": "2026-11-25",
            "sleep_minutes": None,
            "activity_minutes": None,
            "mood": None,
            "symptom_tags": [],
        }
        assert len(data["recent_journals"]) == 1
        assert data["recent_journals"][0]["local_date"] == "2026-11-24"
        assert data["plans_summary"]["due_count"] == 1
        assert data["plans_summary"]["completed_count"] == 0
        assert data["plans_summary"]["items"][0]["title"] == "晚间拉伸 10 分钟"
        assert data["plans_summary"]["items"][0]["completed"] is False

        # Strictly public published_at DESC order: walk-guide (Nov 24), sleep-guide (Nov 22), diet-guide (Nov 20)
        rec_titles = [a["title"] for a in data["recommended_articles"]]
        assert rec_titles == ["温和步行习惯", "规律作息科普", "清淡饮食指南"]

        hl_titles = [p["title"] for p in data["community_highlights"]]
        assert hl_titles == ["今天傍晚散步二十分钟"]
        assert data["unread_notifications_count"] == 1


def test_t0602_weekly_report_sleep_distinguishes_null_and_zero(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0602: [420, None, 0, 480] yields valid_days=3 and mean_minutes=300.0."""
    # Set local date to Thursday 2026-11-26 (Mon=23, Tue=24, Wed=25, Thu=26)
    fake_clock.set(datetime(2026, 11, 26, 4, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        user, _ = _register_and_login(client, "sleep_calc", "知秋")
        entries = [
            (date(2026, 11, 23), 420, 30, "愉悦"),
            (date(2026, 11, 24), None, 15, "平静"),
            (date(2026, 11, 25), 0, 0, "疲惫"),
            (date(2026, 11, 26), 480, None, "平静"),
        ]
        for d, slp, act, mood in entries:
            db_session.add(
                JournalEntry(
                    user_id=user["id"],
                    local_date=d,
                    sleep_minutes=slp,
                    activity_minutes=act,
                    mood=mood,
                )
            )
        db_session.commit()

        res = client.get("/api/v1/me/weekly-report")
        assert res.status_code == 200, res.text
        rep = res.json()
        assert rep["sleep"] == {"valid_days": 3, "mean_minutes": 300.0}
        assert rep["activity"] == {"valid_days": 3, "total_minutes": 45}
        assert rep["mood_distribution"] == {"平静": 2, "愉悦": 1, "疲惫": 1}


def test_t0603_plan_version_effective_window_preserves_historical_denominator(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0603: Changing schedule or archiving via PlanVersion does not retroactively alter past due counts."""
    # Sunday 2026-11-29 in Asia/Shanghai -> full 7 observed days [Nov 23..Nov 29]
    fake_clock.set(datetime(2026, 11, 29, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        user, _ = _register_and_login(client, "plan_ver_user", "修远")

        plan = Plan(owner_id=user["id"], title="晨间饮水", active=False)
        db_session.add(plan)
        db_session.flush()

        # v1: Mon Nov 23 .. Wed Nov 25, every day (mask=127) -> 3 due days
        # v2: Thu Nov 26 .. Fri Nov 27, only Fri (Fri isoweekday=5 -> bit 4 = 16) -> 1 due day (Fri Nov 27)
        # v3: Sat Nov 28 .. None, archived (active=False) -> 0 due days on Sat/Sun
        # Total due in week = 3 + 1 + 0 = 4!
        db_session.add_all(
            [
                PlanVersion(
                    plan_id=plan.id,
                    version_num=1,
                    effective_from=date(2026, 11, 23),
                    effective_to=date(2026, 11, 25),
                    weekday_mask=127,
                    active=True,
                    start_date=date(2026, 11, 23),
                ),
                PlanVersion(
                    plan_id=plan.id,
                    version_num=2,
                    effective_from=date(2026, 11, 26),
                    effective_to=date(2026, 11, 27),
                    weekday_mask=(1 << 4),
                    active=True,
                    start_date=date(2026, 11, 23),
                ),
                PlanVersion(
                    plan_id=plan.id,
                    version_num=3,
                    effective_from=date(2026, 11, 28),
                    effective_to=None,
                    weekday_mask=127,
                    active=False,
                    start_date=date(2026, 11, 23),
                ),
                Checkin(plan_id=plan.id, local_date=date(2026, 11, 23), completed=True),
                Checkin(plan_id=plan.id, local_date=date(2026, 11, 25), completed=True),
                Checkin(plan_id=plan.id, local_date=date(2026, 11, 27), completed=True),
            ]
        )
        db_session.commit()

        res = client.get("/api/v1/me/weekly-report")
        assert res.status_code == 200, res.text
        rep = res.json()
        assert rep["plans"] == {"due": 4, "completed": 3, "completion_rate": 0.75}


def test_t0604_empty_week_returns_null_metrics_never_fake_rates(
    app_instance,
    fake_clock: FakeClock,
):
    """T-0604: Empty week returns None for sleep.mean_minutes, activity.total_minutes, plans.completion_rate."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        _register_and_login(client, "empty_week_user", "空山")
        res = client.get("/api/v1/me/weekly-report")
        assert res.status_code == 200, res.text
        rep = res.json()
        assert rep["journal_days"] == 0
        assert rep["journal_coverage_rate"] == 0.0
        assert rep["sleep"] == {"valid_days": 0, "mean_minutes": None}
        assert rep["activity"] == {"valid_days": 0, "total_minutes": None}
        assert rep["plans"] == {"due": 0, "completed": 0, "completion_rate": None}


def test_t0605_partial_completed_and_future_week_boundaries(
    app_instance,
    fake_clock: FakeClock,
):
    """T-0605: Current week is partial_week; past week is completed_week (7 days); future or non-Monday rejected 422."""
    # Wednesday 2026-11-25 -> current_monday = 2026-11-23 -> observed_days = 3
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        _register_and_login(client, "week_bound_user", "行舟")

        cur = client.get("/api/v1/me/weekly-report")
        assert cur.status_code == 200
        assert cur.json()["status"] == "partial_week"
        assert cur.json()["observed_days"] == 3
        assert len(cur.json()["daily_series"]) == 3

        past = client.get("/api/v1/me/weekly-report?week_start=2026-11-16")
        assert past.status_code == 200
        assert past.json()["status"] == "completed_week"
        assert past.json()["observed_days"] == 7
        assert len(past.json()["daily_series"]) == 7

        future = client.get("/api/v1/me/weekly-report?week_start=2026-11-30")
        assert future.status_code == 422
        assert future.json()["error"]["code"] == "FUTURE_WEEK_FORBIDDEN"

        not_monday = client.get("/api/v1/me/weekly-report?week_start=2026-11-24")
        assert not_monday.status_code == 422


def test_t0606_live_recalculation_without_stale_cache_and_safe_daily_series(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0606: Modifying journals/checkins updates weekly-report immediately, and daily_series omits private note."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as client:
        user, _ = _register_and_login(client, "live_rep_user", "清溪")

        r1 = client.get("/api/v1/me/weekly-report")
        assert r1.status_code == 200
        assert r1.json()["journal_days"] == 0

        db_session.add(
            JournalEntry(
                user_id=user["id"],
                local_date=date(2026, 11, 25),
                sleep_minutes=450,
                activity_minutes=40,
                mood="愉悦",
                note="非常私密的个人日记备注不应出现在周报序列",
            )
        )
        db_session.commit()

        r2 = client.get("/api/v1/me/weekly-report")
        assert r2.status_code == 200
        rep2 = r2.json()
        assert rep2["journal_days"] == 1
        assert rep2["sleep"]["mean_minutes"] == 450.0
        assert "非常私密的个人日记备注不应出现在周报序列" not in r2.text
        for day_item in rep2["daily_series"]:
            assert "note" not in day_item


def test_t0607_weekly_report_strict_owner_scoping(
    app_instance,
    db_session: Session,
):
    """T-0607: User B cannot view User A's report; passing user_id query param is rejected; unauth gets 401."""
    with TestClient(app_instance) as anon:
        assert anon.get("/api/v1/me/weekly-report").status_code == 401
        assert anon.get("/api/v1/me/dashboard").status_code == 401

    with TestClient(app_instance) as ca, TestClient(app_instance) as cb:
        ua, _ = _register_and_login(ca, "owner_a", "甲")
        ub, _ = _register_and_login(cb, "owner_b", "乙")

        db_session.add(
            JournalEntry(
                user_id=ua["id"],
                local_date=date(2026, 11, 25),
                sleep_minutes=510,
                activity_minutes=60,
                mood="愉悦",
            )
        )
        db_session.commit()

        # User B trying to pass user_id param is rejected
        forged = cb.get(f"/api/v1/me/weekly-report?user_id={ua['id']}")
        assert forged.status_code == 422

        # User B normal call only sees B's empty data
        b_rep = cb.get("/api/v1/me/weekly-report")
        assert b_rep.status_code == 200
        assert b_rep.json()["journal_days"] == 0
        assert b_rep.json()["sleep"]["mean_minutes"] is None


def test_t0608_notifications_isolation_for_list_read_and_read_all(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0608: User B cannot list or mark User A's notifications as read; read-all only affects current user."""
    with TestClient(app_instance) as ca, TestClient(app_instance) as cb:
        ua, csrf_a = _register_and_login(ca, "notif_a", "甲")
        ub, csrf_b = _register_and_login(cb, "notif_b", "乙")

        post = Post(author_id=ua["id"], category="日常心情", title="晴天", body="好心情", status="visible")
        db_session.add(post)
        db_session.flush()

        na = Notification(
            recipient_id=ua["id"],
            type="post_comment",
            target_type="post",
            target_id=post.id,
            summary="甲收到的评论提醒",
            dedup_key="na-1",
            created_at=fake_clock.now(),
        )
        nb = Notification(
            recipient_id=ub["id"],
            type="post_comment",
            target_type="post",
            target_id=post.id,
            summary="乙收到的评论提醒",
            dedup_key="nb-1",
            created_at=fake_clock.now(),
        )
        db_session.add_all([na, nb])
        db_session.commit()
        na_id = na.id

        # B cannot mark A's notification read
        cross_read = cb.post(f"/api/v1/me/notifications/{na_id}/read", headers={"X-CSRF-Token": csrf_b})
        assert cross_read.status_code == 404

        # B calling read-all only marks B's notification
        read_all_b = cb.post("/api/v1/me/notifications/read-all", headers={"X-CSRF-Token": csrf_b})
        assert read_all_b.status_code == 200
        assert cb.get("/api/v1/me/notifications").json()["unread_count"] == 0

        # A's notification is still unread
        list_a = ca.get("/api/v1/me/notifications")
        assert list_a.status_code == 200
        assert list_a.json()["unread_count"] == 1
        assert list_a.json()["items"][0]["id"] == na_id

        # A marks own notification read
        ok_read = ca.post(f"/api/v1/me/notifications/{na_id}/read", headers={"X-CSRF-Token": csrf_a})
        assert ok_read.status_code == 200
        assert ca.get("/api/v1/me/notifications").json()["unread_count"] == 0


def test_t0609_notification_target_available_reflects_hidden_posts_and_comments_without_leak(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0609: Hidden post/comment marks target_available=False and scrubs summary so hidden text never leaks."""
    with TestClient(app_instance) as client:
        user, _ = _register_and_login(client, "notif_vis", "林深")

        p_ok = Post(author_id=user["id"], category="日常心情", title="公开帖", body="正常公开内容", status="visible")
        p_hid = Post(author_id=user["id"], category="日常心情", title="敏感隐藏帖", body="违规内容", status="hidden")
        db_session.add_all([p_ok, p_hid])
        db_session.flush()

        c_hid = Comment(
            post_id=p_ok.id,
            author_id=user["id"],
            body="被隐藏的敏感评论原文XYZ",
            status="hidden",
        )
        plan = Plan(owner_id=user["id"], title="喝水打卡", active=True)
        db_session.add_all([c_hid, plan])
        db_session.flush()

        db_session.add_all(
            [
                Notification(
                    recipient_id=user["id"],
                    type="post_comment",
                    target_type="post",
                    target_id=p_ok.id,
                    summary="有人回复了公开帖",
                    dedup_key="k1",
                    created_at=fake_clock.now(),
                ),
                Notification(
                    recipient_id=user["id"],
                    type="post_comment",
                    target_type="post",
                    target_id=p_hid.id,
                    summary="泄露测试：敏感隐藏帖摘要片段ABC",
                    dedup_key="k2",
                    created_at=fake_clock.now(),
                ),
                Notification(
                    recipient_id=user["id"],
                    type="comment_reply",
                    target_type="comment",
                    target_id=c_hid.id,
                    summary="泄露测试：被隐藏的敏感评论原文XYZ",
                    dedup_key="k3",
                    created_at=fake_clock.now(),
                ),
                Notification(
                    recipient_id=user["id"],
                    type="plan_reminder",
                    target_type="plan",
                    target_id=plan.id,
                    summary="今日习惯待完成：喝水打卡",
                    dedup_key="k4",
                    created_at=fake_clock.now(),
                ),
            ]
        )
        db_session.commit()

        res = client.get("/api/v1/me/notifications")
        assert res.status_code == 200, res.text
        items = {item["target_id"]: item for item in res.json()["items"]}

        assert items[p_ok.id]["target_available"] is True
        assert items[plan.id]["target_available"] is True
        assert items[p_hid.id]["target_available"] is False
        assert items[c_hid.id]["target_available"] is False

        assert "敏感隐藏帖摘要片段ABC" not in res.text
        assert "被隐藏的敏感评论原文XYZ" not in res.text
