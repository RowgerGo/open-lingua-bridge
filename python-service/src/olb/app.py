"""FastAPI application factory and CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import ServiceConfig
from .errors import ErrorCode, ServiceError
from .runtime.http_api import make_router
from .runtime.metrics import Metrics
from .runtime.model_manager import ModelManager
from .runtime.pipeline_orchestrator import PipelineOrchestrator
from .runtime.session_manager import SessionManager
from .runtime.ws import make_ws_router
from .schemas.protocol import Envelope


def build_app(cfg: ServiceConfig | None = None) -> FastAPI:
    cfg = cfg or ServiceConfig.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    mm = ModelManager(cfg)
    sm = SessionManager()
    metrics = Metrics()
    orchestrator = PipelineOrchestrator(mm, sm, metrics)
    app = FastAPI(title="open-lingua-bridge model service", version="0.1.0")
    app.include_router(make_router(cfg, mm, sm))
    app.include_router(make_ws_router(cfg, mm, sm, orchestrator))

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        envelope = Envelope(success=False, code=exc.code.value, message=exc.message)
        return JSONResponse(status_code=400, content=envelope.model_dump())

    @app.get("/")
    def root() -> dict:
        return Envelope(data={"service": "olb", "version": "0.1.0"}).model_dump()

    app.state.cfg = cfg
    app.state.mm = mm
    app.state.sm = sm
    app.state.metrics = metrics
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="olb-model-service")
    parser.add_argument("--host", default=os.environ.get("OLB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OLB_PORT", "8765")))
    parser.add_argument("--auth-token", default=os.environ.get("OLB_AUTH_TOKEN", "dev-token"))
    parser.add_argument("--log-level", default=os.environ.get("OLB_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)
    cfg = ServiceConfig(
        host=args.host,
        port=args.port,
        auth_token=args.auth_token,
        log_level=args.log_level.upper(),
    )
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=cfg.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
