import logging
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import settings
from app.storage.db import init_db
from app.storage.redis_client import init_redis
from app.auth_broker.router import router as auth_router
from app.mcp_server.server import mcp

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", env=settings.APP_ENV)
    init_db(settings.POSTGRES_DSN)
    init_redis(settings.REDIS_DSN)
    yield
    logger.info("shutdown")


app = FastAPI(title="Yandex Wiki MCP Server", lifespan=lifespan)
app.include_router(auth_router)
app.mount("/mcp", mcp.sse_app())
