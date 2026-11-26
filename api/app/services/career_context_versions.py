"""Versioned, owner-scoped job constraints backed by PostgreSQL."""

import json
from uuid import UUID

from sqlalchemy import text

from app.core.exceptions import BizError
from app.repositories.conversation_repository import ConversationRepository, MessageRepository
from app.services.career_chat_context import extract_constraints, latest_constraints


class CareerContextVersions:
    def __init__(self, session, user_id: UUID, conversation_id: UUID, job_id: UUID):
        self.session = session
        self.user_id = user_id
        self.keys = {"conversation": conversation_id, "job": job_id}

    async def _verify(self):
        conv = await ConversationRepository(self.session).get(self.user_id, self.keys["conversation"])
        if conv is None or conv.is_group:
            raise BizError("会话不存在", code=404, status_code=404)

    async def _latest(self, version: int | None = None):
        return (await self.session.execute(text("""
            SELECT version, state, source, created_at FROM career_context_versions
            WHERE conversation_id = :conversation AND job_id = :job
                AND (CAST(:version AS INTEGER) IS NULL OR version = :version)
            ORDER BY version DESC LIMIT 1
        """), {**self.keys, "version": version})).mappings().one_or_none()

    async def read(self, version=None) -> dict:
        await self._verify()
        row = await self._latest(version)
        if row is not None:
            return dict(row)
        if version is not None:
            raise BizError("上下文版本不存在", code=404, status_code=404)
        history = MessageRepository(self.session).job_user_history(self.keys["conversation"], self.user_id, self.keys["job"])
        return {"version": 0, "state": await latest_constraints(history), "source": "history"}

    async def save(self, *, message_id=None, message_text=None, edits=None, expected=None, rollback=None) -> dict:
        # Serialize chat edits and explicit user edits for the same conversation/job.
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                                   {"scope": f"career-context:{self.keys['conversation']}:{self.keys['job']}"})
        current = await self.read()
        version = current["version"]
        if expected is not None and expected != version:
            raise BizError("上下文已更新，请刷新后再修改", code=409, status_code=409)
        state = dict(current["state"])
        if rollback is not None:
            state = (await self.read(rollback))["state"]
            source = f"rollback:{rollback}"
        elif message_id is not None:
            state.update({field: [str(message_id), value] for field, value in extract_constraints(message_text).items()})
            source = "message"
        else:
            for field, value in edits.items():
                if value is None:
                    state.pop(field, None)
                else:
                    state[field] = [None, value]
            source = "user_edit"
        comparable = {key: list(value) for key, value in current["state"].items()}
        if version > 0 and state == comparable:
            await self.session.commit()
            return current
        await self.session.execute(text("""
            INSERT INTO career_context_versions(conversation_id, job_id, version, state, source)
            VALUES (:conversation, :job, :version, CAST(:state AS JSONB), :source)
        """), {**self.keys, "version": version + 1, "state": json.dumps(state, ensure_ascii=False), "source": source})
        await self.session.commit()
        return {"version": version + 1, "state": state, "source": source}
