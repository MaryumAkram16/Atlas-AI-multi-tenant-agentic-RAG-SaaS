"""Request ID, server span and access log for every request (pure ASGI, so
streamed SSE responses are not buffered)."""

import logging
import re
import time
import uuid

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.observability.context import request_id_var
from app.observability.tracing import safe_attrs, tracer

logger = logging.getLogger("app.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        method = scope["method"]
        status_holder = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        with tracer("atlas.api").start_as_current_span(
            f"HTTP {method}",
            kind=SpanKind.SERVER,
            attributes=safe_attrs({"http.request.method": method, "request_id": request_id}),
        ) as span:
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                route = scope.get("route")
                template = getattr(route, "path", None) or "unmatched"
                code = status_holder["code"]
                span.update_name(f"HTTP {method} {template}")
                span.set_attribute("http.route", template)
                span.set_attribute("http.response.status_code", code)
                if code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                if template != "/health":
                    logger.info("%s %s %s %sms", method, template, code, elapsed)
                request_id_var.reset(token)


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
