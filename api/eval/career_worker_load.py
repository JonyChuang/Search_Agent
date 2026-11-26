"""Exercise real MySQL queue concurrency, lease expiry and fencing on isolated tables."""

import asyncio
import re
from uuid import uuid4

from sqlalchemy import text

from app.config import settings
from app.db.career import career_transaction, close
from app.services.career_queue import CareerQueue


async def run() -> dict:
    if settings.career_mysql_host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Use a local MySQL instance for this evaluation")
    prefix = f"eval_{uuid4().hex[:10]}_"
    model_tables = ("career_task", "career_task_event", "career_task_scheduler")
    pattern = re.compile(r"\b(?:career_task_event|career_task_scheduler|career_task)\b")

    class IsolatedQueue(CareerQueue):
        async def _run(self, sql, **params):
            return await super()._run(pattern.sub(lambda match: prefix + match[0], sql), **params)

    created = []
    try:
        async with career_transaction() as db:
            for table in model_tables:
                await db.execute(text(f"CREATE TABLE {prefix}{table} LIKE {table}"))
                created.append(prefix + table)
            await db.execute(text(f"INSERT INTO {prefix}career_task_scheduler (id) VALUES (1)"))
        owners = [str(uuid4()), str(uuid4())]
        requests = [(owners[index % 2], str(uuid4()), {"requestId": str(uuid4())}) for index in range(8)]

        async def submit(spec):
            async with career_transaction() as db:
                return await IsolatedQueue(db).insert(spec[0], "TRAINING", spec[1], spec[2], {})

        submitted = await asyncio.gather(*(submit(spec) for spec in requests * 2))
        assert len({row["id"] for row in submitted}) == 8

        async def claim():
            async with career_transaction() as db:
                return await IsolatedQueue(db).claim(("TRAINING",))

        claimed = [row for row in await asyncio.gather(*(claim() for _ in range(12))) if row]
        assert len({row["id"] for row in claimed}) == 4
        assert all(sum(row["user_id"] == owner for row in claimed) == 2 for owner in owners)
        previous = claimed[0]
        async with career_transaction() as db:
            queue = IsolatedQueue(db)
            assert await queue.renew(previous)
            await queue.checkpoint(previous, "agent_context_json", {"payload": "existing"})
            await queue._run("UPDATE career_task SET lease_until = CURRENT_TIMESTAMP(6) WHERE id = :id", id=previous["id"])
        recovered = await claim()
        assert recovered and recovered["id"] == previous["id"] and recovered["generation"] == previous["generation"] + 1
        assert recovered["agent_context_json"] == {"payload": "existing"}
        async with career_transaction() as db:
            queue = IsolatedQueue(db)
            assert not await queue.renew(previous)
            assert not await queue.finish(previous, {"stale": True}, None)
            assert await queue.retry_transient(recovered)
            retry = await queue.owned(recovered["user_id"], recovered["id"])
            assert retry["status"] == "QUEUED" and retry["lease_token"] is None
            assert await queue._automatic_retries(recovered["id"]) == 2
        return {"submissions": len(submitted), "unique_tasks": 8, "parallel_claimers": 12,
                "successful_initial_claims": 4, "checkpoint_reused": True, "stale_write_rejected": True,
                "transient_retry_recorded": True}
    finally:
        async with career_transaction() as db:
            for table in reversed(created):
                await db.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await close()


if __name__ == "__main__":
    print(asyncio.run(run()))
