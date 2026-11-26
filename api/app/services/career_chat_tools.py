"""Job-scoped tools for an authenticated chat turn."""
import json
import logging
import re
import uuid

import httpx
from fastapi.encoders import jsonable_encoder
from langchain_core.tools import tool

from app.config import settings
from app.core.exceptions import BizError
from app.db.career import career_transaction
from app.services.career_applications import CareerApplications
from app.services.career_interviews import CareerInterviews
from app.services.career_queue import CareerQueue
from app.services.career_records import CareerRecords
from app.services.career_resumes import CareerResumes
from app.services.career_training import CareerTraining

CREATE_PLAN_TOOL = "create_career_training_plan"
logger = logging.getLogger(__name__)
CAREER_ACTION_TOOLS = {
    "CREATE_INTERVIEW": ("start_career_interview", "创建当前岗位的文字模拟面试"),
    "CREATE_APPLICATION": ("create_career_application", "准备当前岗位的网申草稿"),
    "CREATE_RESUME": ("create_career_resume", "用已确认的经历生成岗位简历草稿"),
}
PLAN_REQUEST = re.compile(
    r"(?:请\s*|帮我\s*|给我\s*)*(?:为\s*(?:当前|这个|该)(?:目标)?岗位\s*)?"
    r"(?:生成|创建|制定|做)\s*(?:一份|一个)?\s*(?:岗位)?(?:备考|训练)计划[。！!]*"
)
REPLAN_REQUEST = re.compile(
    r"(?:请\s*|帮我\s*)*(?:(?:按照|根据)(?:新的?|当前的?)(?:截止时间|复习顺序|岗位约束))?"
    r"重新(?:安排|制定|生成)(?:我的?|当前的?)?(?:备考|训练)计划[。！!]*"
)


def requests_plan(message: str) -> bool:
    return len(message) <= 120 and any(rule.fullmatch(message.strip()) for rule in (PLAN_REQUEST, REPLAN_REQUEST))


class CareerToolError(Exception):
    pass


class CareerChatTools:
    def __init__(self, job_id: uuid.UUID, authorization: str, user_id: uuid.UUID | None = None):
        self.job_id = job_id
        self.authorization = authorization
        self.user_id = user_id

    async def _request(self, method: str, path: str, *, pinned: list[dict] | None = None, **kwargs):
        if not self._permitted(method, path, kwargs):
            logger.warning("Career tool rejected user=%s job=%s", self.user_id, self.job_id)
            raise CareerToolError("当前对话不支持该项求职操作")
        try:
            if settings.career_mysql_host and self.user_id is not None:
                async with career_transaction() as connection:
                    records = CareerRecords(connection, str(self.user_id))
                    return jsonable_encoder(await self._native_request(records, method, path, kwargs, pinned=pinned))
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
        except BizError as error:
            raise CareerToolError(error.message) from error
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise CareerToolError("暂时无法连接求职服务，请稍后重试。") from error

    def _permitted(self, method: str, path: str, payload: dict) -> bool:
        job = str(self.job_id)
        if method == "GET":
            if path in {f"/api/career/jobs/{job}", f"/api/career/jobs/{job}/learning-signals", "/api/career/experiences"}:
                return not payload
            if path == "/api/career/tasks":
                return payload == {"params": {"jobId": job, "kind": "TRAINING", "page": 1}}
            # The task handler checks ownership and the native handler checks the task's job.
            return not payload and bool(re.fullmatch(r"/api/career/tasks/[0-9a-f-]{36}/training-progress", path))
        allowed = {
            "/api/career/tasks/training", "/api/career/interviews", "/api/career/applications", "/api/career/resumes",
        }
        data = payload.get("json")
        return method == "POST" and path in allowed and payload.keys() == {"json"} \
            and isinstance(data, dict) and data.get("jobId") == job

    async def _native_request(
        self, records: CareerRecords, method: str, path: str, payload: dict, *, pinned: list[dict] | None = None,
    ):
        job = str(self.job_id)
        owned_job = await records.jobs().get(job)
        queue = CareerQueue(records.db)
        if method == "GET":
            if path == f"/api/career/jobs/{job}":
                return owned_job
            if path == f"/api/career/jobs/{job}/learning-signals":
                from app.controllers.career_learning_controller import learning_signals

                return (await learning_signals(self.job_id, records))["data"]
            if path == "/api/career/experiences":
                return await records.experiences().all()
            if path == "/api/career/tasks":
                return await queue.list(records.user, "TRAINING", job, None, 1)
            if path.endswith("/training-progress"):
                task = await queue.owned(records.user, path.split("/")[-2])
                if task["job_id"] != job:
                    raise CareerToolError("任务不属于当前岗位")
                return await CareerTraining(records).progress(task["id"])
        if method == "POST":
            data = payload["json"]
            if path == "/api/career/tasks/training":
                from app.controllers.career_task_controller import TrainingRequest, submit

                return (await submit("TRAINING", TrainingRequest.model_validate(data), records, pinned=pinned))["data"]
            if path == "/api/career/interviews":
                return await CareerInterviews(records).start(data["requestId"], job, data["mode"], data["count"])
            if path == "/api/career/applications":
                return await CareerApplications(records).create(job, None, "")
            if path == "/api/career/resumes":
                return await CareerResumes(records).create(data["requestId"], job, data["experienceIds"])
        raise CareerToolError("当前对话不支持该项求职操作")

    async def create_plan(self, request_id: uuid.UUID, *, pinned: list[dict] | None = None) -> str:
        data = await self._request("POST", "/api/career/tasks/training",
                                   pinned=pinned, json={"jobId": str(self.job_id), "requestId": str(request_id)})
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
        elif action == "CREATE_RESUME":
            experiences = await self._request("GET", "/api/career/experiences")
            confirmed = [item["id"] for item in experiences if item.get("confirmed")][:12]
            if not confirmed:
                raise CareerToolError("请先在简历制作中确认至少一条真实经历，再生成岗位简历。")
            data = await self._request("POST", "/api/career/resumes", json={
                **job, "requestId": str(request_id), "experienceIds": confirmed,
            })
        else:
            raise CareerToolError("当前对话不支持该项求职操作")
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
