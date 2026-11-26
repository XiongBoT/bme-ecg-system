from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.db.migrations_runner import run_migrations  # noqa: E402


def main() -> int:
    settings = Settings()
    run_migrations(settings.database_url)
    print(f"Migrations applied successfully for {settings.app_env} environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
