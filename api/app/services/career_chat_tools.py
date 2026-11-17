"""Job-scoped tools for an authenticated chat turn."""
import json
import re
import uuid

import httpx
from langchain_core.tools import tool

from app.config import settings

CREATE_PLAN_TOOL = "create_career_training_plan"
CAREER_ACTION_TOOLS = {
    "CREATE_INTERVIEW": ("start_career_interview", "创建当前岗位的文字模拟面试"),
    "CREATE_APPLICATION": ("create_career_application", "准备当前岗位的网申草稿"),
    "CREATE_RESUME": ("create_career_resume", "用已确认的经历生成岗位简历草稿"),
}
PLAN_REQUEST = re.compile(
    r"(?:请\s*|帮我\s*|给我\s*)*(?:为\s*(?:当前|这个|该)(?:目标)?岗位\s*)?"
    r"(?:生成|创建|制定|做)\s*(?:一份|一个)?\s*(?:岗位)?(?:备考|训练)计划[。！!]*"
)


def requests_plan(message: str) -> bool:
    return len(message) <= 120 and bool(PLAN_REQUEST.fullmatch(message.strip()))


class CareerToolError(Exception):
    pass


class CareerChatTools:
    def __init__(self, job_id: uuid.UUID, authorization: str):
        self.job_id = job_id
        self.authorization = authorization

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with httpx.AsyncClient(
                base_url=settings.career_backend_base_url, timeout=8, trust_env=False,
                headers={"Authorization": self.authorization},
            ) as client:
                reply = await client.request(method, path, **kwargs)
                payload = reply.json()
                if reply.status_code in (400, 404, 409, 429):
                    raise CareerToolError(payload.get("message") or "求职任务暂时无法执行。")
                reply.raise_for_status()
                return payload["data"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise CareerToolError("暂时无法连接求职服务，请稍后重试。") from error

    async def create_plan(self, request_id: uuid.UUID) -> str:
        data = await self._request("POST", "/api/career/tasks/training",
                                   json={"jobId": str(self.job_id), "requestId": str(request_id)})
        try:
            return str(uuid.UUID(data["id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CareerToolError("求职服务未返回任务编号，请重试。") from error

    async def create(self, action: str, request_id: uuid.UUID) -> str:
        job = {"jobId": str(self.job_id)}
        if action == "CREATE_INTERVIEW":
            data = await self._request("POST", "/api/career/interviews", json={
                **job, "requestId": str(request_id), "mode": "TEXT", "count": 5,
            })
            data = data.get("summary") or {}
        elif action == "CREATE_APPLICATION":
            data = await self._request("POST", "/api/career/applications", json=job)
        else:
            experiences = await self._request("GET", "/api/career/experiences")
            confirmed = [item["id"] for item in experiences if item.get("confirmed")][:12]
            if not confirmed:
                raise CareerToolError("请先在简历制作中确认至少一条真实经历，再生成岗位简历。")
            data = await self._request("POST", "/api/career/resumes", json={
                **job, "requestId": str(request_id), "experienceIds": confirmed,
            })
        try:
            return str(uuid.UUID(data["id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CareerToolError("求职服务未返回记录编号，请重试。") from error

    def read_tools(self) -> list:
        @tool
        async def read_career_job() -> str:
            """读取用户当前选中的求职岗位、岗位描述与技能要求。"""
            data = await self._request("GET", f"/api/career/jobs/{self.job_id}")
            return json.dumps({
                "company": data["company"], "title": data["title"],
                "description": data["description"][:6000], "skills": data.get("skills"),
            }, ensure_ascii=False)

        @tool
        async def read_career_training_progress() -> str:
            """查询当前岗位最近的备考计划及其状态、已完成题量。"""
            data = await self._request("GET", "/api/career/tasks",
                                       params={"jobId": str(self.job_id), "kind": "TRAINING", "page": 1})
            if not data["items"]:
                return "当前岗位还没有备考计划。"
            latest = data["items"][0]
            progress = {"status": latest["status"]}
            if latest["status"] == "SUCCEEDED":
                task_id = uuid.UUID(latest["id"])
                completed = await self._request("GET", f"/api/career/tasks/{task_id}/training-progress")
                progress["completed"] = len(completed)
                progress["total"] = len((latest.get("result") or {}).get("questions", []))
            return json.dumps(progress, ensure_ascii=False)

        @tool
        async def read_career_practice_signals() -> str:
            """查看当前岗位的客观题练习反馈与模拟面试表现，辅助安排复习。"""
            data = await self._request("GET", f"/api/career/jobs/{self.job_id}/learning-signals")
            return json.dumps(data, ensure_ascii=False)

        return [read_career_job, read_career_training_progress, read_career_practice_signals]
