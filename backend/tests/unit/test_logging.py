import json
import logging

from app.observability.logging import JsonFormatter, RedactingFilter, redact


def test_redacts_tokens_keys_and_passwords():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"
    text = (
        f"Authorization: Bearer abc.def.ghi token={jwt} key sk-live-abcdefghijkl "
        "postgresql://atlas_api:supersecret@db:5432/postgres password=hunter2"
    )
    out = redact(text)
    for leaked in ("abc.def.ghi", jwt, "sk-live-abcdefghijkl", "supersecret", "hunter2"):
        assert leaked not in out
    assert "postgresql://atlas_api:[redacted]@db" in out


def test_json_formatter_and_filter():
    record = logging.LogRecord(
        "app", logging.INFO, __file__, 1, "user said Bearer zzz.yyy.xxx", None, None
    )
    assert RedactingFilter().filter(record)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "INFO" and "zzz.yyy.xxx" not in entry["message"]


def test_exceptions_log_type_only():
    try:
        raise ValueError("document text: confidential salaries")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["exception"] == "ValueError"
    assert "confidential" not in json.dumps(entry)
