"""Versioned SQL and coding submissions executed only by the configured sandbox."""

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import settings
from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.db.career import career_transaction
from app.services.career_queue import conflict

router = APIRouter(prefix="/career/judge", tags=["career"], route_class=CareerRoute)
logger = logging.getLogger(__name__)
SELECT = """
    SELECT id, job_id AS jobId, problem_id AS problemId, version, status, passed, created_at AS createdAt
    FROM career_judge_submission WHERE user_id = :user
"""
SQL_RUNNER = """
import base64, json, sqlite3, sys
query = base64.b64decode(%r).decode("utf-8")
connection = sqlite3.connect(":memory:")
connection.executescript(sys.stdin.read())
read_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
functions = {"count", "sum", "min", "max", "avg", "coalesce", "lower", "upper", "length", "round", "abs"}
def authorize(action, name, detail, database, caller):
    if action in read_actions or (action == sqlite3.SQLITE_FUNCTION and (detail or "").lower() in functions):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
connection.set_authorizer(authorize)
rows = connection.execute(query).fetchmany(512)
if len(rows) == 512:
    sys.exit(2)
print(json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
"""
TOKENS = re.compile(r"^[A-Za-z0-9-]{1,128}$")


class Submission(BaseModel):
    requestId: UUID
    jobId: UUID | None = None
    problemId: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    version: int = Field(gt=0)
    source: str = Field(max_length=16000)


def configured_url() -> str | None:
    value = settings.career_judge0_url.strip()
    if not value:
        return None
    address = urlsplit(value)
    if address.scheme not in {"http", "https"} or not address.hostname or address.username is not None \
            or address.query or address.fragment:
        raise RuntimeError("Invalid CAREER_JUDGE0_URL")
    return value.rstrip("/")


def _present(row) -> dict:
    return dict(row, createdAt=row["createdAt"].replace(tzinfo=timezone.utc))


async def find(db: Records, submission_id: str) -> dict | None:
    query = SELECT.replace("created_at AS createdAt", "created_at AS createdAt, submission")
    row = (await db.db.execute(text(query + " AND id = :id"),
                               {"id": submission_id, "user": db.user})).mappings().one_or_none()
    return _present(row) if row is not None else None


async def owned(db: Records, submission_id: str) -> dict:
    data = await find(db, submission_id)
    if data is None:
        raise BizError("判题记录不存在", code=404, status_code=404)
    return data


@router.get("/problems")
async def problems(db: Records):
    rows = await db.db.execute(text("""
        SELECT p.id, p.version, p.kind, p.topic, p.prompt, p.starter
        FROM career_judge_problem p WHERE NOT EXISTS (
            SELECT 1 FROM career_judge_problem n WHERE n.id = p.id AND n.version > p.version
        ) ORDER BY p.kind, p.id
    """))
    return success({"available": bool(configured_url()), "problems": [dict(row) for row in rows.mappings()]})


@router.get("/submissions")
async def history(db: Records, jobId: UUID | None = None):
    rows = await db.db.execute(text(SELECT + """
        AND (:job IS NULL OR job_id = :job) ORDER BY created_at DESC, id DESC LIMIT 30
    """), {"user": db.user, "job": str(jobId) if jobId else None})
    return success([_present(row) for row in rows.mappings()])


@router.get("/submissions/{submission_id}")
async def get_submission(submission_id: UUID, db: Records):
    data = await owned(db, str(submission_id))
    data.pop("submission")
    return success(data)


@router.post("/submissions")
async def submit(body: Submission, db: Records):
    if not body.source.strip():
        raise BizError("请填写作答内容", code=400)
    if configured_url() is None:
        raise BizError("判题服务尚未配置", code=503, status_code=503)
    job = str(body.jobId) if body.jobId else None
    if job:
        await db.jobs().get(job)
    submission_id = str(body.requestId)
    existing = await find(db, submission_id)
    if existing is None:
        await db.db.execute(text("SELECT id FROM career_task_scheduler WHERE id = 1 FOR UPDATE"))
        existing = await find(db, submission_id)
    if existing is None:
        count = (await db.db.execute(text("""
            SELECT COUNT(*) FROM career_judge_submission WHERE user_id = :user
                AND created_at > CURRENT_TIMESTAMP(6) - INTERVAL 1 HOUR
        """), {"user": db.user})).scalar_one()
        if count >= 20:
            raise BizError("本小时提交次数已达上限", code=429, status_code=429)
        params = {"problem": body.problemId, "version": body.version}
        question = (await db.db.execute(text("""
            SELECT id FROM career_judge_problem WHERE id = :problem AND version = :version
        """), params)).scalar_one_or_none()
        if question is None:
            raise BizError("该题目版本不存在", code=404, status_code=404)
        await db.db.execute(text("""
            INSERT INTO career_judge_submission (id, user_id, job_id, problem_id, version, submission)
            VALUES (:id, :user, :job, :problem, :version, :source) ON DUPLICATE KEY UPDATE id = id
        """), dict(params, id=submission_id, user=db.user, job=job, source=body.source))
        existing = await owned(db, submission_id)
    if (existing["jobId"], existing["problemId"], existing["version"], existing.pop("submission")) != (
        job, body.problemId, body.version, body.source,
    ):
        raise conflict("提交编号已用于另一次作答")
    return success(existing)


@router.post("/submissions/{submission_id}/retry")
async def retry(submission_id: UUID, db: Records):
    await owned(db, str(submission_id))
    await db.db.execute(text("""
        UPDATE career_judge_submission SET status = 'QUEUED', sandbox_token = NULL, expires_at = NULL,
            lease = NULL, ready_at = CURRENT_TIMESTAMP(6)
        WHERE user_id = :user AND id = :id AND status = 'SYSTEM_ERROR'
    """), {"user": db.user, "id": str(submission_id)})
    return await get_submission(submission_id, db)


def _encode(text_value: str) -> str:
    return base64.b64encode(text_value.encode()).decode()


async def _start_sandbox(client: httpx.AsyncClient, kind: str, source: str, case: dict) -> str:
    response = await client.get("config_info")
    configuration = response.raise_for_status().json()
    if configuration.get("enable_network") is not False or configuration.get("allow_enable_network") is not False:
        raise RuntimeError("Judge0 must disallow networking")
    code = SQL_RUNNER % _encode(source) if kind == "SQL" else source
    reply = await client.post("submissions", params={"base64_encoded": "true", "wait": "false"}, json={
        "language_id": settings.career_judge0_python_id, "source_code": _encode(code),
        "stdin": _encode(case["stdin"]), "expected_output": _encode(case["expected"]),
        "cpu_time_limit": 2, "wall_time_limit": 5, "memory_limit": 65536, "max_file_size": 128,
        "max_processes_and_or_threads": 8, "enable_network": False,
    })
    token = reply.raise_for_status().json()["token"]
    if not TOKENS.fullmatch(token):
        raise RuntimeError("Invalid sandbox ticket")
    return token


async def _sandbox_status(client: httpx.AsyncClient, token: str) -> str:
    if not TOKENS.fullmatch(token):
        raise RuntimeError("Invalid sandbox ticket")
    reply = await client.get(f"submissions/{token}", params={"fields": "status", "base64_encoded": "true"})
    status = reply.raise_for_status().json()["status"]["id"]
    if 7 <= status <= 12:
        return "RUNTIME_ERROR"
    return {1: "RUNNING", 2: "RUNNING", 3: "ACCEPTED", 4: "WRONG_ANSWER",
            5: "TIME_LIMIT", 6: "COMPILE_ERROR"}.get(status, "SYSTEM_ERROR")


async def _claim():
    lease = str(uuid4())
    async with career_transaction() as connection:
        changed = await connection.execute(text("""
            UPDATE career_judge_submission SET lease = :lease, ready_at = CURRENT_TIMESTAMP(6) + INTERVAL 20 SECOND,
                status = 'RUNNING' WHERE status IN ('QUEUED', 'RUNNING') AND ready_at <= CURRENT_TIMESTAMP(6)
            ORDER BY ready_at, created_at LIMIT 1
        """), {"lease": lease})
        if changed.rowcount != 1:
            return None
        row = (await connection.execute(text("""
            SELECT s.id, s.submission, s.sandbox_token, s.expires_at, s.passed, s.lease, p.kind, p.tests
            FROM career_judge_submission s JOIN career_judge_problem p ON p.id = s.problem_id AND p.version = s.version
            WHERE s.lease = :lease
        """), {"lease": lease})).mappings().one()
        return dict(row)


async def _execute_sandbox(client: httpx.AsyncClient, work: dict) -> None:
    passed, retain = work["passed"], False
    identity = {"id": work["id"], "lease": work["lease"]}
    try:
        tests = json.loads(work["tests"])
        if work["sandbox_token"] is None:
            token = await _start_sandbox(client, work["kind"], work["submission"], tests[passed])
            async with career_transaction() as db:
                await db.execute(text("""
                    UPDATE career_judge_submission SET sandbox_token = :token, lease = NULL,
                        expires_at = CURRENT_TIMESTAMP(6) + INTERVAL 90 SECOND, ready_at = CURRENT_TIMESTAMP(6)
                    WHERE id = :id AND lease = :lease AND ready_at > CURRENT_TIMESTAMP(6)
                """), dict(identity, token=token))
            return
        status = await _sandbox_status(client, work["sandbox_token"])
        if status == "ACCEPTED":
            passed += 1
            status = "ACCEPTED" if passed == len(tests) else "QUEUED"
        elif status == "RUNNING":
            retain = work["expires_at"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
            if not retain:
                status = "SYSTEM_ERROR"
    except Exception as error:
        logger.warning("Career judge %s failed: %s", work["id"], type(error).__name__)
        status = "SYSTEM_ERROR"
    async with career_transaction() as db:
        await db.execute(text("""
            UPDATE career_judge_submission SET status = :status, passed = :passed, lease = NULL,
                sandbox_token = IF(:retain, sandbox_token, NULL), expires_at = IF(:retain, expires_at, NULL),
                ready_at = CURRENT_TIMESTAMP(6)
            WHERE id = :id AND lease = :lease AND ready_at > CURRENT_TIMESTAMP(6)
        """), dict(identity, status=status, passed=passed, retain=retain))


async def poll_judge() -> None:
    url = configured_url()
    if url is None:
        return
    token = settings.career_judge0_token.get_secret_value()
    headers = {"X-Auth-Token": token} if token else {}
    async with httpx.AsyncClient(base_url=url + "/", headers=headers, trust_env=False,
                                 timeout=httpx.Timeout(4, connect=2)) as client:
        while True:
            try:
                row = await _claim()
                if row is not None:
                    await _execute_sandbox(client, row)
            except Exception:
                logger.exception("Career judge poll failed")
            await asyncio.sleep(0.9)
