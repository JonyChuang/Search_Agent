"""Mock interview sessions with ordered, recoverable scoring and follow-up turns."""

import json
import random
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.exceptions import BizError
from app.services.career_interview_templates import TEMPLATES
from app.services.career_queue import CareerQueue, conflict
from app.services.career_records import CareerRecords
from app.services.career_training import CareerTraining

FOLLOW_UP_LIMIT = 2
ROLE_HINTS = {
    "backend": r"后端|服务端|\b(backend|java|mysql|spring)\b",
    "algorithm": r"算法|数据结构|\balgorithm\b",
    "llm": r"大模型|人工智能|智能体|\b(agent|rag|llm|nlp)\b",
}
BUILTIN = "内置模拟题库"


def normalize(prompt: str) -> str:
    return "".join(
        char for char in prompt.lower() if not char.isspace() and unicodedata.category(char)[0] not in "PZ"
    )


def elapsed(state: dict, now: datetime) -> int:
    active = state["activeSince"]
    return state["elapsedSeconds"] + (max(0, int((now - datetime.fromisoformat(active)).total_seconds())) if active else 0)


def change_status(state: dict, status: str) -> None:
    now = datetime.now(timezone.utc)
    state.update(
        status=status, elapsedSeconds=elapsed(state, now), revision=state["revision"] + 1,
        activeSince=now.isoformat() if status == "ACTIVE" else None,
    )


def summary(state: dict) -> dict:
    job, rounds = state["job"], state["rounds"]
    return {
        **{name: state[name] for name in ("id", "jobId", "mode", "status", "createdAt")},
        "job": f"{job['company']} · {job['title']}", "count": len(rounds),
        "answered": sum(bool(round_["main"]) for round_ in rounds),
        "followUps": sum(bool(round_["extra"]) for round_ in rounds),
        "elapsedSeconds": elapsed(state, datetime.now(timezone.utc)),
    }


def apply_evaluation(state: dict, result: dict | None, failed: bool) -> None:
    index = state["index"]
    round_ = state["rounds"][index]
    is_follow_up = round_["followUp"] is not None
    evaluation = {**result, "followUp": None} if result else None
    turn = round_["extra" if is_follow_up else "main"]
    turn.update(evaluation=evaluation, evaluationUnavailable=failed)
    if not is_follow_up and result and result.get("followUp"):
        candidate = result["followUp"].strip()
        prompts = {
            normalize(prompt)
            for item in state["rounds"] for prompt in (item["question"]["prompt"], item["followUp"])
            if prompt
        }
        used = sum(bool(item["followUp"]) for item in state["rounds"])
        if used < FOLLOW_UP_LIMIT and normalize(candidate) and normalize(candidate) not in prompts:
            round_["followUp"] = candidate
    if is_follow_up or not round_["followUp"]:
        state["index"] = index + 1
    state.update(pending=None, revision=state["revision"] + 1)
    if state["index"] == len(state["rounds"]):
        change_status(state, "FINISHED")


class CareerInterviews:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.db = records.db
        self.user = records.user
        self.queue = CareerQueue(self.db)

    async def find(self, session_id: str, *, lock=False) -> dict | None:
        sql = "SELECT state_json FROM career_mock_interview WHERE user_id = :user AND id = :id"
        row = (await self.db.execute(text(sql + (" FOR UPDATE" if lock else "")),
                                    {"user": self.user, "id": session_id})).scalar_one_or_none()
        return json.loads(row) if row is not None else None

    async def owned(self, session_id: str, *, lock=False) -> dict:
        state = await self.find(session_id, lock=lock)
        if state is None:
            raise BizError("面试记录不存在", code=404, status_code=404)
        return state

    async def save(self, state: dict) -> None:
        await self.db.execute(text("""
            UPDATE career_mock_interview SET state_json = :state WHERE user_id = :user AND id = :id
        """), {"user": self.user, "id": state["id"], "state": json.dumps(state, ensure_ascii=False)})

    async def sessions(self, job: str | None, limit: int, offset=0) -> list[dict]:
        rows = await self.db.execute(text("""
            SELECT state_json FROM career_mock_interview WHERE user_id = :user AND (:job IS NULL OR job_id = :job)
            ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset
        """), {"user": self.user, "job": job, "limit": limit, "offset": offset})
        return [json.loads(row) for row in rows.scalars()]

    async def list_page(self, page: int) -> dict:
        sessions = await self.sessions(None, 21, (page - 1) * 20)
        return {"items": [summary(state) for state in sessions[:20]], "hasMore": len(sessions) > 20}

    async def start(self, request_id: str, job_id: str, mode: str, count: int) -> dict:
        state = await self.find(request_id)
        if state is None:
            job = await self.records.jobs().get(job_id)
            recent = {
                round_["question"]["id"]
                for session in await self.sessions(job_id, 5) for round_ in session["rounds"]
                if round_["main"]
            }
            questions = await self.draw(job, count, recent)
            now = datetime.now(timezone.utc).isoformat()
            state = {
                "id": request_id, "jobId": job_id, "mode": mode, "status": "ACTIVE", "createdAt": now,
                "activeSince": now, "elapsedSeconds": 0, "revision": 0, "index": 0, "pending": None,
                "job": {"company": job["company"], "title": job["title"], "jd": job["description"][:6000],
                        "skills": job["skills"] or ""},
                "rounds": [{"question": q, "main": None, "followUp": None, "extra": None} for q in questions],
            }
            await self.db.execute(text("""
                INSERT INTO career_mock_interview (id, user_id, job_id, state_json)
                VALUES (:id, :user, :job, :state) ON DUPLICATE KEY UPDATE id = id
            """), {"id": request_id, "user": self.user, "job": job_id, "state": json.dumps(state, ensure_ascii=False)})
            state = await self.owned(request_id)
        if (state["jobId"], state["mode"], len(state["rounds"])) != (job_id, mode, count):
            raise conflict("开始编号已用于另一场面试")
        return await self.view(state)

    async def draw(self, job: dict, count: int, recent: set[str]) -> list[dict]:
        training = CareerTraining(self.records)
        title = job["title"]
        core = []
        for task_id in await training.preparation_ids(job["id"], limit=4):
            for index, item in enumerate(await training._preparation(job["id"], task_id)):
                core.append({
                    "id": f"{task_id}-{index}", "version": 1, "gradingVersion": 1, "phase": "CORE",
                    "topic": item["topic"], "prompt": item["prompt"], "rubric": item["rubric"],
                    "sourceName": "岗位 AI 模拟题", "sourceUrl": None,
                })
        snapshot = {**job, "jd": job["description"]}
        topics = await training.practice.matching_questions(snapshot)
        direction = f"{title} {job['skills'] or ''}".lower()
        for role, pattern in ROLE_HINTS.items():
            if re.search(pattern, direction):
                topics += await training.practice.questions(role)
        for item in {q["id"]: q for q in topics}.values():
            core.append({
                "id": "topic-" + item["id"], "version": item["version"], "gradingVersion": 1, "phase": "CORE",
                "topic": item["topic"], "sourceName": item["sourceName"], "sourceUrl": item["sourceUrl"],
                "prompt": f"请用自己的话解释「{item['topic']}」涉及的核心原理。举例说明它怎样用在「{title}」的实际工作中，以及如何验证效果。",
                "rubric": ["原理描述准确", "举例与岗位职责相关", "说明验证方式或适用边界"],
            })
        asked = set()

        def select(phase: str, amount: int, extra=()) -> list[dict]:
            bank = [{
                "id": f"{phase.lower()}-{index}", "version": 1, "gradingVersion": 1, "phase": phase,
                "topic": topic, "prompt": prompt % title, "rubric": rubric, "sourceName": BUILTIN, "sourceUrl": None,
            } for index, (topic, prompt, *rubric) in enumerate(TEMPLATES[phase], 1)]
            bank.extend(extra)
            random.shuffle(bank)
            bank.sort(key=lambda item: (item["id"] in recent, item["sourceName"] == BUILTIN))
            chosen = []
            for item in bank:
                key = normalize(item["prompt"])
                if key not in asked:
                    asked.add(key)
                    chosen.append(item)
                if len(chosen) == amount:
                    break
            return chosen

        warmup = select("WARMUP", 1)
        scenarios = select("SCENARIO", 2 if count == 8 else 1)
        return [*warmup, *select("CORE", count - len(scenarios) - 1, core), *scenarios]

    async def answer(self, session_id: str, request_id: str, revision: int, value: str) -> dict:
        state = await self.owned(session_id, lock=True)
        for round_ in state["rounds"]:
            for turn in (round_["main"], round_["extra"]):
                if turn and turn["requestId"] == request_id:
                    if turn["answer"] != value:
                        raise conflict("提交编号已用于另一条回答")
                    return await self.view(state)
        self.require_revision(state, revision)
        self.require_active(state)
        if state["pending"]:
            raise conflict("请等待当前回答处理完成")
        round_ = state["rounds"][state["index"]]
        is_follow_up = round_["followUp"] is not None
        max_reached = sum(bool(item["followUp"]) for item in state["rounds"]) >= FOLLOW_UP_LIMIT
        context = {"job": state["job"], "question": round_["question"], "answer": value,
                   "allowFollowUp": not is_follow_up and not max_reached}
        if is_follow_up:
            context.update(followUp=round_["followUp"], mainAnswer=round_["main"]["answer"][:1600])
        task = await self.queue.insert(
            self.user, "INTERVIEW_TURN", state["jobId"], {"sessionId": session_id, "revision": revision},
            context, request_id=request_id,
        )
        round_["extra" if is_follow_up else "main"] = {
            "requestId": request_id, "answer": value, "evaluation": None, "evaluationUnavailable": False,
        }
        state.update(pending=task["id"], revision=revision + 1)
        await self.save(state)
        return await self.view(state)

    async def decision(self, session_id: str, task_id: str, *, retry=False, skip_failed=False) -> dict:
        state = await self.owned(session_id, lock=True)
        if state["pending"] == task_id:
            self.require_active(state)
            task = await self.queue.owned(self.user, task_id, public=False)
            failed = task["status"] == "FAILED"
            if retry and failed:
                await self.queue.retry(self.user, task_id, public=False)
            if not retry and (task["status"] == "SUCCEEDED" or failed and skip_failed):
                apply_evaluation(state, task["result_json"], failed)
                await self.save(state)
        return await self.view(state)

    async def status(self, session_id: str, revision: int, target: str) -> dict:
        state = await self.owned(session_id, lock=True)
        if state["status"] != target:
            self.require_revision(state, revision)
            if state["status"] == "FINISHED":
                raise conflict("这场面试已结束")
            if target == "FINISHED" and state["pending"]:
                raise conflict("请先完成当前回答的处理")
            change_status(state, target)
            await self.save(state)
        return await self.view(state)

    @staticmethod
    def require_revision(state: dict, revision: int) -> None:
        if state["revision"] != revision:
            raise conflict("面试进度已更新，请刷新后继续")

    @staticmethod
    def require_active(state: dict) -> None:
        if state["status"] != "ACTIVE":
            raise conflict("请先继续面试")

    async def view(self, state: dict) -> dict:
        finished = state["status"] == "FINISHED"
        index, rounds = state["index"], state["rounds"]
        transcript, review = [], []
        for round_ in rounds:
            if not round_["main"]:
                continue
            transcript.append({"prompt": round_["question"]["prompt"], "answer": round_["main"]["answer"], "followUp": False})
            if round_["extra"]:
                transcript.append({"prompt": round_["followUp"], "answer": round_["extra"]["answer"], "followUp": True})
            if finished:
                review.append(round_)
        phases = [{
            "phase": phase, "total": sum(item["question"]["phase"] == phase for item in rounds),
            "completed": sum(item["question"]["phase"] == phase for item in rounds[:index]),
        } for phase in TEMPLATES]
        current = None
        if not finished:
            round_ = rounds[index]
            current = {
                "number": index + 1, "phase": round_["question"]["phase"],
                "prompt": round_["followUp"] or round_["question"]["prompt"],
                "followUp": round_["followUp"] is not None,
            }
        pending = None
        if state["pending"]:
            task = await self.queue.owned(self.user, state["pending"], public=False)
            pending = {"id": task["id"], "status": task["status"], "error": task["error_message"],
                       "generation": task["generation"]}
        return {"summary": summary(state), "revision": state["revision"], "current": current,
                "phases": phases, "transcript": transcript, "pending": pending, "review": review}
