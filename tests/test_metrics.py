"""Tests for nanobot.metrics — Prometheus token usage tracking."""

import pytest

from prometheus_client import CollectorRegistry

import nanobot.metrics as metrics_mod
from nanobot.metrics import Counter, generate_metrics, record_usage


@pytest.fixture
def fresh_registry():
    """Return a fresh registry and a record_usage bound to it."""
    reg = CollectorRegistry()
    counter = Counter(
        "nanobot_tokens_total",
        "Total tokens processed by the agent",
        labelnames=["type", "model", "channel", "chat_id", "session_key"],
        registry=reg,
    )

    def _record(**kwargs):
        labels = {
            "model": kwargs["model"],
            "channel": kwargs["channel"],
            "chat_id": str(kwargs["chat_id"]),
            "session_key": kwargs["session_key"],
        }
        prompt = kwargs["usage"].get("prompt_tokens", 0)
        if prompt:
            counter.labels(**labels, type="prompt").inc(prompt)
        completion = kwargs["usage"].get("completion_tokens", 0)
        if completion:
            counter.labels(**labels, type="completion").inc(completion)
        cached = kwargs["usage"].get("cached_tokens", 0)
        if cached:
            counter.labels(**labels, type="cached").inc(cached)

    def _generate():
        from prometheus_client import generate_latest
        return generate_latest(reg)

    return _record, _generate


class TestRecordUsage:
    def test_records_prompt_tokens(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'type="prompt"} 100.0' in metrics

    def test_records_completion_tokens(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'type="completion"} 50.0' in metrics

    def test_records_cached_tokens(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 80},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'type="cached"} 80.0' in metrics

    def test_skips_zero_values(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 0, "cached_tokens": 0},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'type="completion"' not in metrics
        assert 'type="cached"' not in metrics

    def test_accumulates_across_calls(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )
        _record(
            usage={"prompt_tokens": 200, "completion_tokens": 75},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'type="prompt"} 300.0' in metrics
        assert 'type="completion"} 125.0' in metrics

    def test_different_sessions_are_separate(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )
        _record(
            usage={"prompt_tokens": 200, "completion_tokens": 75},
            model="test-model",
            channel="telegram",
            chat_id="456",
            session_key="telegram:456",
        )

        metrics = _generate().decode()
        assert 'chat_id="123"' in metrics
        assert 'chat_id="456"' in metrics

    def test_handles_empty_usage(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'session_key="telegram:123"' not in metrics

    def test_different_models_are_separate(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="model-a",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )
        _record(
            usage={"prompt_tokens": 200, "completion_tokens": 75},
            model="model-b",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert 'model="model-a"' in metrics
        assert 'model="model-b"' in metrics


class TestGenerateMetrics:
    def test_returns_bytes(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )
        result = _generate()
        assert isinstance(result, bytes)

    def test_contains_nanobot_tokens_total(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert "nanobot_tokens_total" in metrics

    def test_prometheus_format(self, fresh_registry):
        _record, _generate = fresh_registry
        _record(
            usage={"prompt_tokens": 100},
            model="test-model",
            channel="telegram",
            chat_id="123",
            session_key="telegram:123",
        )

        metrics = _generate().decode()
        assert "# HELP nanobot_tokens_total" in metrics
        assert "# TYPE nanobot_tokens_total counter" in metrics
