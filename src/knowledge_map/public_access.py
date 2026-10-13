"""Visitor identity, request bounds, and admission policy for a single web worker."""

import hashlib
import ipaddress
import os
import re
import secrets
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from limits import RateLimitItemPerHour
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE_NAME = "source_guides_visitor"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class PublicSettings:
    enabled: bool = False
    public_origin: str | None = None
    trusted_proxies: tuple[str, ...] = ()
    active_questions: int = 1
    queued_questions: int = 2
    hourly_submissions: int = 3
    daily_submissions: int = 20
    max_question_characters: int = 4000
    max_body_bytes: int = 32768
    deadline_seconds: float = 240
    retention_days: int = 30

    def __post_init__(self) -> None:
        for name in (
            "active_questions",
            "hourly_submissions",
            "daily_submissions",
            "max_question_characters",
            "max_body_bytes",
            "deadline_seconds",
            "retention_days",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.queued_questions < 0:
            raise ValueError("queued_questions must be nonnegative")
        for proxy in self.trusted_proxies:
            ipaddress.ip_network(proxy)
        if self.enabled and self.public_origin is None:
            raise ValueError("CLOUD_PUBLIC_ORIGIN is required in public mode")
        if self.public_origin is not None:
            parsed = urlsplit(self.public_origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CLOUD_PUBLIC_ORIGIN must be an HTTPS origin without a path"
                )

    @classmethod
    def from_environment(cls) -> "PublicSettings":
        values = {
            "enabled": os.environ.get("CLOUD_PUBLIC_MODE", "0") == "1",
            "public_origin": os.environ.get("CLOUD_PUBLIC_ORIGIN") or None,
            "trusted_proxies": tuple(
                value.strip()
                for value in os.environ.get("CLOUD_TRUSTED_PROXIES", "").split(",")
                if value.strip()
            ),
        }
        for field, key in (
            ("active_questions", "CLOUD_ACTIVE_QUESTIONS"),
            ("queued_questions", "CLOUD_QUEUED_QUESTIONS"),
            ("hourly_submissions", "CLOUD_HOURLY_SUBMISSIONS"),
            ("daily_submissions", "CLOUD_DAILY_SUBMISSIONS"),
            ("max_question_characters", "CLOUD_MAX_QUESTION_CHARACTERS"),
            ("max_body_bytes", "CLOUD_MAX_BODY_BYTES"),
            ("retention_days", "CLOUD_GUIDE_RETENTION_DAYS"),
        ):
            if key in os.environ:
                values[field] = int(os.environ[key])
        if "CLOUD_QUESTION_DEADLINE_SECONDS" in os.environ:
            values["deadline_seconds"] = float(
                os.environ["CLOUD_QUESTION_DEADLINE_SECONDS"]
            )
        return cls(**values)


class VisitorAdmission:
    """Use the library's fixed-window counters for visitor and source IP quotas."""

    def __init__(self, settings: PublicSettings):
        self.limiter = FixedWindowRateLimiter(MemoryStorage())
        self.hourly = RateLimitItemPerHour(settings.hourly_submissions)

    def available(self, visitor: str, ip: str) -> bool:
        return all(
            self.limiter.test(self.hourly, kind, identity)
            for kind, identity in (("visitor", visitor), ("ip", ip))
        )

    def consume(self, visitor: str, ip: str) -> None:
        for kind, identity in (("visitor", visitor), ("ip", ip)):
            self.limiter.hit(self.hourly, kind, identity)


def visitor_id(request: Request) -> str:
    return request.scope["public_visitor_id"]


def source_ip(request: Request, settings: PublicSettings) -> str:
    peer = request.client.host if request.client else "unknown"
    networks = [ipaddress.ip_network(proxy) for proxy in settings.trusted_proxies]

    def trusted(value: str) -> bool:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        return any(address in network for network in networks)

    if trusted(peer):
        chain = request.headers.get("x-forwarded-for", "").split(",")
        for candidate in reversed(chain):
            candidate = candidate.strip()
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                return peer
            peer = candidate
            if not trusted(peer):
                break
    return peer


class PublicAccessMiddleware:
    def __init__(self, app: ASGIApp, settings: PublicSettings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
        except CookieError:
            cookies = SimpleCookie()
        token = cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else ""
        fresh = not _TOKEN.fullmatch(token)
        if fresh:
            token = secrets.token_urlsafe(32)
        scope["public_visitor_id"] = hashlib.sha256(token.encode()).hexdigest()

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                response_headers = list(message.get("headers", []))
                response_headers.append((b"cache-control", b"no-store"))
                if fresh:
                    cookie = SimpleCookie()
                    cookie[COOKIE_NAME] = token
                    cookie[COOKIE_NAME]["path"] = "/"
                    cookie[COOKIE_NAME]["secure"] = True
                    cookie[COOKIE_NAME]["httponly"] = True
                    cookie[COOKIE_NAME]["samesite"] = "Lax"
                    cookie[COOKIE_NAME]["max-age"] = (
                        self.settings.retention_days * 86400
                    )
                    response_headers.append(
                        (b"set-cookie", cookie.output(header="").strip().encode())
                    )
                message["headers"] = response_headers
            await send(message)

        if scope["method"] == "POST":
            expected = (
                self.settings.public_origin
                or f"{scope['scheme']}://{headers.get('host', '')}"
            )
            if headers.get("origin") != expected:
                await JSONResponse(
                    {"error": "Submit this request from this site's page."},
                    status_code=403,
                )(scope, receive, send_with_cookie)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.settings.max_body_bytes:
                    await JSONResponse(
                        {"error": "Request body is too large."}, status_code=413
                    )(scope, receive, send_with_cookie)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False
            original_receive = receive

            async def bounded_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await original_receive()

            receive = bounded_receive
        await self.app(scope, receive, send_with_cookie)
