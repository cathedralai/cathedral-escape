from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from escape_practice.errors import EscapePracticeError, LifecycleError
from escape_practice.leases import (
    RoomLease,
    _locked,
    clear_inflight,
    drop_lease,
    heartbeat,
    is_expired,
    load_inflight,
    load_leases,
    mark_inflight,
    put_lease,
    register_lease,
    write_inflight,
)
from escape_practice.lifecycle import InMemoryBroker, delete_session, tombstone_path
from escape_practice.sim import heartbeat_session, new_session, save, state_path
from escape_practice.store import state_dir as store_state_dir
from escape_practice.sweep import sweep_abandoned

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)
PLANTED = "2026-10-27T00:00:00+00:00"


def _session(*, ttl: int = 60, heartbeat_at: str = PLANTED):
    session = new_session(ttl_seconds=ttl)
    session.planted_at = PLANTED
    session.last_heartbeat_at = heartbeat_at
    save(session)
    return session


def test_abandoned_room_reaped() -> None:
    session = _session(ttl=60)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    report = sweep_abandoned(broker=broker, now=NOW)
    assert session.room_id in report.reaped
    assert not broker.exists(session.room_id)
    assert not state_path().is_file()
    tomb = json.loads(tombstone_path().read_text(encoding="utf-8"))
    assert tomb["reason"] == "ttl"
    assert tomb["policy"] == "always"


def test_heartbeat_keeps_room_alive() -> None:
    session = _session(ttl=60)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    heartbeat_session(session, now=datetime(2026, 10, 27, 0, 50, tzinfo=timezone.utc))
    save(session)
    still_alive = datetime(2026, 10, 27, 0, 50, 30, tzinfo=timezone.utc)
    report = sweep_abandoned(broker=broker, now=still_alive)
    assert session.room_id in report.kept
    assert broker.exists(session.room_id)
    assert state_path().is_file()


def test_restart_mid_sweep_resumes_inflight() -> None:
    session = _session(ttl=3600)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    mark_inflight(session.room_id)
    assert load_inflight() == [session.room_id]
    report = sweep_abandoned(broker=broker, now=datetime(2026, 10, 27, 0, 1, tzinfo=timezone.utc))
    assert session.room_id in report.resumed_inflight
    assert session.room_id in report.reaped
    assert not broker.exists(session.room_id)
    assert not state_path().is_file()
    assert load_inflight() == []


def test_double_delete_is_idempotent() -> None:
    session = _session(ttl=60)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    first = sweep_abandoned(broker=broker, now=NOW)
    second = sweep_abandoned(broker=broker, now=NOW)
    delete_session(session, reason="ttl", broker=broker)
    assert session.room_id in first.reaped
    assert session.room_id not in second.reaped
    assert not broker.exists(session.room_id)
    assert broker.delete_calls.count(session.room_id) >= 1


def test_sweeper_never_touches_non_escape_resources() -> None:
    session = _session(ttl=60)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    broker.create("customer-1", kind="customer_room")
    put_lease(
        RoomLease(
            room_id="customer-1",
            window_id="w-cust",
            kind="customer_room",
            guest="polaris",
            planted_at=PLANTED,
            last_heartbeat_at=PLANTED,
            ttl_seconds=1,
        )
    )
    decoy = store_state_dir() / "customer-secret.json"
    decoy.write_text("do-not-delete\n", encoding="utf-8")
    report = sweep_abandoned(broker=broker, now=NOW)
    assert session.room_id in report.reaped
    assert "customer-1" in report.skipped_non_escape
    assert broker.exists("customer-1")
    assert "customer-1" not in broker.delete_calls
    assert decoy.read_text(encoding="utf-8") == "do-not-delete\n"
    assert load_leases()["customer-1"].kind == "customer_room"


def test_orphan_hotel_escape_room_is_reaped() -> None:
    broker = InMemoryBroker()
    broker.create("orphan-escape")
    report = sweep_abandoned(broker=broker, now=NOW)
    assert "orphan-escape" in report.reaped
    assert not broker.exists("orphan-escape")


def test_fresh_session_without_lease_is_healed_not_reaped() -> None:
    session = new_session(ttl_seconds=3600)
    save(session)
    for room_id in list(load_leases()):
        if room_id == session.room_id:
            drop_lease(room_id)
    report = sweep_abandoned(now=datetime(2026, 10, 27, 0, 1, tzinfo=timezone.utc))
    assert session.room_id in report.kept or session.room_id in load_leases()
    assert state_path().is_file()


def test_corrupt_lease_store_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "leases.json"
    store.write_text("[]\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="corrupt"):
        load_leases(store)
    store.write_text("{}\n", encoding="utf-8")
    assert load_leases(store) == {}
    store.write_text('{"rooms": {"r1": "nope"}}\n', encoding="utf-8")
    with pytest.raises(LifecycleError, match="lease"):
        load_leases(store)


def test_drop_lease_missing_file_is_ok() -> None:
    drop_lease("never-registered")


def test_lease_store_parse_edges(tmp_path: Path) -> None:
    store = tmp_path / "leases.json"
    store.write_bytes(b"\xff\xff")
    with pytest.raises(LifecycleError, match="corrupt"):
        load_leases(store)
    store.write_text('{"rooms": null}\n', encoding="utf-8")
    assert load_leases(store) == {}
    store.write_text('{"rooms": []}\n', encoding="utf-8")
    with pytest.raises(LifecycleError, match="corrupt"):
        load_leases(store)
    missing = tmp_path / "absent.json"

    def _gone(fd: int) -> str:
        assert fd < 0
        return "empty"

    assert _locked(missing, _gone, create=False) == "empty"
    with pytest.raises(LifecycleError, match="ttl"):
        register_lease(room_id="r1", window_id="w1", ttl_seconds=0)
    inflight = tmp_path / "sweep-inflight.json"
    inflight.write_text('{"room_ids": [1]}\n', encoding="utf-8")
    with pytest.raises(LifecycleError, match="corrupt"):
        mark_inflight("room-z", path=inflight)
    with pytest.raises(LifecycleError, match="corrupt"):
        clear_inflight("room-z", path=inflight)
    clear_inflight("room-z", path=tmp_path / "no-inflight.json")
    write_inflight(["room-a"])
    again = mark_inflight("room-a")
    assert again == ["room-a"]


def test_expired_session_without_lease_is_reaped() -> None:
    session = _session(ttl=60)
    drop_lease(session.room_id)
    report = sweep_abandoned(now=NOW)
    assert session.room_id in report.reaped
    assert not state_path().is_file()


def test_deleted_session_file_does_not_crash_sweep() -> None:
    session = new_session()
    session.deleted = True
    save(session)
    report = sweep_abandoned(now=NOW)
    assert report.policy == "always"


def test_list_escape_rooms_failures_are_skipped() -> None:
    class NoList:
        def delete(self, room_id: str) -> None:
            return None

        def exists(self, room_id: str) -> bool:
            return False

    class Boom:
        def delete(self, room_id: str) -> None:
            return None

        def exists(self, room_id: str) -> bool:
            return False

        def list_escape_rooms(self) -> list[str]:
            raise EscapePracticeError("hotel list failed")

    class BadShape:
        def delete(self, room_id: str) -> None:
            return None

        def exists(self, room_id: str) -> bool:
            return False

        def list_escape_rooms(self) -> object:
            return ["ok", 1]

    assert sweep_abandoned(broker=NoList(), now=NOW).reaped == []
    assert sweep_abandoned(broker=Boom(), now=NOW).reaped == []
    assert sweep_abandoned(broker=BadShape(), now=NOW).reaped == []


def test_corrupt_session_is_ignored_on_delete() -> None:
    state_path().write_text("{not-json", encoding="utf-8")
    delete_session(None, reason="ttl", room_id="ghost-room")
    assert not load_leases()


def test_broker_other_guard_fail_closed() -> None:
    class Sticky:
        other = {"cust-1"}

        def delete(self, room_id: str) -> None:
            return None

        def exists(self, room_id: str) -> bool:
            return True

    with pytest.raises(LifecycleError, match="non-escape"):
        delete_session(None, reason="ttl", broker=Sticky(), room_id="cust-1")


def test_lease_field_validation_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "leases.json"
    store.write_text(
        json.dumps({"rooms": {"r1": {"room_id": "r1", "window_id": "w1", "kind": "", "guest": "escape-sealed"}}})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LifecycleError, match="kind"):
        load_leases(store)
    store.write_text(
        json.dumps({"rooms": {"r1": {"room_id": "r1", "window_id": "w1", "kind": "escape_room", "guest": ""}}})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LifecycleError, match="guest"):
        load_leases(store)
    store.write_text(
        json.dumps(
            {
                "rooms": {
                    "r1": {
                        "room_id": "r1",
                        "window_id": "w1",
                        "kind": "escape_room",
                        "guest": "escape-sealed",
                        "ttl_seconds": 0,
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LifecycleError, match="ttl"):
        load_leases(store)


def test_register_rejects_non_escape_lease() -> None:
    with pytest.raises(LifecycleError, match="escape-sealed"):
        register_lease(
            room_id="r1",
            window_id="w1",
            kind="customer_room",
            guest="polaris",
        )


def test_heartbeat_unknown_room_fails_closed() -> None:
    with pytest.raises(LifecycleError, match="no lease"):
        heartbeat("missing-room")


def test_heartbeat_refreshes_lease() -> None:
    session = _session(ttl=60)
    later = datetime(2026, 10, 27, 0, 30, tzinfo=timezone.utc)
    lease = heartbeat(session.room_id, now=later)
    assert lease.last_heartbeat_at == later.replace(microsecond=0).isoformat()


def test_sweep_empty_store_is_noop() -> None:
    report = sweep_abandoned(now=NOW)
    assert report.reaped == []
    assert report.policy == "always"


def test_corrupt_inflight_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "sweep-inflight.json"
    store.write_text("[]\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="corrupt"):
        load_inflight(store)


def test_is_expired_accepts_naive_now() -> None:
    lease = RoomLease(
        room_id="r1",
        window_id="w1",
        kind="escape_room",
        guest="escape-sealed",
        planted_at=PLANTED,
        last_heartbeat_at=PLANTED,
        ttl_seconds=60,
    )
    assert is_expired(lease, datetime(2026, 10, 27, 1, 0)) is True
    assert is_expired(lease, datetime(2026, 10, 27, 0, 0, 30, tzinfo=timezone.utc)) is False


def test_new_session_rejects_bad_ttl() -> None:
    with pytest.raises(EscapePracticeError, match="ttl"):
        new_session(ttl_seconds=0)
    with pytest.raises(EscapePracticeError, match="ttl"):
        new_session(ttl_seconds=99_999)


def test_write_and_clear_inflight_roundtrip() -> None:
    write_inflight(["room-a", "room-b"])
    assert load_inflight() == ["room-a", "room-b"]
    clear_inflight("room-a")
    assert load_inflight() == ["room-b"]
    clear_inflight("missing")
    assert load_inflight() == ["room-b"]


def test_heartbeat_rejects_non_escape_lease() -> None:
    put_lease(
        RoomLease(
            room_id="cust-room",
            window_id="w-cust",
            kind="customer_room",
            guest="polaris",
            planted_at=PLANTED,
            last_heartbeat_at=PLANTED,
            ttl_seconds=60,
        )
    )
    with pytest.raises(LifecycleError, match="escape-sealed"):
        heartbeat("cust-room")


def test_delete_other_room_does_not_unlink_live_session() -> None:
    session = _session(ttl=3600)
    broker = InMemoryBroker()
    broker.create(session.room_id)
    broker.create("other-escape")
    delete_session(session, reason="ttl", broker=broker, room_id="other-escape")
    assert state_path().is_file()
    assert broker.exists(session.room_id)
    assert not broker.exists("other-escape")
