"""Opt-in reuse of the query vector used by long-term memory recall."""

import asyncio
import json
from hashlib import sha256
from math import isfinite
from uuid import UUID

from cryptography.fernet import InvalidToken
from redis.exceptions import RedisError

from app.config import settings
from app.core.cache_stats import record_cache
from app.core.exceptions import BizError
from app.core.llm.client import LLMClient
from app.core.security import decrypt_secret, encrypt_secret
from app.db.redis import get_redis


async def recall_embedding(client: LLMClient, user_id: UUID, query: str) -> list[float]:
    if not settings.memory_shared_recall_cache_enabled:
        return await client.embed_one(query)

    credential = sha256(client.api_key.encode()).hexdigest()
    identity = json.dumps([client.base_url, client.model_name, settings.embedding_dims, credential, query],
                          ensure_ascii=False)
    key = f"memory:recall-vector:v1:{user_id}:{sha256(identity.encode()).hexdigest()}"
    redis = get_redis()
    outcome = "miss"
    try:
        async with asyncio.timeout(0.15):
            cached = await redis.get(key)
        if cached and len(cached) <= 256 * 1024:
            vector = json.loads(decrypt_secret(cached))
            if isinstance(vector, list) and len(vector) == settings.embedding_dims and all(
                isinstance(value, (int, float)) and isfinite(value) for value in vector
            ):
                record_cache("memory_vector", "hit")
                return vector
    except (RedisError, TimeoutError, InvalidToken, ValueError, TypeError, OverflowError, BizError):
        outcome = "fallback"

    record_cache("memory_vector", outcome)

    vector = await client.embed_one(query)
    try:
        payload = encrypt_secret(json.dumps(vector, separators=(",", ":"), allow_nan=False))
        if len(payload) <= 256 * 1024:
            async with asyncio.timeout(0.15):
                await redis.set(key, payload, ex=120)
    except (RedisError, TimeoutError, ValueError, BizError):
        pass
    return vector
