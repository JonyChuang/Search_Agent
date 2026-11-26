"""把 MCPServer 配置行转成 langchain-mcp-adapters 的 connection dict。

负责：解密认证信息 → 拼 headers；SSRF 校验（禁内网地址）；按传输类型组装。
"""
import asyncio
import ipaddress
import socket
from functools import partial

import httpcore
import httpx
from httpcore import AnyIOBackend

from app.core.security import decrypt_secret
from app.models.mcp_server_model import (
    AUTH_API_KEY,
    AUTH_BEARER,
    TRANSPORT_SSE,
    MCPServer,
)

# 连接 / 读取超时（秒）
CONNECT_TIMEOUT = 15.0
SSE_READ_TIMEOUT = 60.0


def is_safe_url(url: str) -> bool:
    """Validate input before connecting. Address validation is repeated at socket creation."""
    try:
        parsed = httpx.URL(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.raw_host) and not parsed.userinfo and not parsed.fragment
    except (httpx.InvalidURL, ValueError):
        return False


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not (address.is_multicast or address.is_reserved)


class PublicNetworkBackend(AnyIOBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        async with asyncio.timeout(timeout):
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(info[4][0] for info in infos))
            if not addresses or not all(_public_address(ip) for ip in addresses):
                raise httpcore.ConnectError("MCP endpoint has a non-public address")
            for ip in addresses:
                try:
                    # Pass the validated IP to the socket. The pool retains the original origin for Host and TLS.
                    return await super().connect_tcp(ip, port, timeout, local_address, socket_options)
                except httpcore.ConnectError:
                    continue
            raise httpcore.ConnectError("Unable to connect to the MCP endpoint")


def _origin(url: httpx.URL):
    return url.scheme, url.raw_host, url.port or (443 if url.scheme == "https" else 80)


def _client_for_origin(origin, headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    # HTTPX 0.28 does not expose a network backend in its transport constructor.
    transport._pool = httpcore.AsyncConnectionPool(network_backend=PublicNetworkBackend())

    async def check_origin(request: httpx.Request) -> None:
        if request.url.userinfo or _origin(request.url) != origin:
            raise httpx.RequestError("MCP requests must remain on the configured origin", request=request)

    return httpx.AsyncClient(
        headers=headers, timeout=timeout or httpx.Timeout(30.0), auth=auth, transport=transport,
        follow_redirects=False, trust_env=False, event_hooks={"request": [check_origin]},
    )


def _build_headers(server: MCPServer) -> dict[str, str]:
    """按认证类型解密并拼出请求头。"""
    cfg = server.auth_config or {}
    if server.auth_type == AUTH_BEARER:
        token = cfg.get("token")
        if token:
            return {"Authorization": f"Bearer {decrypt_secret(token)}"}
    elif server.auth_type == AUTH_API_KEY:
        header_name = cfg.get("header") or "X-API-Key"
        key = cfg.get("key")
        if key:
            return {header_name: decrypt_secret(key)}
    return {}


def build_connection(server: MCPServer) -> dict:
    """MCPServer → 官方 connection dict。URL 不安全时抛 ValueError。"""
    if not is_safe_url(server.url):
        raise ValueError("不允许访问该地址（内网/非法 URL）")

    headers = _build_headers(server)
    if headers and httpx.URL(server.url).scheme != "https":
        raise ValueError("Authenticated MCP servers require HTTPS")
    transport = "sse" if server.transport == TRANSPORT_SSE else "streamable_http"
    conn: dict = {
        "transport": transport,
        "url": server.url,
        "httpx_client_factory": partial(_client_for_origin, _origin(httpx.URL(server.url))),
    }
    if headers:
        conn["headers"] = headers
    if transport == "sse":
        conn["timeout"] = CONNECT_TIMEOUT
        conn["sse_read_timeout"] = SSE_READ_TIMEOUT
    return conn
