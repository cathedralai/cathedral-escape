from __future__ import annotations

import pytest

from escape_practice.errors import LifecycleError
from escape_practice.lifecycle import (
    HARD_DELETE_POLICY,
    InMemoryBroker,
    abandon,
    assert_delete_always,
    delete_session,
    finish,
    retry,
    tombstone_path,
)
from escape_practice.sim import load, new_session, save, state_path


def test_soft_delete_policy_is_a_fail() -> None:
    with pytest.raises(LifecycleError, match="hard"):
        assert_delete_always("best-effort")
    with pytest.raises(LifecycleError, match="hard"):
        assert_delete_always("soft")
    assert_delete_always(HARD_DELETE_POLICY)


def test_finish_always_deletes() -> None:
    session = new_session()
    save(session)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    finish(session, broker=broker)
    assert not state_path().is_file()
    assert not broker.exists(session.room_id)
    assert tombstone_path().is_file()
    with pytest.raises(FileNotFoundError):
        load()


def test_abandon_always_deletes() -> None:
    session = new_session()
    save(session)
    abandon(session)
    assert not state_path().is_file()


def test_delete_is_idempotent() -> None:
    session = new_session()
    save(session)
    delete_session(session, reason="finish")
    delete_session(session, reason="finish")
    delete_session(None, reason="abandon")
    assert not state_path().is_file()


def test_retry_deletes_then_plants_new_window() -> None:
    first = new_session()
    save(first)
    broker = InMemoryBroker()
    broker.create(first.room_id)
    second = retry(first, broker=broker)
    assert not broker.exists(first.room_id)
    assert broker.exists(second.room_id)
    assert second.window_id != first.window_id
    assert second.room_id != first.room_id
    loaded = load()
    assert loaded.window_id == second.window_id


def test_ttl_delete_reason_writes_tombstone() -> None:
    session = new_session()
    save(session)
    delete_session(session, reason="ttl")
    assert not state_path().is_file()
    assert tombstone_path().is_file()


def test_broker_refuses_non_escape_delete() -> None:
    broker = InMemoryBroker()
    broker.create("customer-1", kind="customer_room")
    with pytest.raises(LifecycleError, match="non-escape"):
        broker.delete("customer-1")
    assert broker.exists("customer-1")


def test_broker_delete_is_recorded() -> None:
    broker = InMemoryBroker()
    broker.create("room-a")
    broker.delete("room-a")
    broker.delete("room-a")
    assert broker.delete_calls == ["room-a", "room-a"]
    assert not broker.exists("room-a")
