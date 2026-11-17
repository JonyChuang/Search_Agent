"""Cross-worker admission and ownership for career conversation turns."""
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.db.redis import get_redis

TURN_LIMIT_SECONDS = 115
LEASE_SECONDS = 150
USER_LIMIT = 3
GLOBAL_LIMIT = 24
KEY_PREFIX = "career-chat:{turns}:"

CLAIM = """
local now = tonumber(redis.call('TIME')[1])
local ttl = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3])
    or redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[4]) then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ttl)
redis.call('ZADD', KEYS[2], now + ttl, ARGV[1])
redis.call('ZADD', KEYS[3], now + ttl, ARGV[1])
redis.call('EXPIRE', KEYS[2], ttl)
redis.call('EXPIRE', KEYS[3], ttl)
return 1
"""

RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('DEL', KEYS[1]) end
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return 1
"""


@dataclass(frozen=True)
class CareerChatLease:
    keys: tuple[str, str, str]
    owner: str

    @classmethod
    async def claim(cls, conversation: UUID, user: UUID):
        keys = (KEY_PREFIX + f"conversation:{conversation}", KEY_PREFIX + f"user:{user}", KEY_PREFIX + "global")
        owner = str(uuid4())
        acquired = await get_redis().eval(CLAIM, 3, *keys, owner, LEASE_SECONDS, USER_LIMIT, GLOBAL_LIMIT)
        return cls(keys, owner) if acquired else None

    async def release(self):
        await get_redis().eval(RELEASE, 3, *self.keys, self.owner)
