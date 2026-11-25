"""OpenTelemetry tracing for the API, agent and worker.

Spans carry IDs, counts, statuses and timings only, never document text,
questions, answers or tokens: `span()` drops attributes whose values are not
small scalars and `safe_attrs` truncates strings. Exporting is enabled only when
OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise spans stay in-process (logs still
carry trace IDs for correlation).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

_configured = False
MAX_ATTR_LEN = 120
# Attribute names that must never be recorded, whatever the value.
FORBIDDEN_ATTRS = frozenset({"question", "answer", "content", "text", "prompt", "token", "email"})


def setup_tracing(service_name: str, endpoint: str | None, exporter: SpanExporter | None = None):
    """Idempotent. `exporter` lets tests capture spans in memory."""
    global _configured
    if _configured and exporter is None:
        return trace.get_tracer_provider()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is None and endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    if exporter is not None:
        if exporter.__class__.__name__ == "InMemorySpanExporter":
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor

            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider) if not _configured else None
    _configured = True
    return provider


def tracer(name: str = "atlas"):
    return trace.get_tracer(name)


def safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key in FORBIDDEN_ATTRS or value is None:
            continue
        if isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value[:MAX_ATTR_LEN]
        else:
            out[key] = str(value)[:MAX_ATTR_LEN]
    return out


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name, attributes=safe_attrs(attrs)) as s:
        yield s


def inject_context() -> dict[str, str]:
    """W3C trace context of the current span, to carry across the job queue."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_context(carrier: dict[str, str] | None):
    return propagate.extract(carrier or {})
