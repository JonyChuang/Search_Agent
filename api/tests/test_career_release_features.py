import io
import json
import unittest
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.exceptions import BizError
from app.core.rag.chunker import count_tokens
from app.services.career_chat_context import SUMMARY_TOKENS, clip, summarize, turn_content
from app.services.career_chat_tools import CareerChatTools, CareerToolError
from app.services.skill_packages import parse_release


def skill_zip(**extra):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("demo/manifest.yaml", "id: career-demo\nname: Demo\nversion: 1.2.0\ntools: [datetime]\n")
        archive.writestr("demo/SKILL.md", "整理岗位资料，标记证据来源。")
        for path, text in extra.items():
            archive.writestr(path, text)
    return buffer.getvalue()


class CareerSkillArchiveTests(unittest.TestCase):
    def test_public_format_uses_exact_version_and_read_only_references(self):
        release = parse_release(skill_zip(**{"demo/references/guide.md": "来源说明"}), "local")
        self.assertEqual(release.manifest.version, "1.2.0")
        self.assertEqual(release.manifest.tools, ["datetime"])
        self.assertEqual(release.references, {"references/guide.md": "来源说明"})
        self.assertEqual(len(release.digest), 64)

    def test_paths_and_reference_formats_are_rejected(self):
        with self.assertRaises(BizError):
            parse_release(skill_zip(**{"../SKILL.md": "unsafe"}), "local")
        with self.assertRaises(BizError):
            parse_release(skill_zip(**{"demo/references/script.py": "unsafe"}), "local")


class CareerHistoryTests(unittest.TestCase):
    def test_budget_prioritizes_user_constraints_and_retains_source_ids(self):
        messages = [SimpleNamespace(id=uuid.uuid4(), role="assistant", content="分析。" * 2000) for _ in range(30)]
        constraint = SimpleNamespace(id=uuid.uuid4(), role="user", content="确认：简历只用我的真实经历。")
        messages.insert(2, constraint)
        value = summarize(messages)
        self.assertLessEqual(count_tokens(value), SUMMARY_TOKENS)
        self.assertIn({"message_id": str(constraint.id), "speaker": "user", "excerpt": constraint.content}, json.loads(value))
        self.assertLessEqual(count_tokens(clip("资料里面有很多文字" * 1000, 520)), 520)
        self.assertNotIn(str(constraint.id), summarize([message for message in messages if message is not constraint]))
        question = "确认只根据已核对经历准备简历。"
        content = turn_content(question, [{"file_name": "很长的岗位资料", "text": "原始资料" * 10000}], 500)
        self.assertTrue(content.endswith(question))
        self.assertLessEqual(count_tokens(content), 500)


class CareerConversationActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_uses_confirmed_experiences_and_scoped_idempotency(self):
        job, key, confirmed, pending, resume = (uuid.uuid4() for _ in range(5))
        tools = CareerChatTools(job, "Bearer fixture")
        tools._request = AsyncMock(side_effect=[[{"id": str(confirmed), "confirmed": True},
                                                {"id": str(pending), "confirmed": False}], {"id": str(resume)}])
        self.assertEqual(await tools.create("CREATE_RESUME", key), str(resume))
        tools._request.assert_awaited_with("POST", "/api/career/resumes", json={
            "jobId": str(job), "requestId": str(key), "experienceIds": [str(confirmed)],
        })
        tools._request = AsyncMock(return_value=[{"id": str(pending), "confirmed": False}])
        with self.assertRaises(CareerToolError):
            await tools.create("CREATE_RESUME", key)
        tools._request.assert_awaited_once_with("GET", "/api/career/experiences")
