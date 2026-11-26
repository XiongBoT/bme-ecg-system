from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def test_t0001_clean_init_migrate_and_health(tmp_path: Path):
    """T-0001: Empty temp directory without legacy ECG -> migrate, start, health ready."""
    from app.core.config import Settings
    from app.db.migrations_runner import run_migrations
    from app.main import create_app

    db_file = tmp_path / "clean_t0001.db"
    settings = Settings(database_url=f"sqlite:///{db_file.as_posix()}", app_env="test", demo_mode=False)
    run_migrations(settings.database_url)

    app = create_app(settings=settings)
    with TestClient(app) as client:
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ready"
        assert "database_url" not in body
        assert "clean_t0001" not in res.text

        cfg = client.get("/api/v1/public-config")
        assert cfg.status_code == 200
        assert cfg.json()["assistant_enabled"] is False
        assert cfg.json()["ecg_external_url"] is None


def test_t0002_idempotent_migrations_preserve_data(tmp_path: Path):
    """T-0002: Repeated migrations on an existing DB preserve data and do not duplicate tables."""
    from sqlalchemy import select
    from app.core.config import Settings
    from app.db.database import build_session_factory
    from app.db.migrations_runner import run_migrations
    from app.db.models import User

    db_file = tmp_path / "idem_t0002.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    run_migrations(db_url)

    _, SessionLocal = build_session_factory(db_url)
    with SessionLocal() as session:
        session.add(
            User(
                account="keepme",
                password_hash="argon2id$hash",
                nickname="保留用户",
                timezone="Asia/Shanghai",
                roles="member",
                status="active",
            )
        )
        session.commit()

    # Run migrations a second and third time
    run_migrations(db_url)
    run_migrations(db_url)

    with SessionLocal() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].account == "keepme"


def test_t0003_seed_demo_rejected_when_demo_mode_disabled(tmp_path: Path):
    """T-0003: Demo seed refuses to run when DEMO_MODE is false or non-local env."""
    from sqlalchemy import func, select
    from app.core.config import Settings
    from app.db.database import build_session_factory
    from app.db.migrations_runner import run_migrations
    from app.db.models import User
    from app.seed import seed_demo_data

    db_file = tmp_path / "nodemo_t0003.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    run_migrations(db_url)

    settings_off = Settings(database_url=db_url, app_env="local", demo_mode=False)
    with pytest.raises(PermissionError):
        seed_demo_data(settings_off)

    settings_prod = Settings(database_url=db_url, app_env="production", demo_mode=True)
    with pytest.raises(PermissionError):
        seed_demo_data(settings_prod)

    _, SessionLocal = build_session_factory(db_url)
    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(User))
        assert count == 0


def test_t0004_seed_demo_idempotent_and_explicitly_labeled(tmp_path: Path):
    """T-0004: Repeated seed_demo in DEMO_MODE=1 creates fixed non-duplicated synthetic records marked as demo."""
    from sqlalchemy import select
    from app.core.config import Settings
    from app.db.database import build_session_factory
    from app.db.migrations_runner import run_migrations
    from app.db.models import Article, Challenge, Post, User
    from app.seed import seed_demo_data

    db_file = tmp_path / "demo_t0004.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    run_migrations(db_url)

    settings = Settings(database_url=db_url, app_env="local", demo_mode=True)
    first_summary = seed_demo_data(settings)
    second_summary = seed_demo_data(settings)
    assert first_summary == second_summary

    _, SessionLocal = build_session_factory(db_url)
    with SessionLocal() as session:
        users = session.scalars(select(User)).all()
        posts = session.scalars(select(Post)).all()
        articles = session.scalars(select(Article)).all()
        challenges = session.scalars(select(Challenge)).all()

        assert len(users) == 4
        assert all(u.is_demo is True for u in users)
        assert len(posts) >= 4
        assert all(p.is_demo is True for p in posts)
        assert len(articles) >= 10
        assert len(challenges) >= 3


@pytest.mark.parametrize(
    "raw_url,expected",
    [
        ("", None),
        ("https://ecg.example.edu/login", "https://ecg.example.edu/login"),
        ("http://ecg.example.edu/login", None),
        ("javascript:alert(1)", None),
        ("file:///etc/passwd", None),
        ("https://user:secret@ecg.example.edu/", None),
        ("https://ecg.example.edu/?token=abc", None),
        ("https://ecg.example.edu/?uid=123", None),
        ("https://ecg.example.edu/#frag", None),
    ],
)
def test_t1001_t1002_t1003_external_ecg_url_validation(tmp_path: Path, raw_url: str, expected: str | None):
    """T-1001/T-1002/T-1003: Only clean HTTPS external URLs without credentials or query params are exposed."""
    from app.core.config import Settings
    from app.db.migrations_runner import run_migrations
    from app.main import create_app

    db_file = tmp_path / "urlguard.db"
    settings = Settings(
        database_url=f"sqlite:///{db_file.as_posix()}",
        app_env="test",
        ecg_external_url=raw_url,
    )
    run_migrations(settings.database_url)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        res = client.get("/api/v1/public-config")
        assert res.status_code == 200
        assert res.json()["ecg_external_url"] == expected
        health = client.get("/api/v1/health")
        assert health.status_code == 200
