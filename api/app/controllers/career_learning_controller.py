"""Saved job learning material, provenance and task metrics."""

import json
import posixpath
import re
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.services.career_queue import CareerQueue
from app.services.career_training import OPEN_QUESTION, CareerTraining

router = APIRouter(prefix="/career", tags=["career"], route_class=CareerRoute)
NOTE_COLUMNS = """
    source_key AS sourceKey, title, summary, source_url AS sourceUrl, document_id AS documentId,
    document_title AS documentTitle, document_revision AS documentRevision, collected_at AS collectedAt
"""


class NoteInput(BaseModel):
    taskId: UUID
    index: int = Field(ge=0, le=9)


def missing():
    return BizError("找不到所选的备考内容", code=404, status_code=404)


def normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if not parsed.hostname or parsed.username is not None or parsed.scheme not in {"http", "https"}:
            return None
        port = parsed.port
    except ValueError:
        return None
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
        hostname = f"{hostname}:{port}"
    path = posixpath.normpath(parsed.path) if parsed.path else "/"
    if parsed.path.endswith("/") and not path.endswith("/"):
        path += "/"
    query = "&".join(part for part in parsed.query.rstrip("&").split("&") if not part.lower().startswith("utm_"))
    return urlunsplit((parsed.scheme, hostname, path, query, ""))


def note_from_task(task: dict, index: int) -> dict:
    result = task["result_json"] or {}
    base = {"documentId": None, "documentTitle": None, "documentRevision": None, "sourceUrl": None}
    try:
        if task["kind"] == "DISCOVERY":
            source = result["sources"][index]
            identity = normalize_url(source["url"])
            if identity is None:
                raise missing()
            collected = datetime.fromisoformat(result["searchedAt"]) if result.get("searchedAt") else task["updated_at"]
            base.update(title=source["title"], summary=source["snippet"], sourceUrl=source["url"])
        elif task["kind"] == "PREPARATION":
            note = result["notes"][index]
            reference = task["agent_context_json"]["references"][note["reference"] - 1]
            title, doc = note["title"], reference["id"]
            identity = doc + "\n" + re.sub(r"\s+", " ", title.strip()).lower()
            collected = task["updated_at"]
            base.update(title=title, summary=note["summary"], documentId=doc,
                        documentTitle=reference["title"], documentRevision=reference["revision"])
        else:
            raise missing()
    except (KeyError, TypeError, IndexError, ValueError):
        raise missing() from None
    if collected.tzinfo:
        collected = collected.astimezone(timezone.utc).replace(tzinfo=None)
    return dict(base, sourceKey=sha256(identity.encode()).hexdigest(), collectedAt=collected)


@router.get("/learning/jobs/{job_id}/questions")
async def questions(job_id: UUID, db: Records):
    await db.jobs().get(str(job_id))
    rows = await db.db.execute(text("""
        SELECT id, result_json, agent_context_json FROM career_task
        WHERE user_id = :user AND job_id = :job AND kind = 'PREPARATION' AND status = 'SUCCEEDED'
            AND JSON_LENGTH(result_json, '$.openQuestions') > 0
        ORDER BY created_at DESC, id DESC
    """), {"user": db.user, "job": str(job_id)})
    seen, result = set(), []
    for row in rows:
        context = json.loads(row.agent_context_json) if row.agent_context_json else {}
        for index, question in enumerate(json.loads(row.result_json)["openQuestions"]):
            key = re.sub(r"\s+", " ", question["prompt"].strip()).lower()
            if key in seen:
                continue
            seen.add(key)
            result.append({"id": f"{row.id}-{index}", "version": 1, "topic": question["topic"],
                           "prompt": question["prompt"], "references": context.get("references")})
    return success(result)


@router.get("/learning/jobs/{job_id}/questions/{question_id}")
async def question(job_id: UUID, question_id: str, db: Records):
    match = OPEN_QUESTION.fullmatch(question_id)
    if match is None:
        raise missing()
    source = await CareerTraining(db).open_question(str(job_id), question_id, 1)
    task = await CareerQueue(db.db).owned(db.user, match[1])
    return success({"id": question_id, "version": 1, "topic": source["topic"], "prompt": source["prompt"],
                    "references": (task["agent_context_json"] or {}).get("references")})


@router.get("/learning/jobs/{job_id}/notes")
async def notes(job_id: UUID, db: Records):
    await db.jobs().get(str(job_id))
    rows = await db.db.execute(text(f"""
        SELECT {NOTE_COLUMNS} FROM career_learning_note
        WHERE user_id = :user AND job_id = :job ORDER BY collected_at DESC, source_key
    """), {"user": db.user, "job": str(job_id)})
    return success([dict(row, collectedAt=row["collectedAt"].replace(tzinfo=timezone.utc)) for row in rows.mappings()])


@router.post("/learning/jobs/{job_id}/notes")
async def save_note(job_id: UUID, body: NoteInput, db: Records):
    await db.jobs().get(str(job_id), lock=True)
    task = await CareerQueue(db.db).owned(db.user, str(body.taskId))
    if task["job_id"] != str(job_id) or task["status"] != "SUCCEEDED":
        raise missing()
    note = note_from_task(task, body.index)
    await db.db.execute(text("""
        INSERT INTO career_learning_note (user_id, job_id, source_key, title, summary, source_url,
            document_id, document_title, document_revision, collected_at)
        VALUES (:user, :job, :sourceKey, :title, :summary, :sourceUrl,
            :documentId, :documentTitle, :documentRevision, :collectedAt) AS incoming
        ON DUPLICATE KEY UPDATE
            title = IF(collected_at <= incoming.collected_at, incoming.title, title),
            summary = IF(collected_at <= incoming.collected_at, incoming.summary, summary),
            source_url = IF(collected_at <= incoming.collected_at, incoming.source_url, source_url),
            document_title = IF(collected_at <= incoming.collected_at, incoming.document_title, document_title),
            document_revision = IF(collected_at <= incoming.collected_at, incoming.document_revision, document_revision),
            collected_at = GREATEST(collected_at, incoming.collected_at)
    """), {"user": db.user, "job": str(job_id), **note})
    return success(note["sourceKey"])


@router.get("/jobs/{job_id}/learning-signals")
async def learning_signals(job_id: UUID, db: Records):
    await db.jobs().get(str(job_id))
    bind = {"user": db.user, "job": str(job_id)}
    attempts = await db.db.execute(text("""
        SELECT a.request_id AS attemptId, a.question_id AS questionId, a.question_version AS questionVersion,
            a.correct, a.submitted_at AS submittedAt, q.topic
        FROM career_practice_attempt a JOIN career_question_version q
            ON q.id = a.question_id AND q.version = a.question_version
        WHERE a.user_id = :user AND a.job_id = :job ORDER BY a.sequence_id DESC LIMIT 12
    """), bind)
    interviews = await db.db.execute(text("""
        SELECT id, created_at AS createdAt, state_json->>'$.status' AS status FROM career_mock_interview
        WHERE user_id = :user AND job_id = :job ORDER BY created_at DESC LIMIT 5
    """), bind)
    return success({
        "objectiveAttempts": [dict(row, correct=bool(row["correct"]),
                                   submittedAt=row["submittedAt"].replace(tzinfo=timezone.utc))
                              for row in attempts.mappings()],
        "recentInterviews": [dict(row, createdAt=row["createdAt"].replace(tzinfo=timezone.utc))
                             for row in interviews.mappings()],
    })


@router.get("/task-metrics")
async def metrics(db: Records, jobId: UUID | None = None):
    if jobId is not None:
        await db.jobs().get(str(jobId))
    rows = await db.db.execute(text("""
        WITH steps AS (
            SELECT t.id, t.kind, t.status, t.result_json, e.task_id, e.step, e.outcome, e.elapsed_ms,
                e.input_tokens, e.output_tokens,
                ROW_NUMBER() OVER (PARTITION BY t.kind, t.status ORDER BY e.elapsed_ms DESC) AS reverse_rank,
                COUNT(e.task_id) OVER (PARTITION BY t.kind, t.status) AS measured
            FROM career_task t LEFT JOIN career_task_event e ON e.task_id = t.id
            WHERE t.user_id = :user AND (:job IS NULL OR t.job_id = :job)
                AND t.created_at >= CURRENT_TIMESTAMP - INTERVAL 30 DAY
        )
        SELECT t.kind, t.status, COUNT(DISTINCT t.id) AS taskCount, COUNT(t.task_id) AS recordedSteps,
            COALESCE(SUM(t.elapsed_ms), 0) AS stepMilliseconds, COUNT(t.input_tokens) AS measuredInputs,
            COALESCE(SUM(t.input_tokens), 0) AS inputTokens, COALESCE(SUM(t.output_tokens), 0) AS outputTokens,
            MAX(CASE WHEN t.measured > 0 AND t.reverse_rank = t.measured - CEIL(0.95 * t.measured) + 1
                     THEN t.elapsed_ms END) AS p95StepMilliseconds,
            COUNT(CASE WHEN t.outcome = 'failed' THEN 1 END) AS failedSteps,
            COUNT(DISTINCT CASE WHEN t.step IN ('resume_context', 'resume_catalog', 'resume_draft', 'lease_reclaimed')
                THEN t.id END) AS resumedTasks,
            COUNT(DISTINCT CASE WHEN JSON_SEARCH(t.result_json, 'one', 'SELECTED', NULL,
                    '$.learning.priorities[*].status') IS NOT NULL
                THEN t.id END) AS adaptedPlans
        FROM steps t
        GROUP BY t.kind, t.status ORDER BY t.kind, t.status
    """), {"user": db.user, "job": str(jobId) if jobId else None})
    return success([dict(row) for row in rows.mappings()])
