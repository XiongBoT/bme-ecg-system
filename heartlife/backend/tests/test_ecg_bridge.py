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
    state = {"outage": False, "wrong_owner": False, "invalid_grant": False}

    def handle(request):
        calls.append(request)
        assert request.headers["X-HeartLife-Key"] == SECRET
        if state["outage"]:
            raise httpx.ConnectError("private upstream details must not be exposed", request=request)
        if request.url.path == "/api/heartlife/exchange":
            assert json.loads(request.content)["code"] == CODE
            return httpx.Response(200, json={"grant_token": TOKEN, "ecg_user_id": ECG_ID,
                "ecg_username": "ecg_alice", "expires_at": (fake_clock.now() + timedelta(days=30)).timestamp()})
        assert request.headers["X-HeartLife-Subject"]
        if request.method == "DELETE":
            return httpx.Response(200, json={"revoked": True})
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        if state["invalid_grant"]:
            return httpx.Response(401, json={"detail": "invalid"})
        return httpx.Response(200, json={
            "ecg_user": {"id": "f" * 32 if state["wrong_owner"] else ECG_ID, "username": "ecg_alice"},
            "expires_at": (fake_clock.now() + timedelta(days=30)).timestamp(),
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
