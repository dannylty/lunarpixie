"""Tests for MemoryStore.purge_session_history (used by /clear).

Also covers the session-key tagging contract shared by the history writers.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_new
from nanobot.command.router import CommandContext
from nanobot.session.manager import SessionManager


def test_purge_removes_only_matching_session(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.append_history("keep other", session_key="telegram:111")
    store.append_history("purge me", session_key="telegram:222")
    store.append_history("keep unscoped")
    store.append_history("purge me too", session_key="telegram:222")

    removed = store.purge_session_history("telegram:222")

    assert removed == 2
    contents = [e["content"] for e in store._read_entries()]
    assert contents == ["keep other", "keep unscoped"]


def test_purge_keeps_cursor_monotonic(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    for i in range(3):
        store.append_history(f"entry {i}", session_key="telegram:222")
    assert store._next_cursor() == 4

    removed = store.purge_session_history("telegram:222")

    assert removed == 3
    assert store._read_entries() == []
    # Cursor counter must not regress after the purge.
    assert store._next_cursor() == 4


def test_purge_noop_returns_zero(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.append_history("keep", session_key="telegram:111")
    assert store.purge_session_history("telegram:999") == 0
    assert [e["content"] for e in store._read_entries()] == ["keep"]


class TestHistoryEntriesUseResolvedSessionKey:
    """History entries must be tagged with the resolved session key.

    ``ctx.key`` is the routed key and resolves through rotation aliases, so
    tagging with it wrote entries that no session-scoped reader could match:
    ``read_recent_history_for_prompt`` filters on the resolved key and
    ``purge_session_history`` deletes by it.
    """

    @pytest.mark.asyncio
    async def test_cmd_new_archives_under_resolved_key(self, tmp_path: Path):
        sessions = SessionManager(tmp_path)

        routed = "telegram:111"
        session = sessions.get_or_create(routed)
        session.add_message("user", "hello")
        sessions.save(session)

        # Force routed != resolved so a regression is observable.
        resolved = sessions.rotate_session_key(routed)
        moved = sessions.get_or_create(routed)
        moved.add_message("user", "hello again")
        sessions.save(moved)
        assert sessions.resolve_key(routed) == resolved

        archive = AsyncMock(return_value="summary")
        loop = SimpleNamespace(
            sessions=sessions,
            context=SimpleNamespace(memory=SimpleNamespace(purge_session_history=MagicMock())),
            consolidator=SimpleNamespace(archive=archive),
            _cancel_active_tasks=AsyncMock(return_value=0),
            runtime_for_session=MagicMock(return_value=MagicMock()),
            llm_runtime=MagicMock(return_value=MagicMock()),
            schedule_background=lambda coro: asyncio.ensure_future(coro),
        )

        msg = InboundMessage(
            channel="telegram", sender_id="user1", chat_id="111", content="/new",
        )
        ctx = CommandContext(msg=msg, session=None, key=routed, raw="/new", loop=loop)
        await cmd_new(ctx)
        await asyncio.sleep(0)  # let the scheduled archive coroutine run

        archive.assert_awaited_once()
        assert archive.await_args.kwargs["session_key"] == resolved
