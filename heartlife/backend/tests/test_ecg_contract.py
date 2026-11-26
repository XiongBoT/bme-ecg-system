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

    def code(self) -> str:
        response = self.owner.post("/api/heartlife/link-code")
        assert response.status_code == 200, response.text
        return response.json()["code"]

    def bind(self):
        response = self.heartlife.post("/api/v1/me/ecg/link", json={"code": self.code()})
        assert response.status_code == 200, response.text
        assert response.json()["linked"] is True
        return response

    def summary(self, client=None, period="day", anchor="2026-11-25"):
        return (client or self.heartlife).get("/api/v1/me/ecg/summary", params={
            "period": period, "anchor": anchor,
        })

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
