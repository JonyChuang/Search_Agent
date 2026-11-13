from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.core.rag.chunker import count_tokens
from app.services.career_context import CONTEXT_TOKENS, CareerSourceUnavailable, assemble_context, encode
from app.services.career_task_service import CareerRun, CareerSkillUnavailable, load_career_skill


class CareerContextTest(IsolatedAsyncioTestCase):
    async def test_selected_skill_is_scoped_and_refuses_changed_revision(self):
        user, selected = uuid4(), uuid4()
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=user, kind="TRAINING",
                        context={"skillId": str(selected)})
        skill = {"id": "training", "version": 1, "instructions": "训练"}
        row = SimpleNamespace(enabled=True, prompt="练习用户访谈", updated_at=datetime.now(timezone.utc),
                              tool_keys=["external_submit"])
        repo = SimpleNamespace(get=AsyncMock(return_value=row))
        loaded = await load_career_skill(run, skill, repo)
        repo.get.assert_awaited_once_with(user, selected)
        self.assertEqual(loaded["selected"]["guidance"], "练习用户访谈")
        self.assertNotIn("external_submit", encode(loaded))
        resumed = run.model_copy(update={"agentContext": {"skill": loaded}})
        row.prompt = "修改后的技能"
        with self.assertRaises(CareerSkillUnavailable):
            await load_career_skill(resumed, skill, repo)

    async def test_source_access_budget_and_resume(self):
        user, document = uuid4(), str(uuid4())
        raw = {
            "job": {"title": "服务设计", "jd": "研究用户旅程。" * 5000},
            "documentIds": [document],
            "preferences": {"revision": 3, "notes": "每天练习 30 分钟"},
            "experiences": [{"id": str(uuid4()), "description": "服务设计。" * 6000} for _ in range(12)],
        }
        source = {"id": document, "file_name": "用户访谈.md", "revision": "a" * 64,
                  "content": "介绍 <|endoftext|>\n\n用户旅程与访谈证据\n\n" + "其他段落。" * 9000}
        skill = {"id": "training", "version": 1, "instructions": "训练"}
        with patch("app.services.career_context.read_source", new=AsyncMock(return_value=source)) as read:
            prepared, payload = await assemble_context(user, raw, None, skill)
            read.assert_awaited_once_with(user, document)
            self.assertNotIn("documents", prepared["payload"])
            self.assertNotIn("documentIds", payload)
            self.assertLessEqual(count_tokens(encode(payload)), CONTEXT_TOKENS)
            self.assertIn("访谈证据", payload["documents"][0]["excerpt"])
            self.assertEqual(prepared["references"][0]["id"], document)
            self.assertEqual(payload["preferences"]["revision"], 3)
            saved, resumed = await assemble_context(user, raw, prepared, {"version": 2})
            self.assertEqual(saved, prepared)
            self.assertEqual(resumed, payload)
            read.return_value = {**source, "content": "变更后的资料", "revision": "b" * 64}
            with self.assertRaises(CareerSourceUnavailable):
                await assemble_context(user, raw, prepared, skill)

    async def test_read_source_uses_authenticated_owner(self):
        from app.core.exceptions import BizError
        from app.services.career_context import read_source

        user, document = uuid4(), uuid4()
        preview = AsyncMock(side_effect=BizError("文档不存在", status_code=404))
        with patch("app.services.career_context.DocumentService.preview", new=preview):
            with self.assertRaises(CareerSourceUnavailable):
                await read_source(user, str(document))
        preview.assert_awaited_once_with(user, document, include_revision=True)
