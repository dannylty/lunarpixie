"""Tests for /clear session-key rotation (SessionManager key aliases)."""

from nanobot.session import SessionManager


def test_rotate_creates_alias_and_resolves(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    old = "telegram:123"
    new_key = manager.rotate_session_key(old)
    assert new_key != old
    assert manager.resolve_key(old) == new_key
    assert manager.resolve_key(new_key) == new_key
    # Traffic still deriving the retired key lands on the fresh session.
    fresh = manager.get_or_create(old)
    assert fresh.key == new_key
    assert fresh.messages == []


def test_rotation_chain_resolves_transitively(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    a = "telegram:123"
    b = manager.rotate_session_key(a)
    c = manager.rotate_session_key(b)
    assert manager.resolve_key(a) == c
    assert manager.get_or_create(a).key == c


def test_rotation_survives_restart(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    old = "telegram:123"
    new_key = manager.rotate_session_key(old)
    reloaded = SessionManager(tmp_path)
    assert reloaded.resolve_key(old) == new_key
    assert reloaded.get_or_create(old).key == new_key


def test_rotate_preserves_retired_session_file(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    old = "telegram:123"
    session = manager.get_or_create(old)
    session.add_message("user", "hello")
    manager.save(session)
    new_key = manager.rotate_session_key(old)

    # The live (rotated) session starts empty...
    assert manager.get_or_create(old).key == new_key
    assert manager.get_or_create(old).messages == []
    # ...while the retired episode's file keeps its history on disk.
    old_payload = manager.read_session_file(old)
    assert old_payload is not None
    assert old_payload["messages"][0]["content"] == "hello"


def test_invalidate_resolves_aliases(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    old = "telegram:123"
    new_key = manager.rotate_session_key(old)
    live = manager.get_or_create(old)
    assert manager.get_cached(new_key) is live
    manager.invalidate(old)  # raw/retired key
    assert manager.get_cached(new_key) is None
    assert manager.get_cached(old) is None
