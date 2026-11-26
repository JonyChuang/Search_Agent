"""Durable career task state shared with the existing MySQL queue."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.exceptions import BizError
from app.services.career_training_contract import TrainingContract
from app.services.career_training_runtime import retry_block

PUBLIC_KINDS = {"TRAINING", "REVIEW", "INTERVIEW", "PREPARATION", "DISCOVERY"}
MAX_AUTOMATIC_RETRIES = 2
TRAINING_EVENT_RETENTION_DAYS = 30
FENCE = """
    id = :id AND generation = :generation AND lease_token = :lease
    AND status = 'RUNNING' AND lease_until > CURRENT_TIMESTAMP(6)
"""
TASK_JSON = (
    "request_json", "context_json", "result_json", "training_catalog_json",
    "training_draft_json", "agent_context_json", "training_runtime_json",
)


def conflict(message: str):
    return BizError(message, code=409, status_code=409)


def view(row: dict) -> dict:
    result = deepcopy(row["result_json"])
    if result and "openQuestions" in result:
        for question in result["openQuestions"]:
            question.pop("rubric", None)
            question.pop("referenceAnswer", None)
    context = row["context_json"]
    kind, status = row["kind"], row["status"]
    interview = None
    if kind == "INTERVIEW":
        question = context.get("question") or {}
        interview = {
            "prompt": question.get("prompt") or "",
            "gradingVersion": question.get("gradingVersion") or 0,
            "sourceUrl": str(question.get("sourceUrl") or ""),
            "answer": context.get("answer") or "",
        }
        if status == "SUCCEEDED" and question.get("kind") == "OPEN":
            interview["rubric"] = question.get("rubric")
            if question.get("referenceAnswer") is not None:
                interview["referenceAnswer"] = question["referenceAnswer"]
    step = None
    if kind == "TRAINING":
        if status == "SUCCEEDED":
            step = "COMPLETE"
        elif row["training_draft_json"] is not None:
            step = "SAVE_PLAN"
        elif row["training_catalog_json"] is not None:
            step = "GENERATE_PLAN"
        else:
            step = "FIND_QUESTIONS"
    blocked = retry_block(row) if status in {"FAILED", "WAITING_USER"} else None
    return {
        "id": row["id"], "kind": kind, "status": status, "request": row["request_json"],
        "job": (context.get("job") or {}).get("label", ""), "interview": interview,
        "result": result, "error": row["error_message"], "generation": row["generation"],
        "retryBlocked": {"code": blocked.code, "message": str(blocked)} if blocked else None,
        "trainingStep": step, "references": (row["agent_context_json"] or {}).get("references"),
        "createdAt": row["created_at"].replace(tzinfo=timezone.utc),
        "updatedAt": row["updated_at"].replace(tzinfo=timezone.utc),
    }


def _decode(row) -> dict:
    decoded = dict(row)
    for field in TASK_JSON:
        if decoded.get(field) is not None:
            decoded[field] = json.loads(decoded[field])
    return decoded


class CareerQueue:
    def __init__(self, db: AsyncConnection):
        self.db = db

    async def _run(self, sql: str, **params):
        return await self.db.execute(text(sql), params)

    async def _one(self, where: str, **params) -> dict | None:
        row = (await self._run(f"SELECT * FROM career_task WHERE {where}", **params)).mappings().one_or_none()
        return _decode(row) if row is not None else None

    async def _lock_scheduler(self) -> None:
        (await self._run("SELECT id FROM career_task_scheduler WHERE id = 1 FOR UPDATE")).scalar_one()

    async def _check_queue(self, user: str) -> None:
        row = (await self._run("""
            SELECT COUNT(*) AS total, COALESCE(SUM(user_id = :user), 0) AS own
            FROM career_task WHERE status = 'QUEUED'
        """, user=user)).one()
        if row.total >= 200 or row.own >= 20:
            raise BizError("待处理任务已满，请等部分任务完成后再试", code=429, status_code=429)

    async def owned(self, user: str, task_id: str, *, public=True) -> dict:
        row = await self._one("user_id = :user AND id = :id", user=user, id=task_id)
        if row is None or (public and row["kind"] not in PUBLIC_KINDS):
            raise BizError("任务不存在", code=404, status_code=404)
        return row

    async def by_request(
        self, user: str, kind: str, request: dict, request_id: str | None = None,
    ) -> dict | None:
        existing = await self.lookup_request(user, request_id or request["requestId"])
        if existing and (existing["kind"] != kind or existing["request_json"] != request):
            raise conflict("请求编号已用于另一项任务")
        return existing

    async def lookup_request(self, user: str, request_id: str) -> dict | None:
        return await self._one("user_id = :user AND request_id = :request_id", user=user, request_id=request_id)

    async def insert(
        self, user: str, kind: str, job_id: str, request: dict, context: dict,
        *, request_id: str | None = None, training_catalog: list[dict] | None = None,
    ) -> dict:
        request_id = request_id or request["requestId"]
        await self._lock_scheduler()
        existing = await self.by_request(user, kind, request, request_id)
        if existing:
            return existing
        await self._check_queue(user)
        task_id = str(uuid4())
        await self._run("""
            INSERT INTO career_task (id, user_id, request_id, kind, job_id, request_json, context_json,
                                     training_catalog_json, training_catalog_at)
            VALUES (:id, :user, :request_id, :kind, :job, :request, :context,
                    :catalog, IF(:catalog IS NULL, NULL, CURRENT_TIMESTAMP(6)))
        """, id=task_id, user=user, request_id=request_id, kind=kind, job=job_id,
            catalog=json.dumps(training_catalog, ensure_ascii=False) if training_catalog is not None else None,
            request=json.dumps(request, ensure_ascii=False), context=json.dumps(context, ensure_ascii=False))
        return await self.owned(user, task_id, public=False)

    async def list(self, user: str, kind: str, job_id: str | None, content: str | None, page: int) -> dict:
        rows = await self._run("""
            SELECT * FROM career_task WHERE user_id = :user AND kind = :kind
              AND (:job IS NULL OR job_id = :job)
              AND (:content IS NULL OR (:content = 'notes') = (COALESCE(request_json->>'$.purpose', '') = 'NOTES'))
            ORDER BY created_at DESC, id DESC LIMIT 21 OFFSET :offset
        """, user=user, kind=kind, job=job_id, content=content, offset=(page - 1) * 20)
        items = [view(_decode(row)) for row in rows.mappings()]
        return {"items": items[:20], "hasMore": len(items) > 20}

    async def events(self, user: str, task_id: str) -> list[dict]:
        await self.owned(user, task_id)
        rows = await self._run("""
            SELECT generation, sequence_no AS sequenceNo, step, outcome, elapsed_ms AS elapsedMs,
                input_tokens AS inputTokens, output_tokens AS outputTokens,
                CASE WHEN created_at >= TIMESTAMPADD(DAY, :retention, CURRENT_TIMESTAMP(6))
                    THEN JSON_REMOVE(details_json, '$.replay') END AS details, created_at AS createdAt
            FROM career_task_event WHERE task_id = :id
            ORDER BY generation DESC, sequence_no DESC LIMIT 100
        """, id=task_id, retention=-TRAINING_EVENT_RETENTION_DAYS)
        return [dict(row, details=json.loads(row["details"]) if row["details"] else None,
                     createdAt=row["createdAt"].replace(tzinfo=timezone.utc)) for row in rows.mappings()]

    async def retry(self, user: str, task_id: str, *, public: bool = True) -> dict:
        await self._lock_scheduler()
        row = await self.owned(user, task_id, public=public)
        if row["status"] == "FAILED":
            if blocked := retry_block(row):
                raise conflict(str(blocked)) from blocked
            await self._check_queue(user)
            await self._run("""
                UPDATE career_task SET status = 'QUEUED', error_message = NULL, queued_at = CURRENT_TIMESTAMP(6)
                WHERE user_id = :user AND id = :id AND status = 'FAILED'
            """, user=user, id=task_id)
            row = await self.owned(user, task_id, public=public)
        return row

    async def change_state(
        self, user: str, task_id: str, action: str, status: str, generation: int,
    ) -> dict:
        target, allowed = {
            "PAUSE": ("WAITING_USER", {"QUEUED", "RUNNING"}),
            "RESUME": ("QUEUED", {"WAITING_USER"}),
            "CANCEL": ("CANCELLED", {"QUEUED", "RUNNING", "WAITING_USER", "FAILED"}),
        }[action]
        row = await self.owned(user, task_id)
        if row["status"] == target and row["generation"] == generation:
            return row
        if row["status"] != status or status not in allowed:
            raise conflict("任务状态已变化，请刷新后重试")
        if action == "RESUME" and (blocked := retry_block(row)):
            raise conflict(str(blocked)) from blocked
        changed = await self._run("""
            UPDATE career_task SET status = :target, lease_token = NULL, lease_until = NULL,
                queued_at = IF(:target = 'QUEUED', CURRENT_TIMESTAMP(6), queued_at)
            WHERE user_id = :user AND id = :id AND status = :status AND generation = :generation
              AND (:target = 'QUEUED' OR kind <> 'TRAINING' OR training_draft_json IS NULL)
        """, target=target, user=user, id=task_id, status=status, generation=generation)
        if changed.rowcount != 1:
            raise conflict("任务状态已变化，请刷新后重试")
        return await self.owned(user, task_id)

    async def claim(self, kinds: tuple[str, ...]) -> dict | None:
        if not kinds:
            return None
        await self._lock_scheduler()
        filters = ", ".join(f":kind{i}" for i in range(len(kinds)))
        params = {f"kind{i}": kind for i, kind in enumerate(kinds)}
        task_id = (await self._run(f"""
            SELECT t.id, t.status, t.generation, t.training_draft_json IS NOT NULL AS has_draft,
                t.context_json->'$.trainingContract' IS NOT NULL AS has_contract,
                COALESCE(t.training_runtime_json->>'$.stage' = 'VERIFIED', FALSE) AS verified
            FROM career_task t
            WHERE t.kind IN ({filters})
              AND ((t.status = 'QUEUED' AND t.queued_at <= CURRENT_TIMESTAMP(6))
                   OR (t.status = 'RUNNING' AND t.lease_until <= CURRENT_TIMESTAMP(6)))
              AND (SELECT COUNT(*) FROM career_task r WHERE r.status = 'RUNNING'
                   AND r.lease_until > CURRENT_TIMESTAMP(6)) < 4
              AND (SELECT COUNT(*) FROM career_task r WHERE r.status = 'RUNNING'
                   AND r.lease_until > CURRENT_TIMESTAMP(6) AND r.user_id = t.user_id) < 2
              AND NOT EXISTS (SELECT 1 FROM career_task r
                   WHERE r.user_id = t.user_id AND r.job_id <=> t.job_id AND r.id <> t.id
                     AND ((r.status = 'RUNNING' AND r.lease_until > CURRENT_TIMESTAMP(6))
                       OR (r.status IN ('RUNNING', 'QUEUED') AND (r.queued_at, r.id) < (t.queued_at, t.id))))
            ORDER BY t.queued_at, t.id LIMIT 1 FOR UPDATE SKIP LOCKED
        """, **params)).one_or_none()
        if task_id is None:
            return None
        if task_id.status == "RUNNING":
            step = "lease_reclaimed" if task_id.has_contract else None
            if (not task_id.has_draft and not task_id.verified
                    and await self._automatic_retries(task_id.id, step) >= MAX_AUTOMATIC_RETRIES):
                await self._run("""UPDATE career_task SET status = 'FAILED', lease_token = NULL, lease_until = NULL,
                    training_runtime_json = JSON_SET(training_runtime_json, '$.failureCode', 'WORKER_INTERRUPTED'),
                    error_message = :error WHERE id = :id""", id=task_id.id, error="任务多次失去执行租约，请手动重试。")
                return None
            await self._run("""INSERT INTO career_task_event (task_id, generation, sequence_no, step, outcome, elapsed_ms)
                VALUES (:id, :generation, -1, 'lease_reclaimed', 'failed', 0)""",
                id=task_id.id, generation=task_id.generation)
        await self._run("""
            UPDATE career_task SET status = 'RUNNING', generation = generation + 1,
                lease_token = :lease, lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND)
            WHERE id = :id
        """, id=task_id.id, lease=str(uuid4()))
        return await self._one("id = :id", id=task_id.id)

    async def _automatic_retries(self, task_id: str, step: str | None = None) -> int:
        return (await self._run("""SELECT COUNT(*) FROM career_task_event
            WHERE task_id = :id AND step IN ('auto_retry', 'lease_reclaimed') AND (:step IS NULL OR step = :step)""",
                                id=task_id, step=step)).scalar_one()

    async def renew(self, row: dict) -> bool:
        changed = await self._run(f"""UPDATE career_task SET
            lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND) WHERE {FENCE}""", **self.lease(row))
        return changed.rowcount == 1

    async def release(self, row: dict) -> None:
        await self._run(f"""UPDATE career_task SET status = 'QUEUED', lease_token = NULL, lease_until = NULL
            WHERE {FENCE}""", **self.lease(row))

    async def retry_transient(self, row: dict) -> bool:
        raw = (row.get("context_json") or {}).get("trainingContract")
        budget = TrainingContract.model_validate(raw).budget if raw else None
        attempts = await self._automatic_retries(row["id"], "auto_retry" if budget else None)
        if attempts >= (budget.maxTransientRetries if budget else MAX_AUTOMATIC_RETRIES) or retry_block(row):
            return False
        await self.record_event(row, {"sequenceNo": -2, "step": "auto_retry", "outcome": "failed",
                                      "elapsedMs": 0, "inputTokens": None, "outputTokens": None,
                                      "details": {"errorCode": "TRANSIENT_MODEL_ERROR", "transientRetries": attempts + 1}
                                      if budget else None})
        updated = await self._run(f"""UPDATE career_task SET status = 'QUEUED', lease_token = NULL, lease_until = NULL,
            training_runtime_json = IF(:v2, JSON_SET(training_runtime_json, '$.transientRetries', :attempts),
                                      training_runtime_json),
            queued_at = TIMESTAMPADD(SECOND, :delay, CURRENT_TIMESTAMP(6)) WHERE {FENCE}""",
            delay=4 * 2**attempts, v2=budget is not None, attempts=attempts + 1, **self.lease(row))
        return updated.rowcount == 1

    @staticmethod
    def lease(row: dict) -> dict:
        return {"id": row["id"], "generation": row["generation"], "lease": row["lease_token"]}

    async def active(self, row: dict) -> dict:
        result = await self._one(FENCE, **self.lease(row))
        if result is None:
            raise conflict("任务执行代次已失效")
        return result

    async def checkpoint(self, row: dict, column: str, value) -> dict:
        suffix = {
            "agent_context_json": "",
            "training_catalog_json": ", training_catalog_at = CURRENT_TIMESTAMP(6)",
            "training_draft_json": ", training_draft_at = CURRENT_TIMESTAMP(6)",
        }[column]
        extra = "AND training_catalog_json IS NOT NULL" if column == "training_draft_json" else ""
        await self._run(f"""
            UPDATE career_task SET {column} = :value {suffix}
            WHERE {FENCE} AND {column} IS NULL {extra}
        """, value=json.dumps(value, ensure_ascii=False), **self.lease(row))
        saved = (await self.active(row))[column]
        if saved != value:
            raise conflict("任务检查点已保存或前置阶段尚未完成")
        return saved

    async def record_event(self, row: dict, event: dict) -> None:
        details = event.get("details")
        await self._run(f"""
            INSERT INTO career_task_event (task_id, generation, sequence_no, step, outcome,
                                                elapsed_ms, input_tokens, output_tokens, details_json)
            SELECT id, generation, :sequenceNo, :step, :outcome, :elapsedMs, :inputTokens, :outputTokens, :details_json
            FROM career_task WHERE {FENCE}
            ON DUPLICATE KEY UPDATE sequence_no = career_task_event.sequence_no
        """, **self.lease(row), **event, details_json=json.dumps(details, ensure_ascii=False) if details else None)
        await self.active(row)

    async def training_runtime(self, row: dict, value: dict) -> None:
        # The generation and lease predicate guards every reservation and candidate update.
        operation = value.get("operation") or {}
        complete = operation.get("status") in {"NO_RESULT", "VALIDATED"}
        await self._run(f"""
            UPDATE career_task SET training_runtime_json = :value
            WHERE {FENCE} AND kind = 'TRAINING' AND training_draft_json IS NULL
              AND (NOT :complete OR (training_runtime_json->>'$.operation.id' = :operation_id
                   AND training_runtime_json->>'$.operation.status' = 'RESERVED'))
        """, value=json.dumps(value, ensure_ascii=False), complete=complete, operation_id=operation.get("id"),
            **self.lease(row))
        if (await self.active(row)).get("training_runtime_json") != value:
            raise conflict("训练执行状态无法更新")

    async def prune_training_diagnostics(self) -> None:
        await self._run("""UPDATE career_task_event SET details_json = NULL
            WHERE details_json IS NOT NULL AND created_at < TIMESTAMPADD(DAY, :retention, CURRENT_TIMESTAMP(6))
            ORDER BY created_at LIMIT 200""", retention=-TRAINING_EVENT_RETENTION_DAYS)

    async def finish(self, row: dict, result: dict | None, error: str | None, *, failure_code: str | None = None) -> bool:
        changed = await self._run(f"""
            UPDATE career_task SET status = :status, result_json = :result, error_message = :error,
                training_runtime_json = CASE WHEN :status = 'SUCCEEDED'
                    THEN JSON_REMOVE(training_runtime_json, '$.candidate', '$.failureCode')
                    WHEN :failure_code IS NOT NULL THEN JSON_SET(training_runtime_json, '$.failureCode', :failure_code)
                    ELSE training_runtime_json END,
                lease_token = NULL, lease_until = NULL
            WHERE {FENCE}
        """, status="FAILED" if error else "SUCCEEDED", error=error, failure_code=failure_code,
            result=json.dumps(result, ensure_ascii=False) if result is not None else None, **self.lease(row))
        return changed.rowcount == 1
