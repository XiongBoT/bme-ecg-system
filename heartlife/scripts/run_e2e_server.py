from __future__ import annotations

"""Dedicated clean isolated E2E server runner for Playwright tests.
Builds/serves the built SPA + FastAPI on port 8018 using a fresh temporary SQLite DB
with DEMO_MODE=1 seeded accounts so E2E tests are 100% deterministic and self-contained.
"""

import os
import sys
import tempfile
from pathlib import Path
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.db.migrations_runner import run_migrations  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402


def main() -> None:
    tmp_dir = tempfile.mkdtemp(prefix="heartlife_e2e_")
    db_path = Path(tmp_dir) / "e2e.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    ecg_url = os.environ.get("E2E_ECG_EXTERNAL_URL", "")
    assistant_on = os.environ.get("E2E_ASSISTANT_ENABLED", "false").lower() == "true"

    settings = Settings(
        app_env="test",
        app_host="127.0.0.1",
        app_port=8018,
        frontend_origin="http://127.0.0.1:8018",
        database_url=db_url,
        demo_mode=True,
        assistant_enabled=assistant_on,
        assistant_provider="deterministic",
        ecg_external_url=ecg_url or None,
    )
    run_migrations(db_url)
    seed_demo_data(settings)

    app = create_app(settings=settings)
    uvicorn.run(app, host="127.0.0.1", port=8018, log_level="warning")


if __name__ == "__main__":
    main()
