"""FastAPI 应用入口。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.controllers.career_internal_controller import router as career_internal_router
from app.controllers.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.request_context import RequestContextMiddleware
from app.db import career, elastic, neo4j, postgres, redis

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.career_native_worker_enabled and not settings.career_mysql_host:
        raise RuntimeError("CAREER_NATIVE_WORKER_ENABLED requires CAREER_MYSQL_HOST")
    if settings.career_mysql_host:
        await career.verify_career_schema()
    # 启动：自动把数据库升级到最新迁移（alembic upgrade head）
    from app.db.migrate import upgrade_to_head

    try:
        await upgrade_to_head()
    except Exception as e:
        logger.error("数据库自动迁移失败，请检查迁移脚本或手动执行 alembic upgrade head: %s", e)
    # 启动：初始化 ES 索引
    from app.core.rag.es_index import ensure_index

    try:
        await ensure_index()
    except Exception as e:
        logger.warning("ES 索引初始化失败（稍后可重试）: %s", e)
    # 启动：初始化记忆图谱 schema（约束 + 向量/全文索引）
    from app.core.memory.graph_schema import ensure_graph_schema

    try:
        await ensure_graph_schema()
    except Exception as e:
        logger.warning("记忆图谱 schema 初始化失败（稍后可重试）: %s", e)
    # 启动:Agent Tracing 异步落库器(V0.0.5 ③)
    from app.core.agent.tracing.span_recorder import get_recorder

    try:
        await get_recorder().start()
    except Exception as e:
        logger.warning("Tracing 落库器启动失败（稍后可重试）: %s", e)
    logger.info("%s 启动完成", settings.app_name)
    workers = []
    if settings.career_native_worker_enabled:
        from app.controllers.career_content_controller import curators, feed_schedule, poll_feeds
        from app.controllers.career_judge_controller import configured_url, poll_judge
        from app.services.career_reminders import poll_reminders
        from app.services.career_worker import poll_career_queue, poll_interview_recovery

        curators()
        feeds = feed_schedule()
        judge = configured_url()
        workers = [asyncio.create_task(poll_career_queue()) for _ in range(4)]
        workers.append(asyncio.create_task(poll_interview_recovery()))
        workers.append(asyncio.create_task(poll_reminders()))
        if judge:
            workers.extend(asyncio.create_task(poll_judge()) for _ in range(2))
        if feeds:
            workers.append(asyncio.create_task(poll_feeds()))
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    # 关闭:先停 Tracing 落库器,把残留 span 排空
    try:
        await get_recorder().stop()
    except Exception as e:
        logger.warning("Tracing 落库器关闭异常: %s", e)
    # 关闭：释放长连接 / 连接池
    await career.close()
    await postgres.close()
    await elastic.close()
    await neo4j.close()
    await redis.close()
    logger.info("%s 已关闭，连接池释放完成", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        description="彗记 Comet — 个人 AI 知识库与记忆助手",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 请求上下文（request_id）中间件
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    app.include_router(career_internal_router)
    return app


app = create_app()
