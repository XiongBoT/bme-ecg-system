from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import Checkin, Notification, PlanVersion


def _register_and_login(
    client: TestClient,
    account: str = "plan_user",
    password: str = "SafePass123!",
    nickname: str = "安然",
    tz: str = "Asia/Shanghai",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": password, "nickname": nickname, "timezone": tz},
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["user"], body["csrf_token"]


def test_t0401_templates_and_create_plan_visible_in_today(client: TestClient, db_session: Session):
    """T-0401: Plan templates list non-clinical habits; created plan appears in /me/plans and /me/today."""
    _, csrf = _register_and_login(client, account="p_t0401")
    headers = {"X-CSRF-Token": csrf}

    tpl_res = client.get("/api/v1/plan-templates")
    assert tpl_res.status_code == 200, tpl_res.text
    templates = tpl_res.json()["items"]
    keys = [t["key"] for t in templates]
    assert keys == ["sleep_log", "read_knowledge", "walk_habit", "relax_breathing"]

    created = client.post(
        "/api/v1/me/plans",
        json={
            "title": "晚饭后温和散步",
            "template_key": "walk_habit",
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "reminder_enabled": True,
            "reminder_time": "19:30",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    plan_data = created.json()
    plan_id = plan_data["id"]
    assert plan_data["title"] == "晚饭后温和散步"
    assert plan_data["weekdays"] == [1, 2, 3, 4, 5, 6, 7]
    assert plan_data["today_due"] is True
    assert plan_data["today_completed"] is False
    assert plan_data["streak"] == 0

    plans_list = client.get("/api/v1/me/plans")
    assert plans_list.status_code == 200
    assert len(plans_list.json()["items"]) == 1

    today_view = client.get("/api/v1/me/today")
    assert today_view.status_code == 200
    tv = today_view.json()
    assert tv["date"] == "2026-11-25"
    assert tv["due_count"] == 1
    assert tv["completed_count"] == 0
    assert tv["items"][0]["id"] == plan_id

    vers = db_session.scalars(select(PlanVersion).where(PlanVersion.plan_id == plan_id)).all()
    assert len(vers) == 1
    assert vers[0].version_num == 1
    assert vers[0].weekday_mask == 127


def test_t0402_schedule_filtering_and_reject_non_due_checkin(client: TestClient):
    """T-0402: Non-due weekday or future start_date plans excluded from /me/today and reject checkins."""
    # Default fake_clock is Wednesday 2026-11-25 (isoweekday == 3)
    _, csrf = _register_and_login(client, account="p_t0402")
    headers = {"X-CSRF-Token": csrf}

    # Validation checks on POST /me/plans
    assert client.post("/api/v1/me/plans", json={"title": "   "}, headers=headers).status_code == 422
    assert client.post("/api/v1/me/plans", json={"title": "空星期", "weekdays": []}, headers=headers).status_code == 422
    assert client.post("/api/v1/me/plans", json={"title": "坏星期", "weekdays": [0, 8]}, headers=headers).status_code == 422
    assert (
        client.post(
            "/api/v1/me/plans",
            json={"title": "倒置日期", "start_date": "2026-11-28", "end_date": "2026-11-26"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/me/plans",
            json={"title": "坏提醒时间", "reminder_enabled": True, "reminder_time": "25:99"},
            headers=headers,
        ).status_code
        == 422
    )

    p_tuethu = client.post(
        "/api/v1/me/plans",
        json={"title": "周二周四拉伸", "weekdays": [2, 4]},
        headers=headers,
    ).json()
    p_future = client.post(
        "/api/v1/me/plans",
        json={"title": "下周开始阅读", "start_date": "2026-11-27", "weekdays": [1, 2, 3, 4, 5, 6, 7]},
        headers=headers,
    ).json()
    p_wed = client.post(
        "/api/v1/me/plans",
        json={"title": "一三五呼吸练习", "weekdays": [1, 3, 5]},
        headers=headers,
    ).json()

    today_res = client.get("/api/v1/me/today").json()
    assert today_res["due_count"] == 1
    assert [it["id"] for it in today_res["items"]] == [p_wed["id"]]

    # Non-due weekday checkin rejected with 422
    bad_weekday = client.put(
        f"/api/v1/me/plans/{p_tuethu['id']}/checkins/2026-11-25",
        headers=headers,
    )
    assert bad_weekday.status_code == 422

    # Checkin before start_date rejected with 422
    before_start = client.put(
        f"/api/v1/me/plans/{p_future['id']}/checkins/2026-11-25",
        headers=headers,
    )
    assert before_start.status_code == 422


def test_t0403_checkin_put_idempotent(client: TestClient, db_session: Session):
    """T-0403: Repeated PUT checkins on the same due date are idempotent without double counting."""
    _, csrf = _register_and_login(client, account="p_t0403")
    headers = {"X-CSRF-Token": csrf}

    plan = client.post(
        "/api/v1/me/plans",
        json={"title": "每日记录睡眠", "weekdays": [1, 2, 3, 4, 5, 6, 7]},
        headers=headers,
    ).json()

    for _ in range(3):
        res = client.put(f"/api/v1/me/plans/{plan['id']}/checkins/2026-11-25", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["completed"] is True
        assert body["streak"] == 1
        assert body["total_completed"] == 1

    tv = client.get("/api/v1/me/today").json()
    assert tv["due_count"] == 1
    assert tv["completed_count"] == 1

    db_session.expire_all()
    cnt = db_session.scalar(select(func.count()).select_from(Checkin).where(Checkin.plan_id == plan["id"]))
    assert cnt == 1


def test_t0404_checkin_delete_idempotent_no_negative_counts(client: TestClient):
    """T-0404: Repeated DELETE checkins keep plan uncompleted and never produce negative counts."""
    _, csrf = _register_and_login(client, account="p_t0404")
    headers = {"X-CSRF-Token": csrf}

    plan = client.post(
        "/api/v1/me/plans",
        json={"title": "睡前五分钟平缓呼吸", "weekdays": [1, 2, 3, 4, 5, 6, 7]},
        headers=headers,
    ).json()

    # Delete before ever checking in
    d0 = client.delete(f"/api/v1/me/plans/{plan['id']}/checkins/2026-11-25", headers=headers)
    assert d0.status_code == 200
    assert d0.json()["completed"] is False
    assert d0.json()["total_completed"] == 0

    # Check in then delete twice
    assert client.put(f"/api/v1/me/plans/{plan['id']}/checkins/2026-11-25", headers=headers).status_code == 200
    assert client.get("/api/v1/me/today").json()["completed_count"] == 1

    for _ in range(2):
        del_res = client.delete(f"/api/v1/me/plans/{plan['id']}/checkins/2026-11-25", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["completed"] is False
        assert del_res.json()["streak"] == 0
        assert del_res.json()["total_completed"] == 0

    tv = client.get("/api/v1/me/today").json()
    assert tv["completed_count"] == 0


def test_t0405_checkin_security_and_boundary_guards(app_instance):
    """T-0405: Reject other user's plan (404), future date (422), out-of-range date (422), and missing CSRF (403)."""
    with TestClient(app_instance) as ca:
        _, csrf_a = _register_and_login(ca, account="plan_alice")
        plan_a = ca.post(
            "/api/v1/me/plans",
            json={"title": "甲的习惯", "start_date": "2026-11-24", "weekdays": [1, 2, 3, 4, 5, 6, 7]},
            headers={"X-CSRF-Token": csrf_a},
        )
        assert plan_a.status_code == 201
        pid = plan_a.json()["id"]

        # Future date checkin -> 422
        fut = ca.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-26", headers={"X-CSRF-Token": csrf_a})
        assert fut.status_code == 422

        # Before start_date -> 422
        early = ca.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-20", headers={"X-CSRF-Token": csrf_a})
        assert early.status_code == 422

        # Missing CSRF -> 403
        assert ca.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-25").status_code == 403
        assert ca.delete(f"/api/v1/me/plans/{pid}/checkins/2026-11-25").status_code == 403

    with TestClient(app_instance) as cb:
        _, csrf_b = _register_and_login(cb, account="plan_bob")
        hb = {"X-CSRF-Token": csrf_b}
        assert cb.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-25", headers=hb).status_code == 404
        assert cb.delete(f"/api/v1/me/plans/{pid}/checkins/2026-11-25", headers=hb).status_code == 404
        assert cb.patch(f"/api/v1/me/plans/{pid}", json={"title": "篡改"}, headers=hb).status_code == 404


def test_t0406_streak_calculation_and_today_uncompleted_grace(client: TestClient, fake_clock: FakeClock):
    """T-0406: Streak spans scheduled due dates, skips uncompleted today_local, and breaks on missed past due day."""
    from app.plans.service import calculate_streak, mask_to_weekdays, weekdays_to_mask

    mask = weekdays_to_mask([1, 3, 5])
    assert mask_to_weekdays(mask) == [1, 3, 5]

    due = [date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 25)]
    done = {date(2026, 11, 16), date(2026, 11, 20), date(2026, 11, 23)}
    assert calculate_streak(due, done, date(2026, 11, 25)) == 2

    _, csrf = _register_and_login(client, account="p_t0406")
    headers = {"X-CSRF-Token": csrf}

    plan = client.post(
        "/api/v1/me/plans",
        json={"title": "一三五科普阅读", "start_date": "2026-11-16", "weekdays": [1, 3, 5]},
        headers=headers,
    ).json()
    pid = plan["id"]

    # Complete 11-16 (Mon), miss 11-18 (Wed), complete 11-20 (Fri) & 11-23 (Mon); today 11-25 (Wed) uncompleted
    assert client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-16", headers=headers).status_code == 200
    assert client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-20", headers=headers).status_code == 200
    r_mon = client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-23", headers=headers)
    assert r_mon.status_code == 200
    assert r_mon.json()["streak"] == 2

    # Completing today (Wednesday 2026-11-25) bumps streak to 3
    r_wed = client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-25", headers=headers)
    assert r_wed.status_code == 200
    assert r_wed.json()["streak"] == 3

    # Advance clock to Saturday 2026-11-28 (leaving Friday 2026-11-27 missed) -> streak breaks to 0
    fake_clock.set(datetime(2026, 11, 28, 10, 0, 0, tzinfo=timezone.utc))
    listed = client.get("/api/v1/me/plans").json()["items"]
    assert listed[0]["streak"] == 0


def test_t0407_versioned_plan_patch_preserves_past_history(
    client: TestClient,
    fake_clock: FakeClock,
    db_session: Session,
):
    """T-0407: PATCH schedule/end_date takes effect on next_day without rewriting historical denominators."""
    from app.plans.service import get_effective_version, is_plan_due_on_date

    # Start on Monday 2026-11-23
    fake_clock.set(datetime(2026, 11, 23, 9, 0, 0, tzinfo=timezone.utc))
    _, csrf = _register_and_login(client, account="p_t0407", tz="Asia/Shanghai")
    headers = {"X-CSRF-Token": csrf}

    plan = client.post(
        "/api/v1/me/plans",
        json={"title": "每日温和散步", "weekdays": [1, 2, 3, 4, 5, 6, 7]},
        headers=headers,
    ).json()
    pid = plan["id"]

    assert client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-23", headers=headers).status_code == 200

    # Move to Wednesday 2026-11-25 (Tuesday 11-24 was missed)
    fake_clock.set(datetime(2026, 11, 25, 9, 0, 0, tzinfo=timezone.utc))
    assert client.put(f"/api/v1/me/plans/{pid}/checkins/2026-11-25", headers=headers).status_code == 200

    # Patch schedule on 2026-11-25 to Mon/Wed/Fri only, then patch again on same day
    patch1 = client.patch(
        f"/api/v1/me/plans/{pid}",
        json={"weekdays": [1, 3, 5]},
        headers=headers,
    )
    assert patch1.status_code == 200, patch1.text

    patch2 = client.patch(
        f"/api/v1/me/plans/{pid}",
        json={"title": "一三五温和散步", "end_date": "2026-12-31"},
        headers=headers,
    )
    assert patch2.status_code == 200, patch2.text
    assert patch2.json()["title"] == "一三五温和散步"
    assert patch2.json()["weekdays"] == [1, 3, 5]
    assert patch2.json()["end_date"] == "2026-12-31"

    db_session.expire_all()
    versions = list(
        db_session.scalars(
            select(PlanVersion).where(PlanVersion.plan_id == pid).order_by(PlanVersion.version_num)
        ).all()
    )
    assert len(versions) == 2
    assert versions[0].effective_from == date(2026, 11, 23)
    assert versions[0].effective_to == date(2026, 11, 25)
    assert versions[0].weekday_mask == 127

    assert versions[1].effective_from == date(2026, 11, 26)
    assert versions[1].effective_to is None
    assert versions[1].weekday_mask == 21
    assert versions[1].end_date == date(2026, 12, 31)

    # Past Tuesday 2026-11-24 retains daily schedule (still due -> historical denominator for Mon..Wed stays 3!)
    assert get_effective_version(versions, date(2026, 11, 24)).version_num == 1
    assert is_plan_due_on_date(versions, date(2026, 11, 24)) is True
    historical_due = [
        d for d in (date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)) if is_plan_due_on_date(versions, d)
    ]
    assert len(historical_due) == 3

    # Upcoming Thursday 2026-11-26 follows v2 (not due), Friday 2026-11-27 is due
    assert is_plan_due_on_date(versions, date(2026, 11, 26)) is False
    assert is_plan_due_on_date(versions, date(2026, 11, 27)) is True


def test_t0408_reminder_polling_time_threshold_and_idempotent_dedup(
    client: TestClient,
    fake_clock: FakeClock,
    db_session: Session,
):
    """T-0408: Poll generates notification at/after reminder_time once per (plan, date) idempotently."""
    # 2026-11-25 11:00 UTC == 19:00 Asia/Shanghai
    fake_clock.set(datetime(2026, 11, 25, 11, 0, 0, tzinfo=timezone.utc))
    user, csrf = _register_and_login(client, account="p_t0408", tz="Asia/Shanghai")
    headers = {"X-CSRF-Token": csrf}

    plan = client.post(
        "/api/v1/me/plans",
        json={
            "title": "每日记录睡眠",
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "reminder_enabled": True,
            "reminder_time": "20:00",
        },
        headers=headers,
    ).json()

    early_poll = client.post("/api/v1/me/reminders/poll", headers=headers)
    assert early_poll.status_code == 200
    assert early_poll.json() == {"generated": 0}

    # Advance to 2026-11-25 12:05 UTC == 20:05 Asia/Shanghai
    fake_clock.set(datetime(2026, 11, 25, 12, 5, 0, tzinfo=timezone.utc))
    due_poll = client.post("/api/v1/me/reminders/poll", headers=headers)
    assert due_poll.status_code == 200
    assert due_poll.json() == {"generated": 1}

    # Repeat poll and /me/today on same day -> idempotent deduplication
    repeat_poll = client.post("/api/v1/me/reminders/poll", headers=headers)
    assert repeat_poll.status_code == 200
    assert repeat_poll.json() == {"generated": 0}
    assert client.get("/api/v1/me/today").status_code == 200

    db_session.expire_all()
    notifs = db_session.scalars(
        select(Notification).where(Notification.recipient_id == user["id"])
    ).all()
    assert len(notifs) == 1
    assert notifs[0].type == "plan_reminder"
    assert notifs[0].target_type == "plan"
    assert notifs[0].target_id == plan["id"]
    assert notifs[0].summary == "今日计划待完成：每日记录睡眠"
    assert notifs[0].dedup_key == f"plan_reminder:{plan['id']}:2026-11-25"


def test_t0409_reminder_suppressed_when_completed_disabled_archived_or_not_due(
    client: TestClient,
    fake_clock: FakeClock,
    db_session: Session,
):
    """T-0409: Reminders suppressed when checked in today, reminder disabled, plan archived, or not due today."""
    # 2026-11-25 13:00 UTC == 21:00 Asia/Shanghai (Wednesday, isoweekday=3)
    fake_clock.set(datetime(2026, 11, 25, 13, 0, 0, tzinfo=timezone.utc))
    user, csrf = _register_and_login(client, account="p_t0409", tz="Asia/Shanghai")
    headers = {"X-CSRF-Token": csrf}

    # 1) Already completed today
    p_done = client.post(
        "/api/v1/me/plans",
        json={"title": "已完成计划", "weekdays": [1, 2, 3, 4, 5, 6, 7], "reminder_enabled": True, "reminder_time": "20:00"},
        headers=headers,
    ).json()
    assert client.put(f"/api/v1/me/plans/{p_done['id']}/checkins/2026-11-25", headers=headers).status_code == 200

    # 2) Reminder disabled via PATCH
    p_disabled = client.post(
        "/api/v1/me/plans",
        json={"title": "关提醒计划", "weekdays": [1, 2, 3, 4, 5, 6, 7], "reminder_enabled": True, "reminder_time": "20:00"},
        headers=headers,
    ).json()
    assert (
        client.patch(f"/api/v1/me/plans/{p_disabled['id']}", json={"reminder_enabled": False}, headers=headers).status_code
        == 200
    )

    # 3) Plan archived (active=False) via PATCH immediately stops today's reminder
    p_archived = client.post(
        "/api/v1/me/plans",
        json={"title": "已暂停计划", "weekdays": [1, 2, 3, 4, 5, 6, 7], "reminder_enabled": True, "reminder_time": "20:00"},
        headers=headers,
    ).json()
    assert client.patch(f"/api/v1/me/plans/{p_archived['id']}", json={"active": False}, headers=headers).status_code == 200

    # 4) Not due on Wednesday
    client.post(
        "/api/v1/me/plans",
        json={"title": "周二计划", "weekdays": [2], "reminder_enabled": True, "reminder_time": "20:00"},
        headers=headers,
    )

    poll = client.post("/api/v1/me/reminders/poll", headers=headers)
    assert poll.status_code == 200
    assert poll.json() == {"generated": 0}

    db_session.expire_all()
    cnt = db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.recipient_id == user["id"])
    )
    assert cnt == 0
