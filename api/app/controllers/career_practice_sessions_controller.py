"""Resumable ordered practice sessions."""

import json
from hashlib import md5
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.services.career_queue import CareerQueue, conflict
from app.services.career_training import CareerTraining

router = APIRouter(prefix="/career/practice/sessions", tags=["career"], route_class=CareerRoute)
SELECT = "SELECT id, job_id AS jobId, questions, position FROM career_practice_session WHERE user_id = :user"


class QuestionRef(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    version: int = Field(gt=0)
    type: Literal["SINGLE", "OPEN"]


class Create(BaseModel):
    requestId: UUID
    jobId: UUID | None = None
    questions: list[QuestionRef] = Field(min_length=1, max_length=10)


class Advance(BaseModel):
    position: int = Field(ge=0)


async def lookup(db: Records, session_id: str, *, lock=False) -> dict:
    row = (await db.db.execute(text(SELECT + " AND id = :id" + (" FOR UPDATE" if lock else "")),
                               {"user": db.user, "id": session_id})).mappings().one_or_none()
    if row is None:
        raise BizError("练习记录不存在", code=404, status_code=404)
    return dict(row, questions=json.loads(row["questions"]))


async def view(db: Records, row: dict) -> dict:
    current = {"id": row["id"], "jobId": row["jobId"], "position": row["position"],
               "total": len(row["questions"]), "current": None, "answerRequestId": None, "attempt": None, "taskId": None}
    if row["position"] == current["total"]:
        return current
    item = row["questions"][row["position"]]
    seed = f"{row['id']}:{row['position']}".encode()
    request_id = str(UUID(bytes=md5(seed, usedforsecurity=False).digest(), version=3))
    current.update(current=item, answerRequestId=request_id)
    if item["type"] == "SINGLE":
        attempt = await CareerTraining(db).practice.attempt_for_request(request_id)
        if attempt and (attempt["jobId"], attempt["questionId"], attempt["questionVersion"]) == (
            row["jobId"], item["id"], item["version"],
        ):
            current["attempt"] = attempt
    else:
        task = await CareerQueue(db.db).lookup_request(db.user, request_id)
        if task and task["kind"] == "INTERVIEW" and task["job_id"] == row["jobId"] and (
            task["request_json"].get("questionId"), task["request_json"].get("questionVersion")
        ) == (item["id"], item["version"]):
            current["taskId"] = task["id"]
    return current


@router.post("")
async def create(body: Create, db: Records):
    job_id = str(body.jobId) if body.jobId else None
    if job_id:
        await db.jobs().get(job_id)
    refs = [(item.id, item.version, item.type) for item in body.questions]
    if len(set(refs)) != len(refs):
        raise BizError("练习题目不能重复", code=400)
    training = CareerTraining(db)
    questions = []
    for item in body.questions:
        if item.type == "OPEN":
            if job_id is None:
                raise BizError("开放题练习需要目标岗位", code=400)
            question = await training.open_question(job_id, item.id, item.version)
        else:
            question = await training.practice.question(item.id, item.version)
        questions.append(dict(item.model_dump(), topic=question["topic"], prompt=question["prompt"]))
    await db.db.execute(text("""
        INSERT INTO career_practice_session (id, user_id, job_id, questions)
        VALUES (:id, :user, :job, :questions) ON DUPLICATE KEY UPDATE id = id
    """), {"id": str(body.requestId), "user": db.user, "job": job_id,
           "questions": json.dumps(questions, ensure_ascii=False)})
    row = await lookup(db, str(body.requestId))
    if row["jobId"] != job_id or row["questions"] != questions:
        raise conflict("此编号已用于另一组练习")
    return success(await view(db, row))


@router.get("")
async def list_unfinished(db: Records, jobId: UUID | None = None):
    rows = await db.db.execute(text(SELECT + """
        AND job_id <=> :job AND finished_at IS NULL ORDER BY updated_at DESC, id DESC LIMIT 10
    """), {"user": db.user, "job": str(jobId) if jobId else None})
    items = []
    for row in rows.mappings():
        questions = json.loads(row["questions"])
        items.append({"id": row["id"], "position": row["position"], "total": len(questions),
                      "prompt": questions[row["position"]]["prompt"]})
    return success(items)


@router.get("/{session_id}")
async def get(session_id: UUID, db: Records):
    return success(await view(db, await lookup(db, str(session_id))))


@router.post("/{session_id}/advance")
async def advance(session_id: UUID, body: Advance, db: Records):
    row = await lookup(db, str(session_id), lock=True)
    if row["position"] > body.position:
        return success(await view(db, row))
    if row["position"] != body.position or row["position"] == len(row["questions"]):
        raise conflict("练习进度已更新")
    current = await view(db, row)
    if not current["attempt"] and not current["taskId"]:
        raise conflict("请先提交当前问题的回答")
    row["position"] += 1
    await db.db.execute(text("""
        UPDATE career_practice_session SET position = :position, finished_at = IF(:finished, CURRENT_TIMESTAMP(6), NULL)
        WHERE id = :id AND user_id = :user
    """), {"position": row["position"], "finished": row["position"] == len(row["questions"]),
           "id": str(session_id), "user": db.user})
    return success(await view(db, row))
