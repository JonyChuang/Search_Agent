"""Replayable Redis events for one authenticated career chat turn."""

import json
from time import monotonic

from app.db.redis import get_redis

_TTL = 600
_MAX_EVENTS = 16384
_WAIT_SECONDS = 150
TERMINAL_EVENTS = {"done", "error"}


class ChatEventStream:
    def __init__(self, conversation: str, turn: str):
        self.conversation = conversation
        self.turn = turn
        self.cursor = "0-0"
        self.sequence = 0
        self.key = f"career-chat:events:{conversation}:{turn}"

    @staticmethod
    def marker(conversation: str) -> str:
        return f"career-chat:current-stream:{conversation}"

    @classmethod
    async def current(cls, conversation: str):
        turn = await get_redis().get(cls.marker(conversation))
        return cls(conversation, turn) if turn else None

    async def start(self) -> None:
        await get_redis().set(self.marker(self.conversation), self.turn, ex=_TTL)

    @classmethod
    async def clear_current(cls, conversation: str) -> None:
        await get_redis().delete(cls.marker(conversation))

    async def publish(self, event: str, data: dict) -> None:
        self.sequence += 1
        async with get_redis().pipeline(transaction=True) as tx:
            tx.xadd(self.key, {"payload": json.dumps({"event": event, "data": data}, ensure_ascii=False)},
                    id=f"{self.sequence}-0", maxlen=_MAX_EVENTS, approximate=False)
            tx.expire(self.key, _TTL)
            self.cursor, _ = await tx.execute()

    async def finished(self) -> bool:
        entries = await get_redis().xrevrange(self.key, count=1)
        return bool(entries and json.loads(entries[0][1]["payload"])["event"] in TERMINAL_EVENTS)

    async def events(self, cursor: str = "0-0"):
        deadline = monotonic() + _WAIT_SECONDS
        redis = get_redis()
        expected = int(cursor.split("-")[0]) + 1
        while monotonic() < deadline:
            blocks = await redis.xread({self.key: cursor}, count=128, block=15000)
            if not blocks:
                yield {"event": "_ping"}
                continue
            for _, entries in blocks:
                for cursor, fields in entries:
                    if cursor != f"{expected}-0":
                        yield {"event": "error", "data": {"message": "回复事件已超出可重放范围，请刷新会话。"}}
                        return
                    expected += 1
                    item = json.loads(fields["payload"])
                    yield item
                    if item["event"] in TERMINAL_EVENTS:
                        return
        yield {"event": "error", "data": {"message": "回复事件等待超时，请刷新会话查看最新记录。"}}
