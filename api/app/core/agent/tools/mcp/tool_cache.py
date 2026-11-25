"""Shared cache for MCP tool descriptors, with bounded Redis access."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from hashlib import sha256
from uuid import uuid4

from mcp.types import Tool
from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.db.redis import get_redis

logger = get_logger(__name__)
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
_STORE = """
if redis.call('get', KEYS[2]) == ARGV[1] then
    return redis.call('set', KEYS[1], ARGV[2], 'EX', 300)
end
return 0
"""
MAX_BYTES = 256 * 1024


async def _redis(call, *args, **kwargs):
    async with asyncio.timeout(0.25):
        return await call(*args, **kwargs)


async def _read(redis, key):
    raw = await _redis(redis.get, key)
    if raw and len(raw) <= MAX_BYTES:
        return [Tool.model_validate(item) for item in json.loads(raw)]
    return None


async def load_descriptors(
    user_id: str, server_id: str, version: str, fetch: Callable[[], Awaitable[list[Tool]]],
) -> list[Tool]:
    redis = get_redis()
    key = f"mcp:tools:v1:{user_id}:{server_id}:{sha256(version.encode()).hexdigest()}"
    lock = f"{key}:load"
    owner = uuid4().hex
    # Wait for the instance that owns the load, bounded by the caller's overall MCP timeout.
    while True:
        try:
            cached = await _read(redis, key)
            if cached is not None:
                logger.debug("MCP descriptor cache hit: server=%s", server_id)
                return cached
            acquired = await _redis(redis.set, lock, owner, nx=True, ex=10)
        except (TimeoutError, RedisError):
            return await fetch()
        except (TypeError, ValueError):
            # A malformed entry should never prevent loading the live descriptors.
            return await fetch()
        if acquired:
            break
        await asyncio.sleep(0.1)
    try:
        try:
            cached = await _read(redis, key)
            if cached is not None:
                return cached
        except (TimeoutError, RedisError, TypeError, ValueError):
            pass
        tools = await fetch()
        payload = json.dumps([
            tool.model_dump(mode="json", by_alias=True, include={
                "name", "title", "description", "inputSchema", "outputSchema", "annotations",
            }, exclude_none=True)
            for tool in tools
        ], ensure_ascii=False)
        if len(payload.encode()) <= MAX_BYTES:
            try:
                await _redis(redis.eval, _STORE, 2, key, lock, owner, payload)
            except (TimeoutError, RedisError):
                pass
        return tools
    finally:
        try:
            await _redis(redis.eval, _RELEASE, 1, lock, owner)
        except (TimeoutError, RedisError):
            pass
