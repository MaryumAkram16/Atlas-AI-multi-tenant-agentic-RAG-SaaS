"""Structured, sanitized JSON logs.

Rules (CLAUDE.md): no document text, no tokens, no secrets. Code logs IDs,
statuses, counts and exception types only; the redaction filter below is a
safety net for anything that slips through (bearer tokens, JWTs, API keys,
passwords in connection strings).
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime

from opentelemetry import trace

from app.observability.context import request_id_var

_REDACTIONS = [
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[redacted-jwt]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[redacted-key]"),
    (re.compile(r"(?i)(api[_-]?key|password|secret|token)(\s*[=:]\s*)\S+"), r"\1\2[redacted]"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+):[^@\s]+@"), r"\1:[redacted]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if rid := request_id_var.get():
            entry["request_id"] = rid
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            entry["trace_id"] = format(ctx.trace_id, "032x")
            entry["span_id"] = format(ctx.span_id, "016x")
        if record.exc_info:
            # Exception type only: messages and tracebacks can contain user data.
            entry["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(entry)


def configure_logging(level: str, *, json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx logs full URLs at INFO (signed URLs, query strings): keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
