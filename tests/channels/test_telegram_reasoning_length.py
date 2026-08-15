"""Tests that streamed reasoning never exceeds Telegram's message limit.

Reasoning is rendered into an expandable blockquote and edited in place as
the model thinks. The blockquote used to be built straight from the whole
accumulated buffer, so a long thought stream produced an edit larger than
Telegram's 4096-character cap and the API rejected the whole edit with
``Message_too_long`` -- the reasoning block then froze at whatever partial
text had last fit, for the rest of the turn.

Unlike an answer, reasoning is not split across messages: it is a live view
of one turn, so the tail is kept and the head replaced with a marker.
"""

from __future__ import annotations

import pytest

from nanobot.channels.telegram.runtime import (
    TELEGRAM_HTML_MAX_LEN,
    _REASONING_ELISION_MARKER,
    _reasoning_to_telegram_blockquote,
    _tool_hint_to_telegram_blockquote,
)


def test_short_reasoning_is_untouched() -> None:
    """Anything that already fits must render exactly as before the fix."""
    text = "Thinking about the user's question.\nStep 1: read the file."
    assert _reasoning_to_telegram_blockquote(text) == _tool_hint_to_telegram_blockquote(text)


def test_empty_reasoning_renders_empty() -> None:
    assert _reasoning_to_telegram_blockquote("") == ""


def test_long_reasoning_is_capped() -> None:
    """The regression: a trace far past the limit still produces a legal edit."""
    text = "The user wants me to reason at length. " * 500  # ~19k chars
    html = _reasoning_to_telegram_blockquote(text)

    assert len(html) <= TELEGRAM_HTML_MAX_LEN
    assert _REASONING_ELISION_MARKER.strip() in html
    # The *tail* is what survives -- the most recent thinking, not the oldest.
    assert html.rstrip().endswith("at length. </blockquote>")


def test_cap_is_measured_after_html_escaping() -> None:
    """Escaping expands text, so a raw-character budget would still overflow.

    Every ``&`` becomes ``&amp;``: a 5x expansion. Budgeting on raw length
    would emit ~4096 raw chars and blow past the limit once rendered.
    """
    html = _reasoning_to_telegram_blockquote("&" * 20000)

    assert len(html) <= TELEGRAM_HTML_MAX_LEN
    assert "&amp;" in html
    assert "&&" not in html  # nothing escaped the escaper


@pytest.mark.parametrize("length", [TELEGRAM_HTML_MAX_LEN - 1, TELEGRAM_HTML_MAX_LEN,
                                    TELEGRAM_HTML_MAX_LEN + 1])
def test_boundary_lengths_stay_legal(length: int) -> None:
    """No off-by-one at the point where truncation kicks in."""
    html = _reasoning_to_telegram_blockquote("x" * length)
    assert len(html) <= TELEGRAM_HTML_MAX_LEN


def test_result_is_a_well_formed_blockquote() -> None:
    """A truncated tail must not lose the wrapper Telegram parses."""
    html = _reasoning_to_telegram_blockquote("reasoning " * 2000)
    assert html.startswith("<blockquote expandable>")
    assert html.endswith("</blockquote>")
    assert html.count("<blockquote") == 1
    assert html.count("</blockquote>") == 1
