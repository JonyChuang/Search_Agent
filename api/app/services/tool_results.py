"""Store oversized tool observations and expose scoped, paginated references."""

import logging
from uuid import UUID, uuid4

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.security import decrypt_secret, encrypt_secret
from app.db.postgres import SessionLocal
from app.services.career_chat_context import clip

logger = logging.getLogger(__name__)
READ_TOOL = "read_tool_result"


class ToolResultArchive:
    def __init__(self, user_id: UUID, conversation_id: UUID, job_id: UUID | None = None):
        self.scope = {"user": user_id, "conversation": conversation_id, "job": job_id}

    async def compact(self, name: str, value: str) -> str:
        if name == READ_TOOL:
            return value
        summary = clip(value, 500)
        if summary == value:
            return value
        if len(value.encode()) > 2_000_000:
            return "工具返回超过归档上限。以下是可用摘录。\n" + summary
        reference = uuid4()
        try:
            async with SessionLocal.begin() as session:
                await session.execute(text("""
                    DELETE FROM agent_tool_results WHERE id IN (
                        SELECT id FROM agent_tool_results WHERE expires_at <= now()
                        ORDER BY expires_at LIMIT 30 FOR UPDATE SKIP LOCKED
                    )
                """))
                await session.execute(text("""
                    INSERT INTO agent_tool_results(id, user_id, conversation_id, job_id, tool, ciphertext, expires_at)
                    VALUES (:id, :user, :conversation, :job, :tool, :ciphertext, now() + interval '7 days')
                """), {**self.scope, "id": reference, "tool": name, "ciphertext": encrypt_secret(value)})
        except Exception as error:
            logger.warning("Tool result archival unavailable type=%s", type(error).__name__)
            return "工具输出暂无法归档。以下是可用摘录。\n" + summary
        return f"工具结果引用 {reference}。可使用 read_tool_result 分页读取。\n{summary}"

    def reader(self):
        @tool(READ_TOOL)
        async def read_tool_result(reference: UUID, offset: int = 0) -> str:
            """读取本对话的工具结果引用。offset 从零开始，后续页使用输出中的 next_offset。"""
            if offset < 0:
                return "无效的读取位置。"
            async with SessionLocal() as session:
                encrypted = (await session.execute(text("""
                    SELECT ciphertext FROM agent_tool_results WHERE id = :id AND user_id = :user
                        AND conversation_id = :conversation AND job_id IS NOT DISTINCT FROM :job AND expires_at > now()
                """), {**self.scope, "id": reference})).scalar_one_or_none()
            if encrypted is None:
                return "该工具结果不存在或已过期。"
            value = decrypt_secret(encrypted)
            excerpt = value[offset:offset + 1000]
            next_offset = offset + len(excerpt)
            return f"next_offset={next_offset if next_offset < len(value) else 'end'}\n{excerpt}"

        return read_tool_result
