"""Run the durable career queue directly in Python."""

import asyncio
import logging
import re
import signal
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from openai import APIConnectionError, APIStatusError, RateLimitError
from sqlalchemy import text

from app.config import settings
from app.core.agent.tracing import get_tracer
from app.core.exceptions import BizError
from app.db.career import career_transaction
from app.db.postgres import SessionLocal
from app.services.career_context import CareerContextTooLarge, CareerSourceUnavailable, encode
from app.services.career_interviews import CareerInterviews, apply_evaluation
from app.services.career_queue import PUBLIC_KINDS, CareerQueue, conflict
from app.services.career_records import CareerRecords
from app.services.career_task_service import (
    CareerRun,
    CareerSkillUnavailable,
    InvalidCareerToolResponse,
    MissingCareerSearch,
    MissingCareerTools,
    execute,
)
from app.services.career_training import CareerTraining
from app.services.career_training_contract import TrainingContract, TrainingContractError
from app.services.career_training_harness import explain_learning
from app.services.career_training_runtime import TrainingExecution, TrainingProgress
from app.services.career_training_verifier import TrainingPlan, verify_plan

logger = logging.getLogger(__name__)
_LEASE_HEARTBEAT_SECONDS = 20


class NativeCareerCheckpoints:
    def __init__(self, row: dict):
        self.row = row

    async def checkpoint_context(self, value: dict) -> None:
        async with career_transaction() as connection:
            queue = CareerQueue(connection)
            active = await queue.active(self.row)
            raw = active["context_json"]
            preferences = raw.get("preferences") or {}
            if "revision" in preferences and "trainingContract" not in raw:
                records = CareerRecords(connection, active["user_id"])
                await records.jobs().get(active["job_id"], lock=True)
                current = await records.job_notes(active["job_id"])
                if current["revision"] != preferences["revision"]:
                    raise conflict("备考偏好已修改，请重新创建任务")
            payload, refs = value.get("payload"), value.get("references")
            documents = raw.get("documentIds") or []
            if not isinstance(payload, dict) or "documents" in payload or not isinstance(refs, list) \
                    or len(refs) != len(documents) or len(encode(value)) > 100_000:
                raise BizError("备考上下文格式无效", code=400)
            for doc, ref in zip(documents, refs, strict=True):
                if doc != ref.get("id") or not re.fullmatch(r"[0-9a-f]{64}", ref.get("revision", "")) \
                        or not ref.get("title", "").strip() or len(ref["title"]) > 512:
                    raise BizError("备考资料引用不在本次任务范围内", code=400)
            await queue.checkpoint(self.row, "agent_context_json", value)

    async def questions(self) -> list[dict]:
        async with career_transaction() as connection:
            queue = CareerQueue(connection)
            active = await queue.active(self.row)
            saved = active["training_catalog_json"]
            if saved is not None:
                return saved
            records = CareerRecords(connection, active["user_id"])
            catalog = await CareerTraining(records).catalog(active)
            return await queue.checkpoint(self.row, "training_catalog_json", catalog)

    async def plan(self, plan: dict) -> None:
        async with career_transaction() as connection:
            queue = CareerQueue(connection)
            active = await queue.active(self.row)
            saved = active["training_catalog_json"]
            if saved is None:
                raise conflict("请先完成查题")
            raw = active["context_json"]
            if "trainingContract" in raw:
                contract = TrainingContract.model_validate(raw["trainingContract"])
                candidate = TrainingPlan.model_validate({key: value for key, value in plan.items() if key != "steps"})
                evidence = {item["id"] for item in raw.get("experiences", [])}
                if not verify_plan(candidate, contract, saved, evidence).passed:
                    raise TrainingContractError("训练计划未通过保存校验。", "FINAL_VERIFICATION_FAILED")
                plan = candidate.draft()
                by_id = {ref["id"]: ref for ref in plan["questions"]}
                plan["questions"] = [by_id[identifier] for step in candidate.schedule for identifier in step.questionRefs]
            allowed = {(q["id"], q["version"]): q for q in saved}
            ids = set()
            selected = []
            for ref in plan["questions"]:
                key = (ref["id"], ref["version"])
                if key not in allowed or ref["id"] in ids:
                    raise BizError("训练题目、版本无效或题目重复", code=400)
                selected.append({field: value for field, value in allowed[key].items() if field != "practiceCompleted"})
                ids.add(ref["id"])
            preferred = active["context_json"].get("preferredQuestion")
            if preferred and preferred not in ids:
                raise BizError("计划必须包含用户指定的题目", code=400)
            draft = {**plan, "questions": selected}
            learning = active["context_json"].get("practiceLearning")
            if learning:
                draft["learning"] = explain_learning(selected, saved, learning)
            await queue.checkpoint(self.row, "training_draft_json", draft)

    async def record_event(self, value: dict) -> None:
        async with career_transaction() as connection:
            await CareerQueue(connection).record_event(self.row, value)

    async def training_runtime(self, value: dict) -> None:
        async with career_transaction() as connection:
            await CareerQueue(connection).training_runtime(self.row, value)


def _search_source_is_public(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and parsed.username is None
    except ValueError:
        return False


def _display_error(error: Exception) -> str:
    if isinstance(error, TrainingContractError):
        return str(error)
    if isinstance(error, MissingCareerTools) or isinstance(error, BizError) and error.code == 2010:
        return "请在模型配置中设置支持工具调用的默认对话模型，然后重试"
    if isinstance(error, MissingCareerSearch):
        return "请先在模型配置中添加联网搜索，再重试"
    if isinstance(error, InvalidCareerToolResponse):
        return "模型未返回符合工具格式的结果。可以重试，或切换支持工具调用的模型。"
    if isinstance(error, (CareerSourceUnavailable, CareerSkillUnavailable)):
        return "备考资料或技能不可用、已变更，请检查后重新创建任务。"
    if isinstance(error, CareerContextTooLarge):
        return "备考输入超出上下文预算，请减少参考资料或缩短输入后重新创建任务。"
    if isinstance(error, RateLimitError):
        return "模型服务暂时繁忙，请稍后重试。"
    if isinstance(error, BizError):
        return error.message
    return "Agent 执行失败，请稍后重试"


async def run_claimed(row: dict) -> None:
    checkpoint = next((stage for column, stage in (
        ("training_draft_json", "resume_draft"), ("training_runtime_json", "resume_training"),
        ("training_catalog_json", "resume_catalog"),
        ("agent_context_json", "resume_context"),
    ) if row.get(column) is not None), None)
    if checkpoint == "resume_catalog" and row["generation"] == 1 and row["context_json"].get("trainingContract"):
        checkpoint = None
    async with get_tracer().trace(
        user_id=UUID(row["user_id"]), task_type="career_task", task_id=UUID(row["id"]), task_name=row["kind"],
        attributes={"career.generation": row["generation"], "career.resume_from": checkpoint or "start"},
    ) as trace:
        if checkpoint:
            try:
                await NativeCareerCheckpoints(row).record_event({
                    "sequenceNo": 0, "step": checkpoint, "outcome": "succeeded", "elapsedMs": 0,
                    "inputTokens": None, "outputTokens": None,
                })
            except BizError:
                return  # The task was paused, canceled, or reclaimed by another generation.
            except Exception as error:
                logger.warning("Career task %s could not record recovery (%s)", row["id"], type(error).__name__)
        outcome = await _run_claimed(row)
        trace.set_attribute("career.outcome", outcome)


async def _run_claimed(row: dict) -> str:
    result, error = row["training_draft_json"], None
    failure = None
    transient = False
    if result is None:
        try:
            if snapshot := row["context_json"].get("trainingContract"):
                if (snapshot["userId"], snapshot["jobId"]) != (row["user_id"], row["job_id"]):
                    raise TrainingContractError("任务契约与岗位范围不一致。", "CONTRACT_SCOPE_MISMATCH")
            run = CareerRun(
                id=row["id"], lease=row["lease_token"], userId=row["user_id"], kind=row["kind"],
                context=row["context_json"], trainingCatalog=row["training_catalog_json"],
                agentContext=row["agent_context_json"], practiceLearning=row["context_json"].get("practiceLearning"),
                trainingRuntime=row.get("training_runtime_json"),
            )
            result = await execute(run, NativeCareerCheckpoints(row))
            if run.kind == "PREPARATION" and run.context.get("purpose") == "NOTES":
                documents = run.context.get("documentIds") or []
                if any(note["reference"] > len(documents) for note in result["notes"]):
                    raise InvalidCareerToolResponse("Invalid document reference")
            if run.kind == "DISCOVERY":
                result = {
                    "sources": [source for source in result["sources"] if _search_source_is_public(source["url"])],
                    "searchedAt": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as exception:
            logger.warning("Career task %s generation %s failed: %s",
                           row["id"], row["generation"], type(exception).__name__)
            result, error = None, _display_error(exception)
            transient = isinstance(exception, (TimeoutError, APIConnectionError, RateLimitError))
            if row["context_json"].get("trainingContract") and isinstance(exception, APIStatusError):
                transient = transient or exception.status_code >= 500
            failure = (exception.code if isinstance(exception, TrainingContractError) else
                       "CONTEXT_BUDGET_EXCEEDED" if isinstance(exception, CareerContextTooLarge) else
                       "TRANSIENT_MODEL_ERROR" if transient else type(exception).__name__)
    async with career_transaction() as connection:
        queue = CareerQueue(connection)
        if row["kind"] == "TRAINING":
            try:
                current = await queue.active(row)
            except BizError:
                return "STALE"
            result = current["training_draft_json"]
            error = None if result is not None else error or "Agent 未生成训练计划"
        if error and transient and await queue.retry_transient(row):
            return "RETRY_QUEUED"
        if row["kind"] == "TRAINING" and current["context_json"].get("trainingContract"):
            await record_training_outcome(queue, current, error, failure)
        if row["kind"] == "INTERVIEW_TURN" and error is None:
            interviews = CareerInterviews(CareerRecords(connection, row["user_id"]))
            session = await interviews.find(row["request_json"]["sessionId"], lock=True)
            finished = await queue.finish(row, result, None)
            if finished and session and session["pending"] == row["id"]:
                apply_evaluation(session, result, False)
                await interviews.save(session)
        else:
            finished = await queue.finish(row, result, error)
    return ("FAILED" if error else "SUCCEEDED") if finished else "STALE"


async def record_training_outcome(queue: CareerQueue, row: dict, error: str | None, failure: str | None) -> None:
    saved = row.get("training_runtime_json")
    if saved is None:
        return
    contract = TrainingContract.model_validate(row["context_json"]["trainingContract"])
    state = TrainingProgress.model_validate(saved)
    runtime = TrainingExecution(contract, state, NativeCareerCheckpoints(row).training_runtime)
    elapsed_ms = int((datetime.now(timezone.utc) - state.startedAt).total_seconds() * 1000)
    details = {**runtime.details(), "stage": "FAILED" if error else "COMPLETED", "errorCode": failure if error else None,
               "validation": state.lastReport.public() if state.lastReport else None}
    await queue.record_event(row, {"sequenceNo": -3, "step": "training_outcome",
                                  "outcome": "failed" if error else "succeeded", "elapsedMs": elapsed_ms,
                                  "inputTokens": None, "outputTokens": None, "details": details})


async def recover_interview_turns() -> None:
    async with career_transaction() as connection:
        rows = await connection.execute(text("""
            SELECT s.user_id, s.id, s.pending_task_id
            FROM career_mock_interview s JOIN career_task t ON t.id = s.pending_task_id
                AND t.user_id = CONVERT(s.user_id USING utf8mb4) COLLATE utf8mb4_0900_ai_ci
            WHERE s.pending_task_id IS NOT NULL AND t.kind = 'INTERVIEW_TURN' AND t.status = 'SUCCEEDED'
            ORDER BY s.created_at LIMIT 25
        """))
        pending = rows.all()
    for user, session_id, task_id in pending:
        async with career_transaction() as connection:
            interviews = CareerInterviews(CareerRecords(connection, user))
            state = await interviews.find(session_id, lock=True)
            if state and state["pending"] == task_id:
                task = await interviews.queue.owned(user, task_id, public=False)
                if task["status"] == "SUCCEEDED":
                    apply_evaluation(state, task["result_json"], False)
                    await interviews.save(state)


async def poll_interview_recovery() -> None:
    while True:
        try:
            await recover_interview_turns()
        except Exception:
            logger.exception("Career interview recovery failed")
        await asyncio.sleep(10)


async def poll_career_queue() -> None:
    while True:
        try:
            async with career_transaction() as connection:
                row = await CareerQueue(connection).claim((*sorted(PUBLIC_KINDS), "INTERVIEW_TURN"))
            if row is not None:
                await supervise(row)
                continue
        except Exception:
            logger.exception("Career worker iteration failed")
        await asyncio.sleep(1)


async def supervise(row: dict) -> None:
    async def maintain_lease():
        while True:
            await asyncio.sleep(_LEASE_HEARTBEAT_SECONDS)
            async with career_transaction() as connection:
                if not await CareerQueue(connection).renew(row):
                    return

    runner = asyncio.create_task(run_claimed(row))
    heartbeat = asyncio.create_task(maintain_lease())
    try:
        done, _ = await asyncio.wait((runner, heartbeat), return_when=asyncio.FIRST_COMPLETED)
        if runner in done:
            await runner
        else:
            await heartbeat
            logger.warning("Career worker lost lease task=%s generation=%s", row["id"], row["generation"])
    except asyncio.CancelledError:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        try:
            async with career_transaction() as connection:
                await CareerQueue(connection).release(row)
        except Exception:
            logger.warning("Career lease will expire after shutdown task=%s", row["id"])
        raise
    finally:
        runner.cancel()
        heartbeat.cancel()
        await asyncio.gather(runner, heartbeat, return_exceptions=True)


async def monitor_queue() -> None:
    while True:
        try:
            async with career_transaction() as connection:
                rows = await connection.execute(text("""
                    SELECT COUNT(CASE WHEN status = 'QUEUED' THEN 1 END) AS queued,
                        COUNT(CASE WHEN status = 'RUNNING' AND lease_until <= CURRENT_TIMESTAMP(6) THEN 1 END) AS expired,
                        COALESCE(MAX(CASE WHEN status = 'QUEUED' THEN
                            TIMESTAMPDIFF(SECOND, queued_at, CURRENT_TIMESTAMP(6)) END), 0) AS oldest
                    FROM career_task WHERE status IN ('RUNNING', 'QUEUED')
                """))
                queued, expired, oldest = rows.one()
            async with career_transaction() as connection:
                await CareerQueue(connection).prune_training_diagnostics()
            await record_queue_sample(queued, expired, max(0, oldest))
            await deliver_queue_alerts()
        except Exception as error:
            logger.warning("Career queue monitoring unavailable type=%s", type(error).__name__)
        await asyncio.sleep(60)


async def record_queue_sample(queued: int, expired: int, oldest: int) -> None:
    alert = expired > 0 or oldest > 300
    log = logger.warning if alert else logger.info
    log("Career queue queued=%s expired_leases=%s oldest_wait_seconds=%s", queued, expired, oldest)
    async with SessionLocal.begin() as session:
        previous = (await session.execute(text("""
            WITH previous AS (
                SELECT COALESCE((
                    SELECT alert FROM career_queue_samples WHERE sampled_at < date_trunc('minute', now())
                    ORDER BY sampled_at DESC LIMIT 1
                ), false) AS alert
            ), inserted AS (
                INSERT INTO career_queue_samples(sampled_at, queued, expired_leases, oldest_wait_seconds, alert,
                                                 notification_pending)
                SELECT date_trunc('minute', now()), :queued, :expired, :oldest, :alert,
                    :notify AND previous.alert <> :alert FROM previous
                ON CONFLICT (sampled_at) DO NOTHING RETURNING sampled_at
            )
            SELECT previous.alert FROM inserted CROSS JOIN previous
        """), {"queued": queued, "expired": expired, "oldest": oldest, "alert": alert,
               "notify": bool(settings.career_alert_webhook_url.get_secret_value())})).scalar_one_or_none()
    if previous is not None and previous != alert:
        level = logger.warning if alert else logger.info
        level("Career queue alert transition=%s backlog=%s expired_leases=%s",
              "raised" if alert else "cleared", queued, expired)


async def deliver_queue_alerts() -> None:
    endpoint = settings.career_alert_webhook_url.get_secret_value()
    if not endpoint:
        return
    token = settings.career_alert_webhook_token.get_secret_value()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=4, follow_redirects=False, trust_env=False, headers=headers) as client:
        for _ in range(5):
            async with SessionLocal.begin() as session:
                if not (await session.execute(text(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended('career-queue-alert-delivery', 0))"
                ))).scalar_one():
                    return
                row = (await session.execute(text("""
                    SELECT sampled_at, queued, expired_leases, oldest_wait_seconds, alert
                    FROM career_queue_samples WHERE notification_pending IS TRUE ORDER BY sampled_at LIMIT 1
                """))).mappings().one_or_none()
                if not row:
                    return
                event = {key: row[key] for key in ("queued", "expired_leases", "oldest_wait_seconds")}
                sampled_at = row["sampled_at"].isoformat()
                event_id = f"career-queue:{sampled_at}"
                try:
                    async with asyncio.timeout(5):
                        response = await client.post(endpoint, headers={"Idempotency-Key": event_id}, json={
                            **event, "id": event_id, "sampled_at": sampled_at, "state": "raised" if row["alert"] else "cleared",
                        })
                        response.raise_for_status()
                except (httpx.HTTPError, TimeoutError) as error:
                    logger.warning("Career queue alert delivery pending id=%s type=%s", event_id, type(error).__name__)
                    return
                await session.execute(text("""
                    UPDATE career_queue_samples SET notification_pending = false WHERE sampled_at = :at
                """), {"at": row["sampled_at"]})


def start_workers() -> list[asyncio.Task]:
    from app.controllers.career_content_controller import curators, feed_schedule, poll_feeds
    from app.controllers.career_judge_controller import configured_url, poll_judge
    from app.services.career_reminders import poll_reminders

    curators()
    feeds = feed_schedule()
    judge = configured_url()
    workers = [asyncio.create_task(poll_career_queue()) for _ in range(4)]
    workers.extend(asyncio.create_task(run()) for run in (poll_interview_recovery, poll_reminders, monitor_queue))
    if judge:
        workers.extend(asyncio.create_task(poll_judge()) for _ in range(2))
    if feeds:
        workers.append(asyncio.create_task(poll_feeds()))
    return workers


async def _main():
    from app.core.agent.tracing.span_recorder import get_recorder
    from app.db import career, elastic, neo4j, postgres, redis

    await career.verify_career_schema()
    await get_recorder().start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    workers = [asyncio.create_task(stop.wait()), *start_workers()]
    try:
        done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await get_recorder().stop()
        await asyncio.gather(career.close(), elastic.close(), neo4j.close(), postgres.close(), redis.close())


if __name__ == "__main__":
    asyncio.run(_main())
