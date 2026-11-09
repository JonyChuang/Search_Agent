"""Java 到 Agent 的内部 HTTP 接口。"""
import logging
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings
from app.core.exceptions import BizError
from app.services.career_task_service import CareerRun, InvalidCareerToolResponse, MissingCareerTools, execute

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/v1", include_in_schema=False)
bearer = HTTPBearer(auto_error=False)


def require_career_service(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    token = settings.career_agent_internal_token.get_secret_value()
    if not token:
        raise HTTPException(503, "Agent 内部接口未配置")
    if credentials is None or not compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(401, "内部服务认证失败", headers={"WWW-Authenticate": "Bearer"})


class AgentHealth(BaseModel):
    status: Literal["UP"] = "UP"


@router.get("/health", dependencies=[Depends(require_career_service)])
async def health() -> AgentHealth:
    return AgentHealth()


@router.post("/tasks", dependencies=[Depends(require_career_service)])
async def run_task(run: CareerRun) -> dict:
    try:
        return await execute(run)
    except MissingCareerTools as error:
        raise HTTPException(412, "默认对话模型未启用工具调用") from error
    except InvalidCareerToolResponse as error:
        raise HTTPException(422, "模型未按工具格式返回结果") from error
    except BizError as error:
        if error.code == 2010:
            raise HTTPException(412, "未配置默认对话模型") from error
        raise
    except TimeoutError as error:
        raise HTTPException(504, "Agent 执行超时") from error
    except Exception as error:
        logger.warning("Career task %s failed (%s)", run.id, type(error).__name__)
        raise HTTPException(502, "Agent 执行失败") from error
