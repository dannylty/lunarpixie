"""Tests for MemoryStore.purge_session_history (used by /clear)."""

from nanobot.agent.memory import MemoryStore


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
