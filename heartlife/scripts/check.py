from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.exists():
    VENV_PY = Path(sys.executable)


def run_step(label: str, cmd: list[str], cwd: Path) -> None:
    print(f"\n==> [{label}] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(cwd), shell=(sys.platform == "win32" and cmd[0] in ("npm", "npx")))
    if res.returncode != 0:
        raise SystemExit(res.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="HeartLife unified check runner")
    parser.add_argument("--suite", choices=["all", "backend", "frontend", "e2e"], default="all")
    args = parser.parse_args()

    if args.suite in ("all", "backend"):
        run_step("Backend Pytest", [str(VENV_PY), "-m", "pytest", "-q"], BACKEND)

    if args.suite in ("all", "frontend"):
        run_step("Frontend Typecheck", ["npm", "run", "typecheck"], FRONTEND)
        run_step("Frontend Vitest", ["npm", "run", "test", "--", "--run"], FRONTEND)
        run_step("Frontend Build", ["npm", "run", "build"], FRONTEND)

    if args.suite in ("all", "e2e"):
        run_step("Playwright E2E", ["npx", "playwright", "test"], FRONTEND)

    print("\nAll requested HeartLife checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
