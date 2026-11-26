from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.db.migrations_runner import run_migrations  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402


def main() -> int:
    settings = Settings()
    try:
        run_migrations(settings.database_url)
        summary = seed_demo_data(settings)
        print(f"Seed demo completed: {summary}")
        return 0
    except PermissionError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
