"""Exercise the real HeartLife and ECG HTTP contracts without network sockets.

Only this test imports the legacy application. Production HeartLife consumes
its HTTP API and never opens the ECG database or imports ECG modules.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sqlite3
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.clock import FakeClock
from app.core.config import Settings
from app.ecg.client import EcgClient, get_ecg_client
from app.main import create_app as create_heartlife_app


SECRET = "synthetic-contract-test-client-secret-only"


class CloudTransport:
    """Forward to a real ASGI client; optionally lose a committed response."""

    def __init__(self, client: TestClient):
        self.client = client
        self.available = True
        self.lose_next_exchange = False
        self.lose_next_measurement = False
        self.before_send = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.available:
            raise httpx.ConnectError("synthetic offline service", request=request)
        if self.before_send is not None:
            self.before_send(request)
        response = self.client.request(
            request.method,
            str(request.url),
            content=request.content,
            headers=dict(request.headers),
        )
        if self.lose_next_exchange and request.url.path == "/api/heartlife/exchange":
            self.lose_next_exchange = False
            assert response.status_code == 200, response.text
            raise httpx.ReadTimeout("synthetic lost exchange response", request=request)
        if (self.lose_next_measurement and request.method == "POST"
                and request.url.path == "/api/heartlife/measurements"):
            self.lose_next_measurement = False
            assert response.status_code == 202, response.text
            raise httpx.ReadTimeout("synthetic lost measurement response", request=request)
        return httpx.Response(response.status_code, content=response.content,
                              headers={"Content-Type": "application/json"})


class Contract:
    def __init__(self, cloud, owner, other, heartlife, outsider, transport, clock, db_file):
        self.cloud = cloud
        self.owner = owner
        self.other = other
        self.heartlife = heartlife
        self.outsider = outsider
        self.transport = transport
        self.clock = clock
        self.db_file = db_file

    def code(self, measurement_allowed=None) -> str:
        kwargs = {} if measurement_allowed is None else {"json": {"measurement_allowed": measurement_allowed}}
        response = self.owner.post("/api/heartlife/link-code", **kwargs)
        assert response.status_code == 200, response.text
        return response.json()["code"]

    def bind(self, measurement_allowed=None):
        response = self.heartlife.post("/api/v1/me/ecg/link", json={"code": self.code(measurement_allowed)})
        assert response.status_code == 200, response.text
        assert response.json()["linked"] is True
        return response

    def summary(self, client=None, period="day", anchor="2026-11-25"):
        return (client or self.heartlife).get("/api/v1/me/ecg/summary", params={
            "period": period, "anchor": anchor,
        })

    def device_credentials(self, device_id="pi-contract", owner_id=None):
        owner_id = owner_id or self.owner.get("/api/auth/me").json()["user"]["id"]
        return self.cloud.app.state.devices.create(device_id, device_id, [owner_id])["credentials"]

    def record(self, session_id, stamp, *, owner_id=None, source="serial", complete=1,
               heart_rate=None, weight=360, device_id="pi-contract"):
        owner_id = owner_id or self.owner.get("/api/auth/me").json()["user"]["id"]
        with closing(sqlite3.connect(self.db_file)) as db, db:
            db.execute(
                "INSERT INTO sessions(id,metadata,created_at,sample_count,complete,owner_id,ingest_device_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (session_id, json.dumps({"source": source, "started_utc": stamp}),
                 stamp, 21600, complete, owner_id, device_id),
            )
            if heart_rate is not None:
                db.execute("INSERT INTO measurement_summaries VALUES(?,?)", (
                    session_id, json.dumps({"analysis_stats": {"hr": {
                        "mean": heart_rate, "window_samples": weight,
                    }}}),
                ))

    def seed_records(self):
        """All data are synthetic. Include non-visible records as leak sentinels."""
        owner_id = self.owner.get("/api/auth/me").json()["user"]["id"]
        other_id = self.other.get("/api/auth/me").json()["user"]["id"]
        with closing(sqlite3.connect(self.db_file)) as db, db:
            for sid, owner, source, complete in (
                ("own_heart_rate", owner_id, "serial", 1),
                ("own_missing_heart_rate", owner_id, "serial", 1),
                ("other_private_record", other_id, "serial", 1),
                ("own_synthetic_record", owner_id, "synthetic", 1),
                ("own_incomplete_record", owner_id, "serial", 0),
                ("own_recycled_record", owner_id, "serial", 1),
            ):
                db.execute(
                    "INSERT INTO sessions(id,metadata,created_at,sample_count,complete,owner_id,ingest_device_id) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (sid, json.dumps({"source": source, "started_utc": "2026-11-24T16:30:00Z"}),
                     "2026-11-24T16:31:00Z", 21600, complete, owner, "pi2-demo"),
                )
            db.execute("INSERT INTO session_details VALUES(?,?,?,?)",
                       ("own_recycled_record", "recycled private name", "private note", "2026-11-25T00:00:00Z"))
            db.execute("INSERT INTO session_details VALUES(?,?,?,?)",
                       ("own_heart_rate", "private name must stay private", "private note", None))
            db.execute("INSERT INTO measurement_summaries VALUES(?,?)", (
                "own_heart_rate", json.dumps({
                    "analysis_stats": {"hr": {"mean": 72.0, "window_samples": 360}},
                    "unrelated_private_field": "must not cross the API",
                }),
            ))


@pytest.fixture()
def contract(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    cloud_dir = root / "心电云端平台"
    monkeypatch.syspath_prepend(str(cloud_dir))
    # The ECG module can be imported only after its test data path is selected.
    monkeypatch.setenv("ECG_DATA_DIR", str(tmp_path / "import-cloud"))
    monkeypatch.setenv("ECG_HEARTLIFE_URL", "https://health.example.test")
    monkeypatch.setenv("ECG_HEARTLIFE_CLIENT_SECRET", SECRET)
    monkeypatch.delenv("ECG_PUBLIC_ACCESS", raising=False)
    monkeypatch.setenv("ECG_DEPLOYMENT", "local")
    monkeypatch.setenv("ECG_MODEL", "")
    cloud_module = importlib.import_module("server")
    assert Path(cloud_module.__file__).resolve() == cloud_dir / "server.py"
    cloud_dir_data = tmp_path / "ecg-data"
    cloud_app = cloud_module.create_app(cloud_dir_data, auth_enabled=True, cookie_secure=False)
    cloud_app.state.auth.create_user("contract_alice", "contract-pass")
    cloud_app.state.auth.create_user("contract_bob", "contract-pass")
    clock = FakeClock(datetime.now(timezone.utc))
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'heartlife.db').as_posix()}",
        app_env="test", demo_mode=False, cookie_secure=False, cookie_path="/",
        ecg_api_base_url="http://127.0.0.1:8766",
        ecg_external_url="https://ecg.example.test",
        ecg_client_secret=SECRET,
    )
    hl_app = create_heartlife_app(settings=settings, clock=clock)
    with ExitStack() as stack:
        # Each ASGI app enters its lifespan once; other clients have isolated cookies.
        machine = stack.enter_context(TestClient(cloud_app))
        owner = TestClient(cloud_app)
        other = TestClient(cloud_app)
        stack.callback(owner.close)
        stack.callback(other.close)
        for client, username in ((owner, "contract_alice"), (other, "contract_bob")):
            response = client.post("/api/auth/login", json={"username": username, "password": "contract-pass"})
            assert response.status_code == 200, response.text
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        transport = CloudTransport(machine)
        hl_app.dependency_overrides[get_ecg_client] = lambda: EcgClient(settings, httpx.MockTransport(transport))
        hl = stack.enter_context(TestClient(hl_app))
        outsider = TestClient(hl_app)
        stack.callback(outsider.close)
        for client, account in ((hl, "heartlife_alice"), (outsider, "heartlife_bob")):
            response = client.post("/api/v1/auth/register", json={
                "account": account, "password": "ContractPass123!", "nickname": account,
                "timezone": "Asia/Shanghai",
            })
            assert response.status_code == 201, response.text
            response = client.post("/api/v1/auth/login", json={"account": account, "password": "ContractPass123!"})
            assert response.status_code == 200, response.text
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield Contract(machine, owner, other, hl, outsider, transport, clock, cloud_dir_data / "cloud.sqlite")


def test_bind_read_only_records_and_trends_then_ecg_revoke(contract):
    contract.seed_records()
    bound = contract.bind()
    assert "grant_token" not in bound.text
    assert SECRET not in bound.text
    response = contract.summary()
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    records = {row["session_id"]: row for row in data["recent_records"]}
    assert set(records) == {"own_heart_rate", "own_missing_heart_rate"}
    assert records["own_heart_rate"]["hr_mean"] == 72
    assert records["own_missing_heart_rate"]["hr_mean"] is None
    assert records["own_heart_rate"]["report_url"] == "https://ecg.example.test/?record=own_heart_rate"
    assert data["trends"]["total_records"] == 2
    assert data["trends"]["total_duration_s"] == 120
    assert data["trends"]["buckets"][0]["hr_mean"] == 72
    for sentinel in ("other_private_record", "own_synthetic_record", "own_incomplete_record",
                     "own_recycled_record", "private note", "private name", "unrelated_private_field",
                     "grant_token", SECRET):
        assert sentinel not in response.text
    for period in ("day", "month", "year"):
        summary = contract.summary(period=period)
        baseline = contract.owner.get("/api/records/trends", params={
            "period": period, "anchor": "2026-11-25", "utc_offset_minutes": 480,
        })
        assert summary.status_code == baseline.status_code == 200
        assert summary.json()["trends"] == baseline.json()
    assert contract.summary(contract.outsider).status_code == 409
    assert contract.owner.delete("/api/heartlife/link").status_code == 200
    revoked = contract.summary()
    assert revoked.status_code == 409
    assert revoked.json()["error"]["code"] == "ECG_LINK_EXPIRED"
    status = contract.heartlife.get("/api/v1/me/ecg/link").json()
    assert status["linked"] is False
    assert status["revocation_pending"] is True
    # Revoked integration does not end the independent HeartLife session.
    assert contract.heartlife.get("/api/v1/me").status_code == 200


def test_heartlife_unlink_revokes_and_allows_new_binding(contract):
    contract.bind()
    response = contract.heartlife.delete("/api/v1/me/ecg/link")
    assert response.status_code == 200, response.text
    assert response.json() == {"linked": False, "revocation_pending": False}
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is False
    assert contract.summary().status_code == 409
    contract.bind()
    assert contract.summary().status_code == 200


def test_unlink_outage_hides_data_and_can_be_retried(contract):
    contract.bind()
    contract.transport.available = False
    response = contract.heartlife.delete("/api/v1/me/ecg/link")
    assert response.status_code == 200
    assert response.json() == {"linked": False, "revocation_pending": True}
    assert contract.summary().status_code == 409
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is True
    assert contract.heartlife.get("/api/v1/me/dashboard").status_code == 200
    contract.transport.available = True
    response = contract.heartlife.delete("/api/v1/me/ecg/link")
    assert response.json() == {"linked": False, "revocation_pending": False}
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is False


def test_lost_exchange_response_recovers_actual_remote_grant(contract):
    code = contract.code()
    contract.transport.lose_next_exchange = True
    response = contract.heartlife.post("/api/v1/me/ecg/link", json={"code": code})
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "ECG_UNAVAILABLE"
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is True
    assert contract.summary().status_code == 409
    # A pending in-flight exchange must not race with successful cleanup/rebinding.
    response = contract.heartlife.delete("/api/v1/me/ecg/link")
    assert response.json() == {"linked": False, "revocation_pending": True}
    contract.clock.advance(seconds=311)
    response = contract.heartlife.delete("/api/v1/me/ecg/link")
    assert response.json() == {"linked": False, "revocation_pending": False}
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is False
    contract.bind()
    assert contract.summary().status_code == 200


def test_late_unlink_cannot_revoke_replacement_binding(contract):
    """Two unlink requests must not let the slower one delete a later grant."""
    contract.bind()
    blocked = threading.Event()
    release = threading.Event()
    hook_lock = threading.Lock()

    def pause_first_revoke(request):
        if request.method != "DELETE" or request.url.path != "/api/heartlife/grant":
            return
        with hook_lock:
            first = not blocked.is_set()
            if first:
                blocked.set()
        if first:
            assert release.wait(timeout=10), "timed out waiting for replacement binding"

    contract.transport.before_send = pause_first_revoke
    with ThreadPoolExecutor(max_workers=1) as pool:
        late = pool.submit(contract.heartlife.delete, "/api/v1/me/ecg/link")
        try:
            assert blocked.wait(timeout=10), "the first unlink did not reach the remote API"
            fast = contract.heartlife.delete("/api/v1/me/ecg/link")
            assert fast.status_code == 200, fast.text
            assert fast.json()["revocation_pending"] is False
            contract.bind()
        finally:
            release.set()
        assert late.result(timeout=10).status_code == 200
    assert contract.owner.get("/api/heartlife/link").json()["linked"] is True
    assert contract.heartlife.get("/api/v1/me/ecg/link").json()["linked"] is True
    assert contract.summary().status_code == 200


def test_readonly_binding_cannot_request_measurement_permission(contract):
    """The user consents on ECG; neither the HeartLife form nor requests can elevate it."""
    code = contract.code()
    forged = contract.heartlife.post("/api/v1/me/ecg/link", json={
        "code": code, "measurement_allowed": True,
    })
    assert forged.status_code == 422
    bound = contract.heartlife.post("/api/v1/me/ecg/link", json={"code": code})
    assert bound.status_code == 200, bound.text
    assert bound.json()["measurement_allowed"] is False
    assert contract.owner.get("/api/heartlife/link").json()["measurement_allowed"] is False
    for path in ("devices", "measurements"):
        assert contract.heartlife.get("/api/v1/me/ecg/" + path).status_code == 403
    result = contract.heartlife.post("/api/v1/me/ecg/measurements", json={
        "device_id": "pi-contract", "duration_s": 60, "request_key": "a" * 32,
    })
    assert result.status_code == 403
    with closing(sqlite3.connect(contract.db_file)) as db:
        assert db.execute("SELECT COUNT(*) FROM measurement_requests").fetchone()[0] == 0
    # The added private summary does not require remote-control permission.
    assert contract.heartlife.get("/api/v1/me/ecg/weekly-summary").status_code == 200
    assert contract.heartlife.delete("/api/v1/me/ecg/link").status_code == 200
    upgraded = contract.bind(measurement_allowed=True)
    assert upgraded.json()["measurement_allowed"] is True
    assert contract.heartlife.get("/api/v1/me/ecg/devices").status_code == 200


def test_measurement_lost_response_retry_upload_and_revocation(contract):
    credentials = contract.device_credentials()
    bound = contract.bind(measurement_allowed=True)
    assert bound.json()["measurement_allowed"] is True
    with closing(TestClient(contract.cloud.app)) as device:
        device.headers["X-API-Key"] = credentials["token"]
        heartbeat = device.put("/api/device/heartbeat", json={"state": "standby", "remote_ready": True})
        assert heartbeat.status_code == 200, heartbeat.text
        listed = contract.heartlife.get("/api/v1/me/ecg/devices")
        assert listed.status_code == 200, listed.text
        own = next(item for item in listed.json()["devices"] if item["device_id"] == "pi-contract")
        assert own["online"] is True and own["ready"] is True
        request = {"device_id": "pi-contract", "duration_s": 180, "request_key": "a" * 32}
        contract.transport.lose_next_measurement = True
        lost = contract.heartlife.post("/api/v1/me/ecg/measurements", json=request)
        assert lost.status_code == 503, lost.text
        assert lost.json()["error"]["code"] == "ECG_UNAVAILABLE"
        retry = contract.heartlife.post("/api/v1/me/ecg/measurements", json=request)
        assert retry.status_code == 202, retry.text
        task = retry.json()["measurement"]
        assert task["status"] == "queued"
        assert task["report"] == {"model": "not_started", "physiology": "not_started"}
        repeated = contract.heartlife.post("/api/v1/me/ecg/measurements", json=request)
        assert repeated.json()["measurement"]["id"] == task["id"]
        conflict = contract.heartlife.post("/api/v1/me/ecg/measurements", json={**request, "duration_s": 60})
        assert conflict.status_code == 409
        with closing(sqlite3.connect(contract.db_file)) as db:
            assert db.execute("SELECT COUNT(*) FROM measurement_requests").fetchone()[0] == 1
        assert contract.other.get("/api/measurements").json()["measurements"] == []
        assert contract.outsider.get("/api/v1/me/ecg/measurements").status_code == 409
        pending = device.get("/api/device/measurements/next").json()["measurement"]
        assert pending["id"] == task["id"]
        base = "/api/device/measurements/" + task["id"]
        assert device.post(base + "/claim").status_code == 200
        recording = device.post(base + "/status", json={
            "status": "recording", "session_id": "contract_uploaded",
        })
        assert recording.status_code == 200, recording.text
        contract.record("contract_uploaded", "2026-11-25T01:00:00Z")
        response = contract.heartlife.get("/api/v1/me/ecg/measurements")
        assert response.status_code == 200, response.text
        item = response.json()["measurements"][0]
        assert item["status"] == "completed"
        assert item["report"] == {"model": "not_started", "physiology": "not_started"}
        assert item["report_url"] == "https://ecg.example.test/?record=contract_uploaded"
        assert "owner_id" not in response.text and "grant_token" not in response.text
        assert credentials["token"] not in response.text and SECRET not in response.text
        with closing(sqlite3.connect(contract.db_file)) as db:
            assert db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0] == 0
        # Existing acquisition and its record remain; revocation only prevents future bridge access.
        assert contract.owner.delete("/api/heartlife/link").status_code == 200
        blocked = contract.heartlife.post("/api/v1/me/ecg/measurements", json={
            **request, "request_key": "b" * 32,
        })
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "ECG_LINK_EXPIRED"
        assert contract.owner.get("/api/measurements").json()["measurements"][0]["id"] == task["id"]


def test_admin_binding_still_limits_devices_and_rechecks_recipient_at_write(contract):
    owner_id = contract.owner.get("/api/auth/me").json()["user"]["id"]
    other_id = contract.other.get("/api/auth/me").json()["user"]["id"]
    credentials = contract.device_credentials()
    contract.device_credentials("pi-other-private", owner_id=other_id)
    with closing(sqlite3.connect(contract.db_file)) as db, db:
        db.execute("UPDATE users SET is_admin=1 WHERE id=?", (owner_id,))
    contract.bind(measurement_allowed=True)
    with closing(TestClient(contract.cloud.app)) as device:
        device.headers["X-API-Key"] = credentials["token"]
        device.put("/api/device/heartbeat", json={"state": "standby", "remote_ready": True})
        response = contract.heartlife.get("/api/v1/me/ecg/devices")
        assert response.status_code == 200, response.text
        rows = response.json()["devices"]
        assert "pi-contract" in {item["device_id"] for item in rows}
        assert "pi-other-private" not in response.text
        assert all(set(item) == {"device_id", "label", "online", "ready", "reason"} for item in rows)

        def revoke_device_before_write(request):
            if request.method == "POST" and request.url.path == "/api/heartlife/measurements":
                contract.cloud.app.state.devices.update("pi-contract", user_ids=[])

        contract.transport.before_send = revoke_device_before_write
        blocked = contract.heartlife.post("/api/v1/me/ecg/measurements", json={
            "device_id": "pi-contract", "duration_s": 60, "request_key": "a" * 32,
        })
        assert blocked.status_code == 403, blocked.text
        with closing(sqlite3.connect(contract.db_file)) as db:
            assert db.execute("SELECT COUNT(*) FROM measurement_requests").fetchone()[0] == 0
        assert contract.heartlife.get("/api/v1/me").status_code == 200


def test_grant_revoked_after_heartlife_check_cannot_start_acquisition(contract):
    credentials = contract.device_credentials()
    contract.bind(measurement_allowed=True)
    with closing(TestClient(contract.cloud.app)) as device:
        device.headers["X-API-Key"] = credentials["token"]
        device.put("/api/device/heartbeat", json={"state": "standby", "remote_ready": True})

        def revoke_before_forward(request):
            if request.method == "POST" and request.url.path == "/api/heartlife/measurements":
                assert contract.owner.delete("/api/heartlife/link").status_code == 200

        contract.transport.before_send = revoke_before_forward
        response = contract.heartlife.post("/api/v1/me/ecg/measurements", json={
            "device_id": "pi-contract", "duration_s": 60, "request_key": "a" * 32,
        })
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ECG_LINK_EXPIRED"
        with closing(sqlite3.connect(contract.db_file)) as db:
            assert db.execute("SELECT COUNT(*) FROM measurement_requests").fetchone()[0] == 0
        assert device.get("/api/device/measurements/next").json()["measurement"] is None


def test_weekly_summary_is_private_weighted_and_independent_of_life_report(contract):
    contract.seed_records()
    contract.record("weighted_monday", "2026-11-23T01:00:00Z", heart_rate=90, weight=720)
    contract.record("after_observed_days", "2026-11-26T01:00:00Z", heart_rate=200)
    contract.bind()
    contract.clock.set(datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc))
    before = contract.heartlife.get("/api/v1/me/weekly-report").json()
    response = contract.heartlife.get("/api/v1/me/ecg/weekly-summary")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["week_start"] == "2026-11-23" and data["week_end"] == "2026-11-29"
    assert data["timezone"] == "Asia/Shanghai" and data["observed_days"] == 3
    assert data["total_records"] == 3 and data["total_duration_s"] == 180
    assert data["hr_mean"] == 84 and data["hr_records"] == 2
    assert len(data["daily_series"]) == 7
    assert data["daily_series"][0]["hr_mean"] == 90
    assert data["daily_series"][1]["hr_mean"] is None
    assert data["daily_series"][2]["records"] == 2
    assert data["daily_series"][3]["records"] == 0
    for sentinel in ("other_private_record", "own_synthetic_record", "own_incomplete_record",
                     "own_recycled_record", "private note", "private name", "grant_token", SECRET):
        assert sentinel not in response.text
    assert contract.outsider.get("/api/v1/me/ecg/weekly-summary").status_code == 409
    assert contract.heartlife.get("/api/v1/me/weekly-report").json() == before
    exported = contract.heartlife.get("/api/v1/me/export")
    assert exported.status_code == 200
    assert "ecg_user" not in exported.text and "weighted_monday" not in exported.text
    contract.transport.available = False
    assert contract.heartlife.get("/api/v1/me/ecg/weekly-summary").status_code == 503
    assert contract.heartlife.get("/api/v1/me/weekly-report").json() == before
    assert contract.heartlife.get("/api/v1/me/dashboard").status_code == 200


def test_weekly_summary_uses_actual_dst_midnights_end_to_end(contract):
    contract.bind()
    changed = contract.heartlife.patch("/api/v1/me", json={"timezone": "America/New_York"})
    assert changed.status_code == 200, changed.text
    # 2026-11-01 has 25 local hours; use the next local Monday as an exclusive upper bound.
    for session_id, stamp in (
        ("outside_before", "2026-10-26T03:59:59Z"),
        ("monday_start", "2026-10-26T04:00:00Z"),
        ("sunday_first_0130", "2026-11-01T05:30:00Z"),
        ("sunday_second_0130", "2026-11-01T06:30:00Z"),
        ("sunday_end", "2026-11-02T04:59:59Z"),
        ("outside_after", "2026-11-02T05:00:00Z"),
    ):
        contract.record(session_id, stamp)
    response = contract.heartlife.get("/api/v1/me/ecg/weekly-summary", params={"week_start": "2026-10-26"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["timezone"] == "America/New_York"
    assert data["observed_days"] == 7 and data["total_records"] == 4
    assert data["daily_series"][0]["records"] == 1
    assert data["daily_series"][6]["records"] == 3
    assert data["hr_mean"] is None
