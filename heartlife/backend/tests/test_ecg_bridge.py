from __future__ import annotations

from datetime import timedelta
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import EcgLink, User
from app.ecg.client import EcgClient, get_ecg_client


SECRET = "s" * 40
CODE = "c" * 32
TOKEN = "g" * 43
ECG_ID = "e" * 32


def login(client, name="alice"):
    response = client.post("/api/v1/auth/register", json={
        "account": name, "password": "ExamplePass123!", "nickname": name,
        "timezone": "Asia/Shanghai",
    })
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"account": name, "password": "ExamplePass123!"})
    assert response.status_code == 200
    return response.json()["user"]["id"], {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture()
def bridge(app_instance, test_settings, fake_clock):
    test_settings.ecg_api_base_url = "http://127.0.0.1:8766"
    test_settings.ecg_external_url = "https://ecg.example.test"
    test_settings.ecg_client_secret = SECRET
    calls = []
    state = {"outage": False, "wrong_owner": False, "invalid_grant": False,
             "measurement_allowed": False, "measurement_conflict": False,
             "wrong_week": False, "wrong_measurement": False, "control_forbidden": False}

    def handle(request):
        calls.append(request)
        assert request.headers["X-HeartLife-Key"] == SECRET
        if state["outage"]:
            raise httpx.ConnectError("private upstream details must not be exposed", request=request)
        if request.url.path == "/api/heartlife/exchange":
            assert json.loads(request.content)["code"] == CODE
            return httpx.Response(200, json={"grant_token": TOKEN, "ecg_user_id": ECG_ID,
                "ecg_username": "ecg_alice", "expires_at": (fake_clock.now() + timedelta(days=30)).timestamp(),
                "measurement_allowed": state["measurement_allowed"]})
        assert request.headers["X-HeartLife-Subject"]
        if request.method == "DELETE":
            return httpx.Response(200, json={"revoked": True})
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        if state["invalid_grant"]:
            return httpx.Response(401, json={"detail": "invalid"})
        if state["control_forbidden"] and request.url.path in ("/api/heartlife/devices", "/api/heartlife/measurements"):
            return httpx.Response(403, json={"detail": "private upstream authorization detail"})
        envelope = {
            "ecg_user": {"id": "f" * 32 if state["wrong_owner"] else ECG_ID, "username": "ecg_alice"},
            "expires_at": (fake_clock.now() + timedelta(days=30)).timestamp(),
            "measurement_allowed": state["measurement_allowed"],
        }
        if request.url.path == "/api/heartlife/devices":
            return httpx.Response(200, json={**envelope, "devices": [{
                "device_id": "pi-unit", "label": "采集终端", "online": True,
                "ready": True, "reason": "可以测量", "owner_id": "private-owner",
            }]})
        if request.url.path == "/api/heartlife/measurements":
            if state["measurement_conflict"]:
                return httpx.Response(409, json={"detail": "private database or device details"})
            measurement = {
                "id": "m" * 32, "device_id": "pi-unit", "duration_s": 60,
                "status": "completed", "created_at": fake_clock.now().timestamp(),
                "expires_at": (fake_clock.now() + timedelta(seconds=45)).timestamp(),
                "updated_at": fake_clock.now().timestamp(), "session_id": "serial-001",
                "message": "已上传，等待查看报告", "report": {"model": "not_started", "physiology": "queued"},
                "owner_id": "private-owner",
            }
            if request.method == "POST":
                sent = json.loads(request.content)
                measurement.update(device_id=sent["device_id"], duration_s=sent["duration_s"])
                if state["wrong_measurement"]:
                    measurement["duration_s"] = 300 if sent["duration_s"] == 60 else 60
                return httpx.Response(202, json={**envelope, "measurement": measurement})
            return httpx.Response(200, json={**envelope, "measurements": [measurement]})
        if request.url.path == "/api/heartlife/weekly-summary":
            from datetime import date
            ws = date.fromisoformat(request.url.params["week_start"])
            return httpx.Response(200, json={**envelope,
                "week_start": (ws + timedelta(days=7) if state["wrong_week"] else ws).isoformat(),
                "week_end": (ws + timedelta(days=6)).isoformat(),
                "timezone": request.url.params["timezone"],
                "observed_days": int(request.url.params["observed_days"]),
                "total_records": 0, "total_duration_s": 0.0, "hr_mean": None, "hr_records": 0,
                "daily_series": [{"date": (ws + timedelta(days=n)).isoformat(), "records": 0,
                    "duration_s": 0.0, "hr_mean": None, "hr_records": 0} for n in range(7)],
            })
        return httpx.Response(200, json={
            "ecg_user": {"id": "f" * 32 if state["wrong_owner"] else ECG_ID, "username": "ecg_alice"},
            "expires_at": (fake_clock.now() + timedelta(days=30)).timestamp(),
            "measurement_allowed": state["measurement_allowed"],
            "recent_records": [{"session_id": "serial-001", "started_utc": "2026-11-25T01:00:00Z", "duration_s": 60.0, "hr_mean": None, "secret_note": "not allowed"}],
            "trends": {"period": request.url.params["period"], "anchor": request.url.params["anchor"],
                "utc_offset_minutes": int(request.url.params["utc_offset_minutes"]),
                "buckets": [{"index": 0, "label": "1", "records": 1, "duration_s": 60.0, "hr_mean": None, "hr_records": 0}],
                "total_records": 1, "total_duration_s": 60.0, "note": "合格窗口统计"},
            "grant_token": "never forward unknown response fields",
        })

    app_instance.dependency_overrides[get_ecg_client] = lambda: EcgClient(test_settings, httpx.MockTransport(handle))
    return calls, state


def test_link_requires_login_and_csrf(client, bridge):
    assert client.get("/api/v1/me/ecg/link").status_code == 401
    _, csrf = login(client)
    assert client.post("/api/v1/me/ecg/link", json={"code": CODE}).status_code == 403
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE, "subject_id": "someone"}).status_code == 422
    assert bridge[0] == []


def test_bind_summary_is_scoped_and_never_exports_secrets(client, bridge, db_session):
    uid, csrf = login(client)
    response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    assert response.status_code == 200, response.text
    assert response.json()["linked"] is True
    assert TOKEN not in response.text and CODE not in response.text
    assert json.loads(bridge[0][0].content)["subject_id"] == uid
    saved = db_session.get(EcgLink, uid)
    assert saved.grant_token == TOKEN
    response = client.get("/api/v1/me/ecg/summary?period=month&anchor=2026-11-01")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["recent_records"][0]["hr_mean"] is None
    assert result["recent_records"][0]["report_url"] == "https://ecg.example.test/?record=serial-001"
    assert result["trends"]["utc_offset_minutes"] == 480
    assert "secret_note" not in response.text and "grant_token" not in response.text
    exported = client.get("/api/v1/me/export")
    assert TOKEN not in exported.text and ECG_ID not in exported.text
    assert SECRET not in client.get("/api/v1/public-config").text
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 409


def test_other_heartlife_account_cannot_read_or_revoke_link(app_instance, bridge):
    with TestClient(app_instance) as first, TestClient(app_instance) as second:
        _, csrf = login(first)
        assert first.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 200
        _, other_csrf = login(second, "bob")
        assert second.get("/api/v1/me/ecg/link").json()["linked"] is False
        assert second.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25").status_code == 409
        before = len(bridge[0])
        assert second.delete("/api/v1/me/ecg/link", headers=other_csrf).status_code == 200
        assert len(bridge[0]) == before
        assert first.get("/api/v1/me/ecg/link").json()["linked"] is True


def test_outage_does_not_destroy_life_features_or_leak_upstream(client, bridge):
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    bridge[1]["outage"] = True
    response = client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25")
    assert response.status_code == 503
    assert "private upstream" not in response.text
    assert client.get("/api/v1/me").status_code == 200
    assert client.get("/api/v1/me/weekly-report").status_code == 200


def test_revoke_failure_hides_data_and_can_retry(client, bridge, db_session):
    uid, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    bridge[1]["outage"] = True
    response = client.delete("/api/v1/me/ecg/link", headers=csrf)
    assert response.json() == {"linked": False, "revocation_pending": True}
    assert client.get("/api/v1/me/ecg/link").json()["linked"] is False
    assert client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25").status_code == 409
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 409
    bridge[1]["outage"] = False
    assert client.delete("/api/v1/me/ecg/link", headers=csrf).json()["revocation_pending"] is False
    assert db_session.get(EcgLink, uid) is None


def test_response_loss_requires_safe_cleanup_before_retry(client, bridge, fake_clock):
    _, csrf = login(client)
    bridge[1]["outage"] = True
    response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    assert response.status_code == 503
    assert client.get("/api/v1/me/ecg/link").json()["revocation_pending"] is True
    bridge[1]["outage"] = False
    assert client.delete("/api/v1/me/ecg/link", headers=csrf).json()["revocation_pending"] is True
    fake_clock.advance(seconds=311)
    assert client.delete("/api/v1/me/ecg/link", headers=csrf).json()["revocation_pending"] is False
    assert bridge[0][-1].url.path == "/api/heartlife/subject-grant"


def test_owner_mismatch_and_expiry_fail_closed(client, bridge, fake_clock):
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    bridge[1]["wrong_owner"] = True
    assert client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25").status_code == 502
    bridge[1]["wrong_owner"] = False
    bridge[1]["invalid_grant"] = True
    response = client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ECG_LINK_EXPIRED"
    assert client.get("/api/v1/me").status_code == 200


def test_deletion_checks_password_before_revoke_and_retries_failure(client, bridge, db_session):
    uid, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    initial = len(bridge[0])
    payload = {"password": "wrong", "confirm_text": "DELETE"}
    assert client.post("/api/v1/me/delete", headers=csrf, json=payload).status_code == 401
    assert len(bridge[0]) == initial
    payload["password"] = "ExamplePass123!"
    bridge[1]["outage"] = True
    assert client.post("/api/v1/me/delete", headers=csrf, json=payload).status_code == 503
    assert db_session.get(User, uid).status == "active"
    bridge[1]["outage"] = False
    assert client.post("/api/v1/me/delete", headers=csrf, json=payload).status_code == 200
    db_session.expire_all()
    assert db_session.get(User, uid).status == "deleted"
    assert db_session.get(EcgLink, uid) is None


def test_default_disabled_and_bad_configuration(client):
    _, csrf = login(client)
    assert client.get("/api/v1/me/ecg/link").json()["enabled"] is False
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 503
    for base in ("http://example.com", "https://x.test/api", "https://u:p@x.test", "https://x.test?x=1", "https://x.test\\@evil.test"):
        with pytest.raises(ValueError):
            Settings(ecg_api_base_url=base)
    for base in ("http://127.0.0.1:8766", "http://[::1]:8766", "https://ecg.example.test"):
        assert Settings(ecg_api_base_url=base).ecg_api_base_url == base
    assert Settings(ecg_external_url="https://ecg.example.test", ecg_api_base_url="http://127.0.0.1:8766", ecg_client_secret="short").is_ecg_integration_enabled is False


def test_missing_grant_expiration_does_not_reach_upstream(client, bridge, fake_clock):
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    fake_clock.advance(days=31)
    # Refresh local login after its separate session expiry.
    response = client.post("/api/v1/auth/login", json={"account": "alice", "password": "ExamplePass123!"})
    assert response.status_code == 200
    count = len(bridge[0])
    assert client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25").status_code == 409
    assert len(bridge[0]) == count


def test_summary_in_flight_is_discarded_after_unlink(client, bridge, app_instance, test_settings):
    uid, csrf = login(client)
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 200
    make_client = app_instance.dependency_overrides[get_ecg_client]
    upstream = make_client()
    original = upstream.summary

    def revoke_during_request(*args, **kwargs):
        result = original(*args, **kwargs)
        with app_instance.state.session_factory() as db:
            row = db.get(EcgLink, uid)
            row.state = "revocation_pending"
            db.commit()
        return result

    upstream.summary = revoke_during_request
    app_instance.dependency_overrides[get_ecg_client] = lambda: upstream
    response = client.get("/api/v1/me/ecg/summary?period=day&anchor=2026-11-25")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ECG_LINK_CHANGED"
    assert "serial-001" not in response.text


def test_delete_cannot_race_a_new_binding(client, bridge, app_instance, monkeypatch):
    from app.privacy import router as privacy_router

    uid, csrf = login(client)
    original_unlink = privacy_router.unlink

    def insert_new_binding(*args, **kwargs):
        result = original_unlink(*args, **kwargs)
        with app_instance.state.session_factory() as db:
            db.add(EcgLink(user_id=uid, operation_id="a" * 32, state="binding", cleanup_after=1))
            db.commit()
        return result

    monkeypatch.setattr(privacy_router, "unlink", insert_new_binding)
    response = client.post("/api/v1/me/delete", headers=csrf,
                           json={"password": "ExamplePass123!", "confirm_text": "DELETE"})
    assert response.status_code == 409
    with app_instance.state.session_factory() as db:
        assert db.get(User, uid).status == "active"
        assert db.get(EcgLink, uid) is not None


def test_invalid_codes_rate_limited_without_leaking_remote_error(client, bridge, app_instance, test_settings):
    _, csrf = login(client)
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(401, json={"detail": "sensitive upstream details"})

    app_instance.dependency_overrides[get_ecg_client] = lambda: EcgClient(test_settings, httpx.MockTransport(reject))
    for _ in range(5):
        response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
        assert response.status_code == 422
        assert "sensitive upstream" not in response.text
    assert client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE}).status_code == 429
    assert len(calls) == 5


def test_http_redirect_never_follows_credentials(test_settings):
    test_settings.ecg_api_base_url = "https://ecg.example.test"
    test_settings.ecg_external_url = "https://ecg.example.test"
    test_settings.ecg_client_secret = SECRET
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://another.example.test"})

    from app.core.errors import AppError
    with pytest.raises(AppError) as error:
        EcgClient(test_settings, httpx.MockTransport(redirect)).exchange(CODE, "a" * 32, "b" * 32)
    assert error.value.code == "ECG_UNAVAILABLE"
    assert len(calls) == 1 and calls[0].url.host == "ecg.example.test"


def test_upgrade_existing_database_preserves_users_and_adds_link_table(tmp_path):
    from alembic import command
    from alembic.config import Config
    from app.db.database import build_session_factory
    from app.db.migrations_runner import BACKEND_DIR, run_migrations

    db_url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    run_migrations(db_url)
    engine, factory = build_session_factory(db_url)
    with factory() as db:
        db.add(User(id="a" * 32, account="existing", password_hash="unused", nickname="保留用户"))
        db.commit()
    # Simulate the old deployed revision, which did not include the new table.
    with engine.begin() as connection:
        EcgLink.__table__.drop(bind=connection)
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='0001_initial_schema'")
    engine.dispose()
    run_migrations(db_url)
    engine, factory = build_session_factory(db_url)
    with factory() as db:
        assert db.get(User, "a" * 32).nickname == "保留用户"
        assert db.scalars(select(EcgLink)).all() == []
    engine.dispose()


def test_readonly_bindings_cannot_get_control_permissions_from_request(client, bridge):
    _, csrf = login(client)
    response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE, "measurement_allowed": True})
    assert response.status_code == 422
    response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    assert response.json()["measurement_allowed"] is False
    count = len(bridge[0])
    assert client.get("/api/v1/me/ecg/devices").status_code == 403
    assert client.get("/api/v1/me/ecg/measurements").status_code == 403
    assert client.post("/api/v1/me/ecg/measurements", headers=csrf, json={
        "device_id": "pi-unit", "duration_s": 60, "request_key": "a" * 32,
    }).status_code == 403
    assert len(bridge[0]) == count
    # Old grants still support independent, private weekly summaries.
    assert client.get("/api/v1/me/ecg/weekly-summary").status_code == 200


def test_measurement_devices_create_poll_and_exact_retry_key(client, bridge, db_session):
    bridge[1]["measurement_allowed"] = True
    uid, csrf = login(client)
    response = client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    assert response.json()["measurement_allowed"] is True
    assert db_session.get(EcgLink, uid).measurement_allowed is True
    response = client.get("/api/v1/me/ecg/devices")
    assert response.status_code == 200
    assert response.json()["devices"][0]["ready"] is True
    assert "owner_id" not in response.text
    payload = {"device_id": "pi-unit", "duration_s": 180, "request_key": "a" * 32}
    assert client.post("/api/v1/me/ecg/measurements", json=payload).status_code == 403
    for _ in range(2):
        response = client.post("/api/v1/me/ecg/measurements", headers=csrf, json=payload)
        assert response.status_code == 202, response.text
        assert response.json()["measurement"]["duration_s"] == 180
        assert json.loads(bridge[0][-1].content) == payload
    response = client.get("/api/v1/me/ecg/measurements")
    assert response.status_code == 200
    item = response.json()["measurements"][0]
    assert item["status"] == "completed"
    assert item["report"] == {"model": "not_started", "physiology": "queued"}
    assert item["report_url"] == "https://ecg.example.test/?record=serial-001"
    assert "owner_id" not in response.text and TOKEN not in response.text


def test_measurement_validation_errors_and_mismatch_are_safe(client, bridge):
    bridge[1]["measurement_allowed"] = True
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    payload = {"device_id": "pi-unit", "duration_s": 60, "request_key": "a" * 32}
    count = len(bridge[0])
    for invalid in ({**payload, "duration_s": 120}, {**payload, "request_key": "short"},
                    {**payload, "owner_id": "another"}):
        assert client.post("/api/v1/me/ecg/measurements", headers=csrf, json=invalid).status_code == 422
    assert len(bridge[0]) == count
    bridge[1]["measurement_conflict"] = True
    response = client.post("/api/v1/me/ecg/measurements", headers=csrf, json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ECG_MEASUREMENT_CONFLICT"
    assert "private database" not in response.text
    bridge[1]["measurement_conflict"] = False
    bridge[1]["wrong_measurement"] = True
    assert client.post("/api/v1/me/ecg/measurements", headers=csrf, json=payload).status_code == 502
    bridge[1]["wrong_measurement"] = False
    bridge[1]["wrong_owner"] = True
    assert client.get("/api/v1/me/ecg/devices").status_code == 502


def test_weekly_summary_uses_account_timezone_and_validates_returned_week(client, bridge, fake_clock):
    from datetime import datetime, timezone
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    client.patch("/api/v1/me", headers=csrf, json={"timezone": "America/New_York"})
    # UTC Monday is still Sunday in New York: the local report remains the previous week.
    fake_clock.set(datetime(2026, 11, 30, 2, 0, tzinfo=timezone.utc))
    response = client.get("/api/v1/me/ecg/weekly-summary")
    assert response.status_code == 200, response.text
    assert response.json()["week_start"] == "2026-11-23"
    assert response.json()["observed_days"] == 7
    assert response.json()["hr_mean"] is None
    assert bridge[0][-1].url.params["timezone"] == "America/New_York"
    assert "utc_offset_minutes" not in bridge[0][-1].url.params
    assert len(response.json()["daily_series"]) == 7
    assert client.get("/api/v1/me/ecg/weekly-summary?week_start=2026-11-24").status_code == 422
    assert client.get("/api/v1/me/ecg/weekly-summary?week_start=2026-11-30").status_code == 422
    assert client.get("/api/v1/me/ecg/weekly-summary?timezone=Asia/Shanghai").status_code == 422
    bridge[1]["wrong_week"] = True
    assert client.get("/api/v1/me/ecg/weekly-summary").status_code == 502


def test_control_response_after_revoke_is_discarded(client, bridge, app_instance):
    bridge[1]["measurement_allowed"] = True
    uid, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    upstream = app_instance.dependency_overrides[get_ecg_client]()
    original = upstream.devices

    def revoke_during_request(*args, **kwargs):
        result = original(*args, **kwargs)
        with app_instance.state.session_factory() as db:
            db.get(EcgLink, uid).state = "revocation_pending"
            db.commit()
        return result

    upstream.devices = revoke_during_request
    app_instance.dependency_overrides[get_ecg_client] = lambda: upstream
    response = client.get("/api/v1/me/ecg/devices")
    assert response.status_code == 409
    assert "pi-unit" not in response.text


def test_weekly_outage_does_not_change_life_report_or_export(client, bridge):
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    bridge[1]["outage"] = True
    assert client.get("/api/v1/me/ecg/weekly-summary").status_code == 503
    assert client.get("/api/v1/me/weekly-report").status_code == 200
    exported = client.get("/api/v1/me/export")
    assert exported.status_code == 200
    assert "ecg_user" not in exported.text and TOKEN not in exported.text


def test_denied_device_permission_does_not_revoke_readonly_data(client, bridge):
    bridge[1]["measurement_allowed"] = True
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    bridge[1]["control_forbidden"] = True
    response = client.get("/api/v1/me/ecg/devices")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ECG_MEASUREMENT_FORBIDDEN"
    assert "private upstream" not in response.text
    link = client.get("/api/v1/me/ecg/link").json()
    assert link["linked"] is True and link["revocation_pending"] is False
    assert client.get("/api/v1/me/ecg/weekly-summary").status_code == 200


def test_existing_link_migration_does_not_upgrade_measurement_permission(tmp_path):
    from app.db.database import build_session_factory
    from app.db.migrations_runner import run_migrations

    db_url = f"sqlite:///{(tmp_path / 'old-link.db').as_posix()}"
    run_migrations(db_url)
    engine, factory = build_session_factory(db_url)
    with factory() as db:
        db.add(User(id="a" * 32, account="existing", password_hash="unused", nickname="保留用户"))
        db.flush()
        db.add(EcgLink(user_id="a" * 32, operation_id="b" * 32, state="active",
                       grant_token=TOKEN, ecg_user_id=ECG_ID, measurement_allowed=True))
        db.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE ecg_links DROP COLUMN measurement_allowed")
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='0002_ecg_links'")
    engine.dispose()
    run_migrations(db_url)
    engine, factory = build_session_factory(db_url)
    with factory() as db:
        row = db.get(EcgLink, "a" * 32)
        assert row.grant_token == TOKEN and row.operation_id == "b" * 32
        assert row.state == "active" and row.measurement_allowed is False
        assert db.get(User, "a" * 32).nickname == "保留用户"
    engine.dispose()


def test_weekly_and_measurement_routes_reject_browser_scoping_parameters(client, bridge):
    bridge[1]["measurement_allowed"] = True
    _, csrf = login(client)
    client.post("/api/v1/me/ecg/link", headers=csrf, json={"code": CODE})
    count = len(bridge[0])
    for path in ("devices?owner_id=another", "measurements?subject_id=another",
                 "weekly-summary?observed_days=7", "weekly-summary?week_start=2026-11-23&week_start=2026-11-16"):
        assert client.get("/api/v1/me/ecg/" + path).status_code == 422
    assert len(bridge[0]) == count
