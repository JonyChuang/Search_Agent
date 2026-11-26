"""MCP 服务配置相关 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

TransportT = Literal["sse", "streamable_http"]
AuthTypeT = Literal["none", "bearer", "api_key"]


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport: TransportT = "streamable_http"
    url: str = Field(min_length=1, max_length=512)
    auth_type: AuthTypeT = "none"
    # bearer: {"token": "明文"}；api_key: {"header": "X-Api-Key", "key": "明文"}
    auth_config: dict | None = None
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    transport: TransportT | None = None
    url: str | None = Field(default=None, max_length=512)
    auth_type: AuthTypeT | None = None
    # 不传表示不改认证；传则覆盖（明文，service 负责加密）
    auth_config: dict | None = None
    enabled: bool | None = None


class MCPServerToggle(BaseModel):
    enabled: bool


class MCPToolPermissions(BaseModel):
    tools: dict[str, Literal["read", "confirm", "reviewed_read"]] = Field(max_length=200)


Scalar = StrictStr | StrictInt | StrictBool | None


class ReviewedMCPRead(BaseModel):
    """Deployment configuration for an independently reviewed read-only MCP tool."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    server_id: uuid.UUID
    url: str
    tool: str = Field(min_length=1, max_length=128)
    schema_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime
    arguments: dict[str, list[Scalar]] = Field(max_length=12)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("Invalid MCP URL") from None
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("Reviewed MCP endpoints require an exact HTTPS URL without credentials or query")
        return str(url)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value):
        if value.utcoffset() is None:
            raise ValueError("A reviewed MCP grant requires a timezone-aware expiry")
        return value

    @field_validator("arguments")
    @classmethod
    def limit_arguments(cls, value):
        for key, choices in value.items():
            if not 1 <= len(key) <= 80 or not 1 <= len(choices) <= 30 or any(
                isinstance(choice, str) and len(choice) > 180 for choice in choices
            ):
                raise ValueError("Reviewed MCP parameters require a small, explicit list of values")
        return value

    def accepts(self, arguments: dict) -> bool:
        return arguments.keys() == self.arguments.keys() and all(
            any(type(value) is type(allowed) and value == allowed for allowed in self.arguments[key])
            for key, value in arguments.items()
        )


class MCPApprovalDecision(BaseModel):
    approve: bool


class MCPToolMeta(BaseModel):
    name: str
    description: str = ""


class MCPServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transport: str
    url: str
    auth_type: str
    auth_masked: str  # 认证信息掩码，不返回明文
    enabled: bool
    status: str
    last_error: str | None
    tools_cache: list[MCPToolMeta] | None
    synced_at: datetime | None
    created_at: datetime


class MCPTestResult(BaseModel):
    success: bool
    message: str
    tools: list[MCPToolMeta] = Field(default_factory=list)
