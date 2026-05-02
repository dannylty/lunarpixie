"""Prometheus metrics for nanobot token usage tracking.

Exposes counters that Prometheus can scrape via the /metrics endpoint.
Metrics are in-memory only — Prometheus is the persistent store.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry as Registry, Counter, generate_latest

# ---------------------------------------------------------------------------
# Registry and counters
# ---------------------------------------------------------------------------

_registry = Registry()

TOKENS_TOTAL = Counter(
    "nanobot_tokens_total",
    "Total tokens processed by the agent",
    labelnames=["type", "model", "channel", "chat_id", "session_key"],
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_usage(
    *,
    usage: dict[str, int],
    model: str,
    channel: str,
    chat_id: str,
    session_key: str,
) -> None:
    """Record token usage from a single agent run.

    Args:
        usage: Dict with keys like 'prompt_tokens', 'completion_tokens', 'cached_tokens'.
        model: Model name (e.g. 'claude-sonnet-4-20250514').
        channel: Channel name (e.g. 'telegram', 'api', 'feishu').
        chat_id: Chat/user identifier.
        session_key: Session key (e.g. 'telegram:261694229').
    """
    labels = {
        "model": model,
        "channel": channel,
        "chat_id": str(chat_id),
        "session_key": session_key,
    }

    prompt = usage.get("prompt_tokens", 0)
    if prompt:
        TOKENS_TOTAL.labels(**labels, type="prompt").inc(prompt)

    completion = usage.get("completion_tokens", 0)
    if completion:
        TOKENS_TOTAL.labels(**labels, type="completion").inc(completion)

    cached = usage.get("cached_tokens", 0)
    if cached:
        TOKENS_TOTAL.labels(**labels, type="cached").inc(cached)


def generate_metrics() -> bytes:
    """Return Prometheus-formatted metrics for the /metrics endpoint."""
    return generate_latest(_registry)
