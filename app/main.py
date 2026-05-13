"""Application entrypoint for Heron."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Load ALL .env vars into os.environ so os.getenv() works for
# settings not declared in the pydantic Settings model (e.g. HERON_AI_*)
try:
    from dotenv import load_dotenv as _load_dotenv
    from .core.paths import PROJECT_ROOT as _ROOT
    _load_dotenv(_ROOT / ".env", override=False)
except Exception:
    pass  # dotenv optional — fall back to shell environment

from .core import configure_logging, get_logger, get_settings
from .api import chronicle, dashboard, discovery, explain, github, golden_signals, health, otlp, tracing, jira_auth, jobs, ops, pullers, signals
from .db.base import init_db
from .services.cluster_access import cluster_access_service
from .services.demo import demo_runner
from .services.golden_signals import golden_signals_collector
from .services.pullers.scheduler import puller_manager
from .services.tracing.scheduler import tracing_scheduler

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    """Creates app using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    configure_logging()
    app = FastAPI(
        title="Heron",
        description="Autonomous incident intelligence — observe, decide, act, learn.",
        version="0.1.0",
    )

    settings = get_settings()
    logger = get_logger(__name__)
    logger.info(
        "Starting Heron service",
        extra={"environment": settings.environment, "region": settings.region},
    )

    # Initialise database tables (idempotent — safe to call on every startup)
    init_db()

    app.include_router(chronicle.router)
    app.include_router(github.router)
    app.include_router(otlp.router)
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(discovery.router, prefix="/api/v1")
    app.include_router(golden_signals.router, prefix="/api/v1")
    app.include_router(tracing.router, prefix="/api/v1")
    app.include_router(health.router)
    app.include_router(explain.router, prefix="/api/v1")
    app.include_router(signals.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(pullers.router, prefix="/api/v1")
    app.include_router(jira_auth.router, prefix="/api/v1")
    app.include_router(ops.router, prefix="/api/v1")
    app.include_router(pullers.ui_router)
    app.include_router(jira_auth.ui_router)
    app.include_router(signals.ui_router)
    app.include_router(explain.ui_router)
    app.include_router(jobs.ui_router)
    app.include_router(ops.ui_router)
    # Legacy Jinja2 static assets
    static_dir = Path(__file__).resolve().parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve React build assets (JS/CSS/media) from /frontend/dist/assets
    if (FRONTEND_DIST / "assets").exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="frontend-assets",
        )

    # Catch-all: serve React index.html for any non-API, non-legacy path
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_react(full_path: str) -> FileResponse:
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        # Fallback when frontend hasn't been built yet
        from fastapi.responses import JSONResponse
        return JSONResponse(  # type: ignore[return-value]
            status_code=200,
            content={
                "message": "Frontend not built. Run: cd frontend && npm install && npm run build",
                "api_docs": "/docs",
            },
        )

    @app.on_event("startup")
    def _start_background_pullers() -> None:
        """Starts background pullers using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        puller_manager.start()
        cluster_access_service.start_realm_auth_monitor()
        demo_runner.start()
        golden_signals_collector.start()
        # Start tracing connector scheduler if enabled in pullers.yaml
        try:
            import yaml as _yaml
            from .core.paths import config as _cfg_path
            from pathlib import Path as _Path
            _pullers_cfg = _yaml.safe_load(_Path(_cfg_path("pullers.yaml")).read_text()) or {}
            _tracing_cfg = (_pullers_cfg.get("sources") or {}).get("tracing", {})
            if _tracing_cfg.get("enabled"):
                tracing_scheduler.start(interval_seconds=_tracing_cfg.get("interval_seconds", 30))
        except Exception as _exc:
            logger.debug("Tracing scheduler not started: %s", _exc)

    @app.on_event("shutdown")
    def _stop_background_pullers() -> None:
        tracing_scheduler.stop()
        golden_signals_collector.stop()
        demo_runner.stop()
        cluster_access_service.stop_realm_auth_monitor()
        puller_manager.stop()

    return app


def run() -> None:
    """Runs the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        host=settings.api_host,
        port=settings.api_port,
        factory=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
