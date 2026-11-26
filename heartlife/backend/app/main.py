from __future__ import annotations

from contextlib import asynccontextmanager
import importlib
from pathlib import Path
import uuid
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.deps import get_settings
from app.core.errors import register_exception_handlers
from app.core.security import LoginRateLimiter
from app.db.database import build_session_factory
from app.db.migrations_runner import run_migrations

OPTIONAL_MODULE_ROUTERS = [
    "app.accounts.router",
    "app.community.router",
    "app.journal.router",
    "app.plans.router",
    "app.knowledge.router",
    "app.reports.router",
    "app.notifications.router",
    "app.privacy.router",
    "app.challenges.router",
    "app.assistant.router",
    "app.family.router",
    "app.ecg.router",
]


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    cfg = settings or Settings()
    clk = clock or SystemClock()
    engine, session_factory = build_session_factory(cfg.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        run_migrations(cfg.database_url)
        yield
        engine.dispose()

    app = FastAPI(
        title="HeartLife API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.clock = clk
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.rate_limiter = LoginRateLimiter(
        max_attempts=cfg.login_rate_limit_count,
        window_seconds=cfg.login_rate_limit_window_seconds,
    )
    app.state.llm_provider = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.frontend_origin, "http://127.0.0.1:5174", "http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-Id"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        req_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response

    register_exception_handlers(app)

    system_router = APIRouter(prefix="/api/v1", tags=["system"])

    @system_router.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ready", "service": "heartlife"}

    @system_router.get("/public-config")
    def public_config(s: Settings = Depends(get_settings)) -> dict[str, object]:
        return {
            "assistant_enabled": s.is_assistant_available,
            "ecg_external_url": s.ecg_external_url,
            "ecg_integration_enabled": s.is_ecg_integration_enabled,
            "demo_mode": s.demo_mode,
        }

    app.include_router(system_router)

    for module_path in OPTIONAL_MODULE_ROUTERS:
        try:
            mod = importlib.import_module(module_path)
            router = getattr(mod, "router", None)
            if router is not None:
                app.include_router(router, prefix="/api/v1")
        except ModuleNotFoundError as exc:
            # Only ignore when the top-level feature subpackage itself hasn't been created yet
            if exc.name == module_path or (exc.name and module_path.startswith(exc.name)):
                continue
            raise

    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.is_dir() and (dist_dir / "index.html").is_file():
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def serve_spa(full_path: str):
            if full_path.startswith("api/"):
                from app.core.errors import AppError
                raise AppError(404, "NOT_FOUND", "接口不存在")
            candidate = (dist_dir / full_path).resolve()
            if candidate.is_file() and str(candidate).startswith(str(dist_dir.resolve())):
                return FileResponse(str(candidate))
            return FileResponse(str(dist_dir / "index.html"))

    return app


app = create_app()
