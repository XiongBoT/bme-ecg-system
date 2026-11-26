from __future__ import annotations

from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import JournalEntry, User


def _register_and_login(
    client: TestClient,
    account: str = "journal_user",
    password: str = "SafePass123!",
    nickname: str = "清风",
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


def test_t0301_create_read_and_list_journals_desc(client: TestClient):
    """T-0301: Put journal entries, get single date, and list range ordered by local_date DESC."""
    _, csrf = _register_and_login(client, account="j_t0301")
    headers = {"X-CSRF-Token": csrf}

    r1 = client.put(
        "/api/v1/me/journals/2026-11-23",
        json={
            "sleep_minutes": 450,
            "activity_minutes": 35,
            "mood": "good",
            "symptom_tags": ["  晨起清爽  ", "午后微困"],
            "note": "早睡早起，整体精神不错。",
        },
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["local_date"] == "2026-11-23"
    assert d1["sleep_minutes"] == 450
    assert d1["activity_minutes"] == 35
    assert d1["mood"] == "good"
    assert d1["symptom_tags"] == ["晨起清爽", "午后微困"]
    assert d1["note"] == "早睡早起，整体精神不错。"

    r2 = client.put(
        "/api/v1/me/journals/2026-11-25",
        json={"sleep_minutes": 480, "mood": "very_good"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text

    r3 = client.put(
        "/api/v1/me/journals/2026-11-24",
        json={"activity_minutes": 20, "mood": "neutral", "note": "阴雨天室内拉伸"},
        headers=headers,
    )
    assert r3.status_code == 200, r3.text

    single = client.get("/api/v1/me/journals/2026-11-24")
    assert single.status_code == 200
    assert single.json()["note"] == "阴雨天室内拉伸"

    listed = client.get("/api/v1/me/journals?from=2026-11-23&to=2026-11-25")
    assert listed.status_code == 200
    dates = [item["local_date"] for item in listed.json()["items"]]
    assert dates == ["2026-11-25", "2026-11-24", "2026-11-23"]

    sub_range = client.get("/api/v1/me/journals?from=2026-11-24&to=2026-11-25")
    assert sub_range.status_code == 200
    assert [item["local_date"] for item in sub_range.json()["items"]] == ["2026-11-25", "2026-11-24"]


def test_t0302_same_day_upsert_updates_without_duplicate(client: TestClient, db_session: Session):
    """T-0302: Repeated PUT on same (user, local_date) updates in place without duplicate rows."""
    user, csrf = _register_and_login(client, account="j_t0302")
    headers = {"X-CSRF-Token": csrf}

    first = client.put(
        "/api/v1/me/journals/2026-11-25",
        json={"sleep_minutes": 390, "mood": "bad", "symptom_tags": ["熬夜"], "note": "昨晚睡晚了"},
        headers=headers,
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = client.put(
        "/api/v1/me/journals/2026-11-25",
        json={"sleep_minutes": 460, "activity_minutes": 40, "mood": "good", "symptom_tags": [], "note": "补记午休与散步"},
        headers=headers,
    )
    assert second.status_code == 200
    updated = second.json()
    assert updated["id"] == first_id
    assert updated["sleep_minutes"] == 460
    assert updated["activity_minutes"] == 40
    assert updated["mood"] == "good"
    assert updated["symptom_tags"] == []
    assert updated["note"] == "补记午休与散步"

    db_session.expire_all()
    count = db_session.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == user["id"]))
    assert count == 1


def test_t0303_null_vs_zero_strictly_distinguishable(client: TestClient, db_session: Session):
    """T-0303: null (not recorded) vs 0 (recorded zero minutes) remain strictly distinct."""
    user, csrf = _register_and_login(client, account="j_t0303")
    headers = {"X-CSRF-Token": csrf}

    res_a = client.put(
        "/api/v1/me/journals/2026-11-24",
        json={"sleep_minutes": 0, "activity_minutes": None},
        headers=headers,
    )
    assert res_a.status_code == 200, res_a.text
    body_a = res_a.json()
    assert body_a["sleep_minutes"] == 0
    assert body_a["sleep_minutes"] is not None
    assert body_a["activity_minutes"] is None

    res_b = client.put(
        "/api/v1/me/journals/2026-11-25",
        json={"sleep_minutes": None, "activity_minutes": 0},
        headers=headers,
    )
    assert res_b.status_code == 200, res_b.text
    body_b = res_b.json()
    assert body_b["sleep_minutes"] is None
    assert body_b["activity_minutes"] == 0
    assert body_b["activity_minutes"] is not None

    get_a = client.get("/api/v1/me/journals/2026-11-24").json()
    assert get_a["sleep_minutes"] == 0 and get_a["activity_minutes"] is None

    db_session.expire_all()
    row_a = db_session.scalar(
        select(JournalEntry).where(
            JournalEntry.user_id == user["id"],
            JournalEntry.local_date == datetime(2026, 11, 24).date(),
        )
    )
    assert row_a is not None
    assert row_a.sleep_minutes == 0
    assert row_a.activity_minutes is None


def test_t0304_reject_empty_invalid_and_future_journals(client: TestClient):
    """T-0304: Reject all-empty payload, out-of-bounds values, extra fields, and future local_date."""
    _, csrf = _register_and_login(client, account="j_t0304", tz="Asia/Shanghai")
    headers = {"X-CSRF-Token": csrf}

    # Empty or whitespace-only payloads
    assert client.put("/api/v1/me/journals/2026-11-25", json={}, headers=headers).status_code == 422
    assert (
        client.put(
            "/api/v1/me/journals/2026-11-25",
            json={"sleep_minutes": None, "activity_minutes": None, "mood": None, "symptom_tags": [], "note": "   "},
            headers=headers,
        ).status_code
        == 422
    )

    # Bounds and enum checks
    assert client.put("/api/v1/me/journals/2026-11-25", json={"sleep_minutes": -1}, headers=headers).status_code == 422
    assert client.put("/api/v1/me/journals/2026-11-25", json={"sleep_minutes": 1441}, headers=headers).status_code == 422
    assert client.put("/api/v1/me/journals/2026-11-25", json={"activity_minutes": 1500}, headers=headers).status_code == 422
    assert client.put("/api/v1/me/journals/2026-11-25", json={"mood": "amazing"}, headers=headers).status_code == 422
    assert (
        client.put(
            "/api/v1/me/journals/2026-11-25",
            json={"symptom_tags": [f"tag{i}" for i in range(11)]},
            headers=headers,
        ).status_code
        == 422
    )
    assert client.put("/api/v1/me/journals/2026-11-25", json={"symptom_tags": ["   "]}, headers=headers).status_code == 422
    assert client.put("/api/v1/me/journals/2026-11-25", json={"symptom_tags": ["x" * 31]}, headers=headers).status_code == 422
    assert client.put("/api/v1/me/journals/2026-11-25", json={"note": "字" * 1001}, headers=headers).status_code == 422

    # Extra forbidden field
    assert (
        client.put(
            "/api/v1/me/journals/2026-11-25",
            json={"sleep_minutes": 480, "user_id": "other_id"},
            headers=headers,
        ).status_code
        == 422
    )

    # Future date forbidden (clock is 2026-11-25 18:00 Asia/Shanghai)
    future_res = client.put(
        "/api/v1/me/journals/2026-11-26",
        json={"sleep_minutes": 480},
        headers=headers,
    )
    assert future_res.status_code == 422
    assert future_res.json()["error"]["code"] == "FUTURE_DATE_FORBIDDEN"


def test_t0305_strict_privacy_across_users_and_staff_roles(app_instance, db_session: Session):
    """T-0305: User B, moderator, and editor cannot read, list, or delete User A's private journals."""
    with TestClient(app_instance) as ca:
        ua, csrf_a = _register_and_login(ca, account="priv_alice", nickname="甲")
        no_csrf = ca.put("/api/v1/me/journals/2026-11-25", json={"sleep_minutes": 480})
        assert no_csrf.status_code == 403

        ok = ca.put(
            "/api/v1/me/journals/2026-11-25",
            json={"sleep_minutes": 480, "note": "甲的私密记录"},
            headers={"X-CSRF-Token": csrf_a},
        )
        assert ok.status_code == 200

    with TestClient(app_instance) as anon:
        assert anon.get("/api/v1/me/journals").status_code == 401
        assert anon.get("/api/v1/me/journals/2026-11-25").status_code == 401

    for acc, role_str in [("priv_bob", "member"), ("priv_mod", "member,moderator"), ("priv_ed", "member,editor")]:
        with TestClient(app_instance) as c_other:
            u_other, csrf_other = _register_and_login(c_other, account=acc, nickname=acc)
            if role_str != "member":
                row = db_session.scalar(select(User).where(User.id == u_other["id"]))
                assert row is not None
                row.roles = role_str
                db_session.commit()

            list_res = c_other.get(f"/api/v1/me/journals?user_id={ua['id']}")
            assert list_res.status_code == 200
            assert list_res.json()["items"] == []

            get_res = c_other.get("/api/v1/me/journals/2026-11-25")
            assert get_res.status_code == 404

            del_res = c_other.delete("/api/v1/me/journals/2026-11-25", headers={"X-CSRF-Token": csrf_other})
            assert del_res.status_code == 404

            pub = c_other.get(f"/api/v1/users/{ua['id']}")
            assert pub.status_code == 200
            assert "journals" not in pub.json()
            assert "甲的私密记录" not in pub.text

    with TestClient(app_instance) as ca_verify:
        ca_verify.post("/api/v1/auth/login", json={"account": "priv_alice", "password": "SafePass123!"})
        preserved = ca_verify.get("/api/v1/me/journals/2026-11-25")
        assert preserved.status_code == 200
        assert preserved.json()["note"] == "甲的私密记录"


def test_t0306_get_unrecorded_404_and_delete_lifecycle(client: TestClient):
    """T-0306: Unrecorded date returns 404 on GET/DELETE; existing entry deletes cleanly."""
    _, csrf = _register_and_login(client, account="j_t0306")
    headers = {"X-CSRF-Token": csrf}

    assert client.get("/api/v1/me/journals/2026-11-20").status_code == 404
    assert client.delete("/api/v1/me/journals/2026-11-20", headers=headers).status_code == 404

    put_res = client.put(
        "/api/v1/me/journals/2026-11-20",
        json={"sleep_minutes": 420, "mood": "neutral"},
        headers=headers,
    )
    assert put_res.status_code == 200
    assert client.get("/api/v1/me/journals/2026-11-20").status_code == 200

    del_res = client.delete("/api/v1/me/journals/2026-11-20", headers=headers)
    assert del_res.status_code == 200
    assert client.get("/api/v1/me/journals/2026-11-20").status_code == 404
    assert client.delete("/api/v1/me/journals/2026-11-20", headers=headers).status_code == 404


def test_t0307_timezone_cross_day_boundary(app_instance, fake_clock: FakeClock):
    """T-0307: Cross-day UTC instant allows 2026-11-26 in Asia/Shanghai while forbidding it in America/Los_Angeles."""
    # 2026-11-25 18:30 UTC == 2026-11-26 02:30 Asia/Shanghai == 2026-11-25 10:30 America/Los_Angeles
    fake_clock.set(datetime(2026, 11, 25, 18, 30, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as c_sh:
        _, csrf_sh = _register_and_login(c_sh, account="tz_shanghai", tz="Asia/Shanghai")
        sh_ok = c_sh.put(
            "/api/v1/me/journals/2026-11-26",
            json={"sleep_minutes": 450},
            headers={"X-CSRF-Token": csrf_sh},
        )
        assert sh_ok.status_code == 200, sh_ok.text

        sh_future = c_sh.put(
            "/api/v1/me/journals/2026-11-27",
            json={"sleep_minutes": 450},
            headers={"X-CSRF-Token": csrf_sh},
        )
        assert sh_future.status_code == 422
        assert sh_future.json()["error"]["code"] == "FUTURE_DATE_FORBIDDEN"

    with TestClient(app_instance) as c_la:
        _, csrf_la = _register_and_login(c_la, account="tz_losangeles", tz="America/Los_Angeles")
        la_future = c_la.put(
            "/api/v1/me/journals/2026-11-26",
            json={"sleep_minutes": 450},
            headers={"X-CSRF-Token": csrf_la},
        )
        assert la_future.status_code == 422
        assert la_future.json()["error"]["code"] == "FUTURE_DATE_FORBIDDEN"

        la_ok = c_la.put(
            "/api/v1/me/journals/2026-11-25",
            json={"sleep_minutes": 450},
            headers={"X-CSRF-Token": csrf_la},
        )
        assert la_ok.status_code == 200, la_ok.text
