"""技能（Skill）路由：CRUD + 内置模板列表 + 一键添加。"""
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.skill_schema import (
    OptimizeSkillPromptRequest,
    SkillCreate,
    SkillUpdate,
)
from app.services.skill_service import SkillService
from app.services.skill_packages import MAX_ARCHIVE, SkillPackageService, github_release, invalid, parse_release

router = APIRouter(prefix="/skills", tags=["skill"])


async def read_package(file: UploadFile | None, repository: str | None, commit: str | None):
    if file and not repository and not commit:
        return parse_release(await file.read(MAX_ARCHIVE + 1), "local")
    if file is None and repository and commit:
        return await github_release(repository, commit)
    raise invalid("请选择 ZIP 文件或指定 GitHub 仓库版本")


@router.post("/packages/preview")
async def preview_package(
    file: UploadFile | None = File(None), repository: str | None = Form(None), commit: str | None = Form(None),
    skill_id: uuid.UUID | None = Form(None), user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    release = await read_package(file, repository, commit)
    return success(await SkillPackageService(session).inspect(user.id, release, skill_id))


@router.post("/packages/install")
async def install_package(
    digest: str = Form(...), file: UploadFile | None = File(None), repository: str | None = Form(None),
    commit: str | None = Form(None), skill_id: uuid.UUID | None = Form(None),
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    release = await read_package(file, repository, commit)
    service = SkillPackageService(session)
    return success(SkillService.to_out_dict(await service.apply(user.id, release, digest, skill_id)), "版本已安装")


class PackageRollback(BaseModel):
    version: str = Field(min_length=1, max_length=40)


@router.post("/{skill_id}/packages/rollback")
async def rollback_package(
    skill_id: uuid.UUID, body: PackageRollback, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = SkillPackageService(session)
    return success(SkillService.to_out_dict(await service.rollback(user.id, skill_id, body.version)), "已切换版本")


@router.get("")
async def list_skills(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = SkillService(session)
    items = await service.list(user.id)
    return success([service.to_out_dict(s) for s in items])


@router.get("/builtins")
async def list_builtin_skills(
    user: User = Depends(get_current_user),
):
    """内置技能模板列表（用于「一键添加」前展示）。"""
    return success(SkillService.list_builtins())


@router.post("")
async def create_skill(
    body: SkillCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = SkillService(session)
    skill = await service.create(user.id, body)
    return success(service.to_out_dict(skill), "已创建")


@router.post("/builtins/{key}")
async def add_builtin_skill(
    key: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """把一个内置模板复制为用户自己的技能。"""
    service = SkillService(session)
    skill = await service.add_builtin(user.id, key)
    return success(service.to_out_dict(skill), "已添加")


@router.post("/optimize-prompt")
async def optimize_skill_prompt(
    body: OptimizeSkillPromptRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """技能任务提示词一键优化（专用元提示词，聚焦任务执行，不写人设）。"""
    service = SkillService(session)
    optimized = await service.optimize_prompt(user.id, body.prompt)
    return success({"optimized": optimized})


@router.put("/{skill_id}")
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = SkillService(session)
    skill = await service.update(user.id, skill_id, body)
    return success(service.to_out_dict(skill), "已保存")


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await SkillService(session).delete(user.id, skill_id)
    return success(message="已删除")
