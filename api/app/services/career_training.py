"""Training workflow snapshots and source-of-truth question references."""

import json
import re

from fastapi.encoders import jsonable_encoder
from sqlalchemy import bindparam, text

from app.core.exceptions import BizError
from app.services.career_practice import CareerPractice
from app.services.career_question_catalog import order_questions, question_key
from app.services.career_queue import CareerQueue, conflict
from app.services.career_records import CareerRecords
from app.services.career_training_harness import learn_from_attempts, learning_candidates

OPEN_QUESTION = re.compile(r"^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})-([0-4])$")


class CareerTraining:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.queue = CareerQueue(records.db)
        self.practice = CareerPractice(records)
        self.user = records.user

    async def preparation_ids(self, job_id: str, *, limit: int = 4) -> list[str]:
        result = await self.records.db.execute(text("""
            SELECT id FROM career_task WHERE user_id = :user AND job_id = :job
                AND kind = 'PREPARATION' AND status = 'SUCCEEDED'
                AND JSON_LENGTH(result_json, '$.openQuestions') > 0
            ORDER BY created_at DESC, id DESC LIMIT :limit
        """), {"user": self.user, "job": job_id, "limit": limit})
        return list(result.scalars())

    async def _preparation(self, job_id: str, task_id: str) -> list[dict]:
        row = await self.queue.owned(self.user, task_id)
        if row["kind"] != "PREPARATION" or row["job_id"] != job_id or row["status"] != "SUCCEEDED":
            raise BizError("该岗位的模拟题不存在", code=404, status_code=404)
        return (row["result_json"] or {}).get("openQuestions", [])

    async def open_question(self, job: str, question_id: str, version: int) -> dict:
        match = OPEN_QUESTION.fullmatch(question_id)
        if match and version == 1:
            questions = await self._preparation(job, match[1])
            index = int(match[2])
            if index < len(questions):
                return {"gradingVersion": 1, "kind": "OPEN", **questions[index]}
        raise BizError("岗位模拟题不存在", code=404, status_code=404)

    async def apply_training_snapshot(self, job_id: str, request: dict, context: dict) -> None:
        facts = [fact for fact in await self.records.experiences().all() if fact["confirmed"]]
        context["experiences"] = [
            {"id": fact["id"], "title": fact["title"], "description": fact["description"][:1800]}
            for fact in facts[:10]
        ]
        previous_id, review_id = request.get("previousPlanId"), request.get("reviewTaskId")
        if previous_id or review_id:
            if not previous_id or not review_id:
                raise BizError("请选择原计划和复盘记录", code=400)
            previous = await self.queue.owned(self.user, previous_id)
            review = await self.queue.owned(self.user, review_id)
            if (previous["kind"], review["kind"]) != ("TRAINING", "REVIEW") or any(
                row["status"] != "SUCCEEDED" or row["job_id"] != job_id for row in (previous, review)
            ) or review["request_json"].get("planId") != previous_id:
                raise conflict("请选择本岗位原计划对应的已完成复盘")
            context["plan"] = previous["result_json"]
            context["revisionReview"] = review["result_json"]["feedback"][:2000]
        feedback = await self.interview_feedback(job_id)
        if feedback:
            context["interviewFeedback"] = feedback
        role, preparation, preferred = (request.get(key) for key in ("role", "preparationId", "preferredQuestion"))
        if role is not None:
            context["role"] = role
        if not preparation and not role and not preferred:
            preparations = await self.preparation_ids(job_id, limit=1)
            if preparations:
                preparation = preparations[0]
        if preparation:
            await self._preparation(job_id, preparation)
            context["preparationId"] = preparation
            if preferred:
                match = OPEN_QUESTION.fullmatch(preferred)
                if match is None or match[1] != preparation:
                    raise BizError("指定题目不属于所选模拟题批次", code=400)
                await self.open_question(job_id, preferred, 1)
                context["preferredQuestion"] = preferred
        elif preferred:
            raise BizError("请指定模拟题批次", code=400)
        elif role is None and not await self.practice.matching_questions(context["job"]):
            raise conflict("请先在面经与题库生成该岗位的模拟题")
        learning = learn_from_attempts(await self.practice.training_attempts(job_id), context["job"])
        if learning:
            context["practiceLearning"] = learning

    async def catalog(self, row: dict) -> list[dict]:
        context = row["context_json"]
        job = context["job"]
        role = context.get("role")
        public = await self.practice.matching_questions(job, role)
        items = []
        preparation = context.get("preparationId") or row["request_json"].get("preparationId")
        if preparation:
            questions = await self._preparation(row["job_id"], preparation)
            items.extend({
                "id": f"{preparation}-{index}", "version": 1, "kind": "OPEN",
                "sourceName": "AI 模拟题", "topic": question["topic"], "prompt": question["prompt"],
            } for index, question in enumerate(questions))
        eligible = [*items, *public]
        learning = context.get("practiceLearning")
        if learning and public:
            completed = await self.practice.plan_attempts(
                [question_key(question) for question in public], row["job_id"], "role" in context, feedback=False,
            )
            completed_keys = {question_key(question) for question in completed}
            eligible = [{**question, "practiceCompleted": True} if question_key(question) in completed_keys else question
                        for question in eligible]
        targets = learning_candidates(eligible, learning)
        catalog = order_questions(eligible, job, context.get("preferredQuestion"), targets)[:30]
        if not catalog:
            raise conflict("当前岗位方向暂无训练题目")
        return jsonable_encoder(catalog)

    async def _open_attempts(self, job: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        result = await self.records.db.execute(text("""
            SELECT request_json->>'$.questionId' AS questionId,
                context_json->>'$.question.prompt' AS prompt,
                context_json->>'$.answer' AS answer, result_json->>'$.feedback' AS feedback
            FROM career_task WHERE user_id = :user AND job_id = :job
                AND kind = 'INTERVIEW' AND status = 'SUCCEEDED' AND request_json->>'$.questionId' IN :ids
            ORDER BY created_at DESC LIMIT 20
        """).bindparams(bindparam("ids", expanding=True)), {"user": self.user, "job": job, "ids": ids})
        return [dict(row) for row in result.mappings()]

    async def interview_feedback(self, job: str) -> list[dict]:
        result = await self.records.db.execute(text("""
            SELECT id, state_json FROM career_mock_interview
            WHERE user_id = :user AND job_id = :job AND state_json->>'$.status' = 'FINISHED'
            ORDER BY created_at DESC, id DESC LIMIT 5
        """), {"user": self.user, "job": job})
        return interview_feedback_from_rows(result.mappings())

    async def _plan(self, task_id: str) -> dict:
        row = await self.queue.owned(self.user, task_id)
        if row["kind"] != "TRAINING" or row["status"] != "SUCCEEDED":
            raise conflict("训练计划尚未生成")
        return row

    async def progress(self, task_id: str) -> list[dict]:
        row = await self._plan(task_id)
        questions = (row["result_json"] or {}).get("questions", [])
        objective = [(q["id"], q["version"]) for q in questions if q.get("kind") != "OPEN"]
        open_refs = {(q["id"], q["version"]) for q in questions if q.get("kind") == "OPEN"}
        job = row["job_id"]
        completed = await self.practice.plan_attempts(
            objective, job, "role" in row["context_json"], feedback=False,
        )
        attempts = await self._open_attempts(job, [qid for qid, version in open_refs if version == 1])
        keys = {(q["id"], q["version"]) for q in completed}
        keys.update((q["questionId"], 1) for q in attempts)
        if open_refs:
            sql = text("""
                SELECT DISTINCT q.question_id, q.question_version FROM career_mock_interview s
                JOIN JSON_TABLE(s.state_json, '$.rounds[*]' COLUMNS (
                    question_id VARCHAR(80) PATH '$.question.id',
                    question_version INT PATH '$.question.version',
                    evaluated INT PATH '$.main.evaluation.accuracy'
                )) q
                WHERE s.user_id = :user AND s.job_id = :job
                    AND s.state_json->>'$.status' = 'FINISHED' AND q.evaluated IS NOT NULL
                    AND (q.question_id, q.question_version) IN :refs
            """).bindparams(bindparam("refs", expanding=True))
            rows = await self.records.db.execute(sql, {"user": self.user, "job": job, "refs": list(open_refs)})
            keys.update(tuple(item) for item in rows)
        return [{"id": q["id"], "version": q["version"]} for q in questions if (q["id"], q["version"]) in keys]

    async def review_snapshot(self, plan_id: str) -> tuple[str, dict]:
        row = await self._plan(plan_id)
        context = row["context_json"]
        questions = (row["result_json"] or {}).get("questions", [])
        objective = [(q["id"], q["version"]) for q in questions if q.get("kind") != "OPEN"]
        open_ids = [q["id"] for q in questions if q.get("kind") == "OPEN"]
        job = row["job_id"]
        feedback = await self.practice.plan_attempts(objective, job, "role" in context, feedback=True)
        feedback.extend(
            {"question": item["prompt"], "answer": item["answer"], "feedback": item["feedback"]}
            for item in await self._open_attempts(job, open_ids)
        )
        interview = await self.interview_feedback(job)
        if not feedback and not interview:
            raise conflict("请先完成计划练习或本岗位的模拟面试")
        snapshot = {"job": context["job"], "plan": row["result_json"], "feedback": jsonable_encoder(feedback)}
        if interview:
            snapshot["interviewFeedback"] = interview
        return job, snapshot


def interview_feedback_from_rows(rows) -> list[dict]:
    feedback = []
    for row in rows:
        for turn in json.loads(row["state_json"])["rounds"]:
            main = turn.get("main") or {}
            evaluation = main.get("evaluation")
            if not evaluation:
                continue
            question = turn["question"]
            extra = (turn.get("extra") or {}).get("evaluation") or {}
            feedback.append({
                "sessionId": row["id"], "topic": question["topic"], "question": question["prompt"],
                "questionId": question["id"], "version": question["version"], "answer": main["answer"][:600],
                "feedback": evaluation["feedback"],
                "scores": [evaluation[k] for k in ("accuracy", "evidence", "structure")],
                "followUpFeedback": extra.get("feedback", ""),
            })
    return feedback[:8]
