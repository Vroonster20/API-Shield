"""Fixed-destination HTTP forwarding. No shared caller cookie state."""

from __future__ import annotations

import http.cookiejar
from dataclasses import dataclass

import httpx

from .contracts import RegisteredUpstream

HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}
ADMIN_COOKIES = {b"__Host-shield_session", b"shield_dev_session"}


class RejectCookies(http.cookiejar.DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


class ProxyProblem(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status


def connection_tokens(headers: list[tuple[bytes, bytes]]) -> set[bytes]:
    return {
        token.strip().lower()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.split(b",")
        if token.strip()
    }


def request_headers(headers, *, upstream, public_host, public_scheme, client_ip, request_id):
    tokens = connection_tokens(headers)
    if tokens & {b"authorization", b"cookie", b"host", b"x-shield-client-ip"}:
        raise ProxyProblem("BAD_REQUEST", 400)
    result = []
    for key, value in headers:
        lower = key.lower()
        if lower in HOP | tokens | {
            b"host",
            b"content-length",
            b"expect",
            b"forwarded",
            b"x-real-ip",
            b"x-request-id",
        }:
            continue
        if lower.startswith((b"x-forwarded-", b"x-shield-", b"x-user-")):
            continue
        if lower == b"cookie":
            parts = [
                p.strip()
                for p in value.split(b";")
                if p.strip() and p.strip().split(b"=", 1)[0] not in ADMIN_COOKIES
            ]
            if not parts:
                continue
            value = b"; ".join(parts)
        result.append((key, value))
    result.extend(
        [
            (b"x-forwarded-for", client_ip.encode("ascii")),
            (b"x-forwarded-host", public_host.encode("ascii")),
            (b"x-forwarded-proto", public_scheme.encode("ascii")),
            (b"x-request-id", request_id.encode("ascii")),
            (b"via", b"1.1 shield-api"),
        ]
    )
    return result


def response_headers(headers, request_id):
    tokens = connection_tokens(headers)
    return [(k, v) for k, v in headers if k.lower() not in HOP | tokens | {b"x-request-id"}] + [
        (b"x-request-id", request_id.encode("ascii")),
        (b"via", b"1.1 shield-api"),
    ]


@dataclass(frozen=True)
class PreparedRequest:
    upstream: RegisteredUpstream
    method: str
    raw_path: bytes
    query: bytes
    headers: list[tuple[bytes, bytes]]
    body: bytes
    public_host: str
    public_scheme: str
    client_ip: str
    request_id: str


class Forwarder:
    def __init__(self, transport=None):
        self.client = httpx.AsyncClient(
            cookies=http.cookiejar.CookieJar(policy=RejectCookies()),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(10, connect=2, pool=0.1, write=10),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def forward(self, request: PreparedRequest) -> httpx.Response:
        target = httpx.URL(
            scheme=request.upstream.scheme,
            host=request.upstream.host,
            port=request.upstream.port,
            raw_path=request.raw_path + (b"?" + request.query if request.query else b""),
        )
        headers = request_headers(
            request.headers,
            upstream=request.upstream,
            public_host=request.public_host,
            public_scheme=request.public_scheme,
            client_ip=request.client_ip,
            request_id=request.request_id,
        )
        outbound = httpx.Request(request.method, target, headers=headers, content=request.body)
        try:
            return await self.client.send(outbound, stream=True, follow_redirects=False)
        except httpx.PoolTimeout:
            raise ProxyProblem("GATEWAY_BUSY", 503) from None
        except httpx.TimeoutException:
            raise ProxyProblem("UPSTREAM_TIMEOUT", 504) from None
        except httpx.HTTPError:
            raise ProxyProblem("UPSTREAM_UNAVAILABLE", 502) from None
