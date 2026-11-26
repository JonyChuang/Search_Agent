"""Deployment-reviewed, narrowly scoped grants for read-only external MCP tools."""

from datetime import datetime, timezone
import httpx

from app.config import settings
from app.schemas.mcp_schema import ReviewedMCPRead


def reviewed_read_for(server, tool: str, digest: str | None) -> ReviewedMCPRead | None:
    if not settings.mcp_reviewed_reads or not digest or not server.enabled:
        return None
    if server.transport != "streamable_http" or server.auth_type != "none" or server.auth_config:
        return None
    try:
        url = str(httpx.URL(server.url))
    except httpx.InvalidURL:
        return None
    now = datetime.now(timezone.utc)
    return next((grant for grant in settings.mcp_reviewed_reads
                 if (grant.user_id, grant.server_id, grant.url, grant.tool, grant.schema_digest)
                 == (server.user_id, server.id, url, tool, digest)
                 and grant.expires_at > now), None)
