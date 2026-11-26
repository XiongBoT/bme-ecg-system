from __future__ import annotations

from pathlib import Path
from alembic import command
from alembic.config import Config

from app.db.database import build_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations(database_url: str) -> None:
    engine = build_engine(database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    with engine.begin() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.upgrade(alembic_cfg, "head")
    engine.dispose()
