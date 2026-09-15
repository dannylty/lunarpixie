"""The cron prompt must state the current date/time.

A daily job fires into a long-running session where the previous message may be
a day old. Without an authoritative clock in the prompt the agent reuses the
date it established earlier in the conversation and concludes nothing is due.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nanobot.cron.bound_runner import _cron_prompt_ref
from nanobot.utils.helpers import current_time_str
from nanobot.utils.prompt_templates import render_template


def _render(current_time: str) -> str:
    return render_template(
        "agent/cron_reminder.md",
        strip=True,
        message="Check overnight backups",
        current_time=current_time,
    )


def test_cron_prompt_states_the_current_datetime() -> None:
    tz = "Asia/Singapore"
    now = current_time_str(tz)
    prompt = _render(now)

    assert now in prompt
    today = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    assert today in prompt
    # The job itself must still be present.
    assert "Check overnight backups" in prompt


def test_cron_prompt_warns_against_reusing_an_earlier_date() -> None:
    """The clock is useless if the model treats it as passive metadata."""
    prompt = _render(current_time_str("UTC")).lower()
    assert "authoritative" in prompt
    assert "do not reuse a date" in prompt


@pytest.mark.parametrize("clock", ["2026-01-01 00:00", "2026-12-31 23:59"])
def test_cron_prompt_ref_ignores_the_clock(clock: str) -> None:
    """prompt_ref identifies the template, so it must not move with the clock.

    It is hashed from a fixed placeholder render; if it tracked the real time,
    every single run would report a different prompt version.
    """
    placeholder_ref = _cron_prompt_ref(_render("<current_time>"))
    other = _cron_prompt_ref(_render("<current_time>"))
    assert placeholder_ref["sha256"] == other["sha256"]
    # A real clock value produces a different hash, which is exactly why the
    # runner hashes the placeholder render instead of the sent prompt.
    assert _cron_prompt_ref(_render(clock))["sha256"] != placeholder_ref["sha256"]
    assert placeholder_ref["id"] == "cron.agent_turn.reminder"
