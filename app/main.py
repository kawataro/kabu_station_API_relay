"""FastAPI entrypoint and startup sequence.

Startup order (fail-fast):
  1. config + env
  2. secret presence check
  3. symbols<=50 / port validation (already in load_settings)
  4. SQLite schema init
  5. kabu token initial fetch
  6. collector background thread start
  7. FastAPI listen
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import install_auth
from .collector import Collector
from .db import init_schema
from .export_service import ExportService
from .kabu_client import KabuClient
from .settings import ConfigError, RelaySettings, load_settings
from .token_manager import TokenManager
from .routes import (
    boards as boards_route,
    export as export_route,
    health as health_route,
    price_changes as price_changes_route,
    snapshots as snapshots_route,
    status as status_route,
    symbols as symbols_route,
)


log = logging.getLogger("kabu_relay")


def _configure_logging() -> None:
    """Configure stderr + rotating file handlers.

    File output goes to `KABU_RELAY_LOG_DIR/relay.log` (defaults to `./logs`)
    with rotation at 10MiB × 5 files. Set `KABU_RELAY_DISABLE_FILE_LOG=1` to
    skip the file handler (e.g. in tests).

    Secrets are never written to logs by code anywhere; this configuration
    does not change that.
    """
    level = os.environ.get("KABU_RELAY_LOG_LEVEL", "INFO").upper()
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    # Replace existing handlers — uvicorn / pytest may have set their own.
    for h in list(root.handlers):
        root.removeHandler(h)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(stream_handler)

    if not os.environ.get("KABU_RELAY_DISABLE_FILE_LOG"):
        log_dir = Path(os.environ.get("KABU_RELAY_LOG_DIR", "./logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                str(log_dir / "relay.log"),
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(fmt))
            root.addHandler(file_handler)
        except OSError as e:
            # logs/ is not writable — keep stderr only and surface the reason
            # via the logger we just attached, so the stream handler emits it.
            logging.getLogger("kabu_relay").warning(
                "file logging disabled (continuing with stderr only): %s", e
            )


def build_app(settings: RelaySettings | None = None) -> FastAPI:
    _configure_logging()

    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as e:
            log.error("config error: %s", e)
            raise

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. DB schema init
        init_schema(settings.storage.db_path)

        # 2. kabu client + token manager
        client = KabuClient(
            host=settings.kabu.host,
            port=settings.kabu.port,
            api_password=settings.api_password,
        )
        token_mgr = TokenManager(client)

        # 3. Initial token fetch — fail-fast unless explicitly degraded.
        if settings.kabu.token_refresh.on_start:
            ok = token_mgr.refresh()
            if not ok and not _allow_degraded_start():
                raise RuntimeError(
                    "initial kabu token fetch failed (set KABU_RELAY_ALLOW_DEGRADED=1 to override)"
                )

        # 4. export service
        export_svc = ExportService(
            db_path=settings.storage.db_path,
            export_dir=settings.storage.export_dir,
            keep=settings.storage.keep_exports,
        )

        # 5. collector thread
        collector = Collector(settings, client, token_mgr)
        collector.start()

        app.state.settings = settings
        app.state.kabu_client = client
        app.state.token_manager = token_mgr
        app.state.collector = collector
        app.state.export_service = export_svc

        log.info(
            "kabu-relay started host=%s port=%d symbols=%d",
            settings.server.listen_host,
            settings.server.listen_port,
            len(settings.symbols),
        )

        try:
            yield
        finally:
            log.info("shutting down kabu-relay")
            collector.stop()

    app = FastAPI(
        title="kabu-relay",
        version=settings.service.version,
        lifespan=lifespan,
    )
    app.state.settings = settings  # also visible before lifespan runs

    install_auth(app, settings)

    app.include_router(health_route.router)
    app.include_router(status_route.router)
    app.include_router(symbols_route.router)
    app.include_router(boards_route.router)
    app.include_router(snapshots_route.router)
    app.include_router(price_changes_route.router)
    app.include_router(export_route.router)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request, exc: StarletteHTTPException):
        # Normalize HTTPException(detail=dict) into the standard error envelope.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_query",
                "message": "request validation failed",
            },
        )

    return app


def _allow_degraded_start() -> bool:
    return os.environ.get("KABU_RELAY_ALLOW_DEGRADED", "").lower() in {"1", "true", "yes"}


# Module-level app for `uvicorn app.main:app`.
# Skip wiring during pytest collection or when running as a script (we'll
# build it inside main() instead) so we don't construct the app twice.
_should_skip_boot = (
    "pytest" in sys.modules
    or bool(os.environ.get("KABU_RELAY_SKIP_BOOT"))
    or __name__ == "__main__"
)
if not _should_skip_boot:
    try:
        app = build_app()
    except ConfigError:
        # Defer the failure to the runner; pytest discovery shouldn't crash.
        app = FastAPI(title="kabu-relay (config-error)")
else:
    app = FastAPI(title="kabu-relay (deferred)")


def main() -> int:
    import uvicorn

    settings = load_settings()
    application = build_app(settings)
    uvicorn.run(
        application,
        host=settings.server.listen_host,
        port=settings.server.listen_port,
        log_level=os.environ.get("KABU_RELAY_LOG_LEVEL", "info").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
