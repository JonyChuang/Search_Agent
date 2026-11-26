"""MCP 服务配置路由：CRUD + 测试连接 + 同步工具 + 启停。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.agent.tools.mcp.execution import decide_approval, pending_approvals
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.mcp_schema import (
    MCPApprovalDecision,
    MCPServerCreate,
    MCPServerToggle,
    MCPServerUpdate,
    MCPToolPermissions,
)
from app.services.mcp_service import MCPService

router = APIRouter(prefix="/tools/mcp", tags=["mcp"])


@router.get("/approvals")
async def list_approvals(user: User = Depends(get_current_user)):
    return success(await pending_approvals(user.id))


@router.post("/approvals/{request_id}")
async def resolve_approval(request_id: uuid.UUID, body: MCPApprovalDecision, user: User = Depends(get_current_user)):
    return success(await decide_approval(user.id, request_id, body.approve))


@router.put("/{server_id}/permissions")
async def set_permissions(
    server_id: uuid.UUID, body: MCPToolPermissions, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    return success(service.to_out_dict(await service.set_permissions(user.id, server_id, body.tools)))


@router.get("")
async def list_servers(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    servers = await service.list_servers(user.id)
    return success([service.to_out_dict(s) for s in servers])


@router.post("")
async def create_server(
    body: MCPServerCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    server = await service.create(user.id, body)
    return success(service.to_out_dict(server), "已添加")


@router.put("/{server_id}")
async def update_server(
    server_id: uuid.UUID,
    body: MCPServerUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    server = await service.update(user.id, server_id, body)
    return success(service.to_out_dict(server), "已保存")


@router.delete("/{server_id}")
async def delete_server(
    server_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    await service.delete(user.id, server_id)
    return success(None, "已删除")


@router.post("/{server_id}/test")
async def test_server(
    server_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    ok, msg, tools = await service.test(user.id, server_id)
    return success({"success": ok, "message": msg, "tools": tools})


@router.post("/{server_id}/sync")
async def sync_server(
    server_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    server = await service.sync(user.id, server_id)
    return success(service.to_out_dict(server), "已同步")


@router.put("/{server_id}/toggle")
async def toggle_server(
    server_id: uuid.UUID,
    body: MCPServerToggle,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MCPService(session)
    server = await service.toggle(user.id, server_id, body.enabled)
    return success(service.to_out_dict(server), "已保存")
