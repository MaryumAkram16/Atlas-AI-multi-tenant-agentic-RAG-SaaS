"""OpenTelemetry spans across API, agent and worker, sharing one trace, with
no document text, questions or answers in span attributes."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import ask
from tests.docs_helpers import drain, upload
from tests.files import sample

pytestmark = pytest.mark.db


@pytest.fixture
def spans():
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    yield exporter
    processor.shutdown()


def test_trace_spans_cover_api_agent_and_worker(docs_api, worker, spans):
    alice = USERS["alice"]
    resp = upload(docs_api, alice, ACME_ID, "refund.md", sample("acme/refund-policy-2026.md"))
    upload_trace = next(
        s.context.trace_id
        for s in spans.get_finished_spans()
        if s.name == "HTTP POST /v1/organizations/{org_id}/documents"
    )
    drain(worker)
    question = "How many days do customers have to request a refund?"
    ask(docs_api, alice, ACME_ID, question)
    finished = spans.get_finished_spans()
    names = {s.name for s in finished}

    assert {
        "HTTP POST /v1/organizations/{org_id}/chat",
        "retrieval.hybrid",
        "llm.generate",
        "agent.retrieve_documents",
        "agent.verify_citations",
    } <= names
    assert {
        "worker.job ingest",
        "ingest.parse",
        "ingest.chunk",
        "ingest.embed",
        "ingest.index",
        "ingest.publish",
    } <= names
    # The worker continues the upload request's trace through the job queue.
    job = next(s for s in finished if s.name == "worker.job ingest")
    assert job.context.trace_id == upload_trace
    assert resp.status_code == 202

    # Sanitized: no question, answer or document text in any attribute.
    corpus = sample("acme/refund-policy-2026.md").decode()
    forbidden = [question, "7 days of purchase", "Customers may request"]
    for s in finished:
        for value in (s.attributes or {}).values():
            text = str(value)
            assert not any(f in text for f in forbidden), (s.name, text)
            assert text not in corpus or len(text) < 40, (s.name, text)
