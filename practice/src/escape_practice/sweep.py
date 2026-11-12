"""TTL / heartbeat sweeper for abandoned Escape rooms.

Delete-always is hard (T4). Finish / abandon / retry still delete on the
trigger. This module reaps rooms that never get a trigger: client gone,
crash, walk-away. Idempotent. Restart resumes in-flight deletes. Never
deletes a resource that is not an escape-sealed room.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import DEFAULT_SWEEP_INTERVAL_SECONDS
from .errors import EscapePracticeError, LifecycleError
from .freshness import now_utc
from .leases import (
    RoomLease,
    clear_inflight,
    drop_lease,
    is_expired,
    load_inflight,
    load_leases,
    mark_inflight,
    register_lease,
)
from .lifecycle import HARD_DELETE_POLICY, DeleteReason, RoomBroker, delete_session
from .placement import ESCAPE_GUEST
from .sim import load
from .store import state_path

DEFAULT_INTERVAL_SECONDS = DEFAULT_SWEEP_INTERVAL_SECONDS


@dataclass
class SweepReport:
    reaped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped_non_escape: list[str] = field(default_factory=list)
    resumed_inflight: list[str] = field(default_factory=list)
    policy: str = HARD_DELETE_POLICY

    def to_dict(self) -> dict[str, Any]:
        return {
            "reaped": list(self.reaped),
            "kept": list(self.kept),
            "skipped_non_escape": list(self.skipped_non_escape),
            "resumed_inflight": list(self.resumed_inflight),
            "policy": self.policy,
        }


def _session_lease_if_present() -> RoomLease | None:
    try:
        session = load()
    except FileNotFoundError:
        return None
    except (EscapePracticeError, OSError, KeyError, TypeError, ValueError):
        return None
    return RoomLease(
        room_id=session.room_id,
        window_id=session.window_id,
        kind="escape_room",
        guest=ESCAPE_GUEST,
        planted_at=session.planted_at,
        last_heartbeat_at=session.last_heartbeat_at,
        ttl_seconds=session.ttl_seconds,
    )


def _reap_room(
    room_id: str,
    *,
    broker: RoomBroker | None,
    reason: DeleteReason = "ttl",
) -> None:
    session = None
    if state_path().is_file():
        try:
            loaded = load()
        except (FileNotFoundError, EscapePracticeError, OSError, KeyError, TypeError, ValueError):
            loaded = None
        if loaded is not None and loaded.room_id == room_id:
            session = loaded
    delete_session(session, reason=reason, broker=broker, room_id=room_id)


def _list_escape_rooms(broker: RoomBroker | None) -> list[str]:
    if broker is None:
        return []
    lister = getattr(broker, "list_escape_rooms", None)
    if not callable(lister):
        return []
    try:
        found = lister()
    except (EscapePracticeError, OSError, KeyError, TypeError, ValueError):
        return []
    if not isinstance(found, list) or any(not isinstance(x, str) for x in found):
        return []
    return list(found)


def sweep_abandoned(
    *,
    broker: RoomBroker | None = None,
    now: datetime | None = None,
    leases_file: Path | None = None,
    inflight_file: Path | None = None,
) -> SweepReport:
    """Reap expired and in-flight escape rooms. Safe to call twice and after crash."""
    moment = now if now is not None else now_utc()
    report = SweepReport()
    seen: set[str] = set()

    inflight = load_inflight(inflight_file)
    for room_id in list(inflight):
        _reap_room(room_id, broker=broker, reason="ttl")
        clear_inflight(room_id, inflight_file)
        report.resumed_inflight.append(room_id)
        report.reaped.append(room_id)
        seen.add(room_id)

    leases = load_leases(leases_file)
    session_lease = _session_lease_if_present()
    if session_lease is not None and session_lease.room_id not in leases:
        if is_expired(session_lease, moment):
            leases[session_lease.room_id] = session_lease
        else:
            register_lease(
                room_id=session_lease.room_id,
                window_id=session_lease.window_id,
                planted_at=session_lease.planted_at,
                last_heartbeat_at=session_lease.last_heartbeat_at,
                ttl_seconds=session_lease.ttl_seconds,
                path=leases_file,
            )
            leases[session_lease.room_id] = session_lease

    for room_id, lease in list(leases.items()):
        if room_id in seen:
            continue
        if not lease.is_escape_room():
            report.skipped_non_escape.append(room_id)
            continue
        if not is_expired(lease, moment):
            report.kept.append(room_id)
            continue
        mark_inflight(room_id, inflight_file)
        _reap_room(room_id, broker=broker, reason="ttl")
        drop_lease(room_id, leases_file)
        clear_inflight(room_id, inflight_file)
        report.reaped.append(room_id)
        seen.add(room_id)

    for room_id in _list_escape_rooms(broker):
        if room_id in seen or room_id in leases:
            continue
        mark_inflight(room_id, inflight_file)
        _reap_room(room_id, broker=broker, reason="ttl")
        drop_lease(room_id, leases_file)
        clear_inflight(room_id, inflight_file)
        report.reaped.append(room_id)
        seen.add(room_id)

    return report
