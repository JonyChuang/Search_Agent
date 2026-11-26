"""Versioned, owner-scoped job constraints backed by PostgreSQL."""

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from app.core.exceptions import BizError
from app.models.conversation_model import Message
from app.repositories.conversation_repository import ConversationRepository, MessageRepository
from app.services.career_chat_context import extract_constraints, latest_constraints, normalize_constraint_value
from app.services.career_training_contract import TrainingContractError, fixed_deadline


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
            SELECT version, state, source, created_at, field_meta FROM career_context_versions
            WHERE conversation_id = :conversation AND job_id = :job
                AND (CAST(:version AS INTEGER) IS NULL OR version = :version)
            ORDER BY version DESC LIMIT 1
        """), {**self.keys, "version": version})).mappings().one_or_none()

    async def read(self, version=None) -> dict:
        await self._verify()
        row = await self._latest(version)
        if row is not None:
            state = {}
            for key, (source, value) in row["state"].items():
                legacy = key not in (row["field_meta"] or {})
                normalized = normalize_constraint_value(key, value) if source and legacy else value
                if normalized is not None:
                    state[key] = [source, normalized]
            return {**dict(row), "state": state}
        if version is not None:
            raise BizError("上下文版本不存在", code=404, status_code=404)
        history = MessageRepository(self.session).job_user_history(self.keys["conversation"], self.user_id, self.keys["job"])
        return {"version": 0, "state": await latest_constraints(history), "source": "history"}

    async def save(self, *, message: Message | None = None, edits=None, expected=None, rollback=None,
                   time_zone: str | None = None) -> dict:
        # Serialize chat edits and explicit user edits for the same conversation/job.
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                                   {"scope": f"career-context:{self.keys['conversation']}:{self.keys['job']}"})
        current = await self.read()
        version = current["version"]
        if expected is not None and expected != version:
            raise BizError("上下文已更新，请刷新后再修改", code=409, status_code=409)
        state = dict(current["state"])
        metadata = current.get("field_meta") or {
            key: {"version": version, "confirmed": version > 0} for key in state
        }
        next_meta = dict(metadata)
        if rollback is not None:
            restored = await self.read(rollback)
            state = restored["state"]
            next_meta = restored.get("field_meta") or {
                key: {"version": rollback, "confirmed": True} for key in state
            }
            source = f"rollback:{rollback}"
        elif message is not None:
            if message.conversation_id != self.keys["conversation"] or message.role != "user":
                raise BizError("约束来源不属于本次用户对话", code=400, status_code=400)
            self.session.add(message)
            await self.session.flush()
            edits = extract_constraints(message.content)
            source = "message"
        else:
            source = "user_edit"
        if rollback is None:
            for field, value in (edits or {}).items():
                if value is None:
                    state.pop(field, None)
                    next_meta.pop(field, None)
                else:
                    entry = [str(message.id) if message is not None else None, value.strip()]
                    previous = next_meta.get(field, {})
                    details = {"version": version + 1, "confirmed": True}
                    if field == "截止时间":
                        anchor = getattr(message, "created_at", None) or datetime.now(timezone.utc)
                        try:
                            details.update(fixed_deadline(entry[1], anchor, time_zone))
                        except TrainingContractError as error:
                            if message is None:
                                raise BizError(str(error), code=409, status_code=409) from error
                            details.update(rawValue=entry[1], confirmed=False, status="AMBIGUOUS")
                    if (tuple(state.get(field, ())) != tuple(entry) or not previous.get("confirmed")
                            or details.get("normalizedValue") != previous.get("normalizedValue")):
                        next_meta[field] = details
                    state[field] = entry
        comparable = {key: list(value) for key, value in current["state"].items()}
        if version > 0 and state == comparable and next_meta == metadata:
            await self.session.commit()
            return current
        await self.session.execute(text("""
            INSERT INTO career_context_versions(conversation_id, job_id, version, state, source, field_meta)
            VALUES (:conversation, :job, :version, CAST(:state AS JSONB), :source, CAST(:field_meta AS JSONB))
        """), {**self.keys, "version": version + 1, "state": json.dumps(state, ensure_ascii=False), "source": source,
               "field_meta": json.dumps(next_meta, ensure_ascii=False)})
        await self.session.commit()
        return {"version": version + 1, "state": state, "source": source, "field_meta": next_meta}
