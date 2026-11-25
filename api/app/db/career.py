"""Connections to the existing career business database."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import settings
from app.core.exceptions import BizError


@lru_cache(maxsize=1)
def career_engine() -> AsyncEngine:
    url = URL.create(
        "mysql+aiomysql",
        username=settings.career_mysql_user,
        password=settings.career_mysql_password.get_secret_value(),
        host=settings.career_mysql_host,
        port=settings.career_mysql_port,
        database=settings.career_mysql_database,
        query={"charset": "utf8mb4"},
    )
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        isolation_level="READ COMMITTED",
        connect_args={"init_command": "SET time_zone = '+00:00'"},
    )


@asynccontextmanager
async def career_transaction() -> AsyncIterator[AsyncConnection]:
    if not settings.career_mysql_host:
        raise BizError("求职数据库未配置", code=503, status_code=503)
    if not settings.career_mysql_password.get_secret_value():
        raise BizError("求职数据库缺少 CAREER_MYSQL_PASSWORD，请在项目根目录的 .env 配置 Compose 使用的密码",
                       code=503, status_code=503)
    async with career_engine().begin() as connection:
        yield connection


async def verify_career_schema() -> None:
    """Require the schema shared with the legacy service before accepting writes."""
    async with career_transaction() as connection:
        rows = await connection.execute(text(
            "SELECT version, success FROM flyway_schema_history WHERE version IS NOT NULL"
        ))
        applied = {row.version for row in rows if row.success}
        missing = {str(version) for version in range(1, 20)} - applied
        if missing:
            raise RuntimeError(f"Career database migrations missing: {', '.join(sorted(missing))}")


async def close() -> None:
    if career_engine.cache_info().currsize:
        await career_engine().dispose()
        career_engine.cache_clear()
