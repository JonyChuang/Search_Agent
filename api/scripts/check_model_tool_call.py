"""用已配置的对话模型完成一次 Comet 原生工具调用。"""
import argparse
import asyncio

from langchain_core.messages import HumanMessage

from app.core.agent.orchestrator import run_function_calling
from app.core.agent.tools.base import BUILTIN_REGISTRY, ToolBuildContext
from app.core.agent.tools.builtin.datetime_tool import KEY
from app.core.llm.chat_model import build_default_chat_model, supports_function_call
from app.db.postgres import SessionLocal, close
from app.repositories.user_repository import UserRepository


async def verify_tool_call(username: str) -> None:
    try:
        async with SessionLocal() as session:
            user = await UserRepository(session).get_by_username(username)
            if user is None:
                raise SystemExit("找不到该 Comet 账号")

            model, config = await build_default_chat_model(session, user.id, deepseek_tool_mode=True)
            if not supports_function_call(config):
                raise SystemExit("请在对话模型配置中启用 function_call")
            tool = await BUILTIN_REGISTRY[KEY].builder(ToolBuildContext(session, user.id, [], {}, {}))
    finally:
        await close()

    messages = [HumanMessage(content="请调用 datetime 工具，然后告诉我现在的北京时间。")]
    observed = False
    async for event in run_function_calling(model, [tool], messages):
        if event["type"] == "tool_result" and event["tool"] == KEY and event["status"] == "success":
            observed = True
            print(f"tool_result: {KEY} success")
        elif event["type"] == "final" and observed and event["text"].strip():
            print(event["text"])
            return
    raise SystemExit("未完成时间工具调用及回答")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="已配置默认对话模型的 Comet 用户名")
    asyncio.run(verify_tool_call(parser.parse_args().username))
