from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.database import build_session_factory
from app.db.migrations_runner import run_migrations
from app.main import create_app


@pytest.fixture()
def fake_clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    db_file = tmp_path / "test_heartlife.db"
    url = f"sqlite:///{db_file.as_posix()}"
    run_migrations(url)
    return Settings(
        database_url=url,
        app_env="test",
        demo_mode=False,
        login_rate_limit_count=5,
        login_rate_limit_window_seconds=900,
    )


@pytest.fixture()
def app_instance(test_settings: Settings, fake_clock: FakeClock):
    return create_app(settings=test_settings, clock=fake_clock)


@pytest.fixture()
def client(app_instance):
    with TestClient(app_instance) as c:
        yield c


@pytest.fixture()
def db_session(test_settings: Settings):
    engine, factory = build_session_factory(test_settings.database_url)
    with factory() as s:
        yield s
    engine.dispose()
