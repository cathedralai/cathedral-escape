"""Delete-always is hard (T4). Finish, abandon, retry, or TTL always deletes.

Soft / best-effort language is a fail. Delete is idempotent. Neighbour canaries
(P2) follow the same rule when they exist: the broker double records them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from .errors import LifecycleError
from .freshness import now_iso
from .leases import drop_lease
from .sim import Session, load, new_session, save
from .store import atomic_write, state_dir, state_path

DeleteReason = Literal["finish", "abandon", "retry", "ttl"]
HARD_DELETE_POLICY = "always"
_ALLOWED_DELETE_REASONS: frozenset[str] = frozenset(("finish", "abandon", "retry", "ttl"))


def assert_delete_always(policy: object) -> None:
    if policy != HARD_DELETE_POLICY:
        raise LifecycleError("delete-always is hard; soft or best-effort is a fail")


class RoomBroker(Protocol):
    """Control-plane delete contract. The live broker is a test double here."""

    def delete(self, room_id: str) -> None:
        """Must delete or raise. Returning without deleting is a fail."""

    def exists(self, room_id: str) -> bool:
        ...

    def list_escape_rooms(self) -> list[str]:
        ...


@dataclass
class InMemoryBroker:
    """Test double. No network, no capacity, no spend."""

    rooms: set[str] = field(default_factory=set)
    other: set[str] = field(default_factory=set)
    delete_calls: list[str] = field(default_factory=list)

    def create(self, room_id: str, *, kind: str = "escape_room") -> None:
        if kind != "escape_room":
            self.other.add(room_id)
            return
        self.rooms.add(room_id)

    def delete(self, room_id: str) -> None:
        if room_id in self.other:
            raise LifecycleError("refusing to delete non-escape-room resource")
        self.delete_calls.append(room_id)
        self.rooms.discard(room_id)

    def exists(self, room_id: str) -> bool:
        return room_id in self.rooms or room_id in self.other

    def list_escape_rooms(self) -> list[str]:
        return sorted(self.rooms)


def tombstone_path() -> Path:
    return state_dir() / "deleted.json"


def _write_tombstone(session: Session, reason: DeleteReason) -> None:
    path = tombstone_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        json.dumps(
            {
                "room_id": session.room_id,
                "window_id": session.window_id,
                "reason": reason,
                "deleted_at": now_iso(),
                "policy": HARD_DELETE_POLICY,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _broker_delete(broker: RoomBroker | None, room_id: str) -> None:
    if broker is None:
        return
    broker.delete(room_id)
    if room_id in getattr(broker, "other", set()):
        raise LifecycleError("refusing to delete non-escape-room resource")
    if broker.exists(room_id):
        raise LifecycleError("broker delete returned without deleting; fail closed")


def delete_session(
    session: Session | None = None,
    *,
    reason: DeleteReason,
    path: Path | None = None,
    broker: RoomBroker | None = None,
    room_id: str | None = None,
) -> None:
    """Idempotent hard delete of the practice room (and broker double, if given)."""
    if reason not in _ALLOWED_DELETE_REASONS:
        raise LifecycleError(f"unknown delete reason {reason!r}")
    target = path or state_path()
    if session is None and target.is_file():
        try:
            session = load(target)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
            session = None
    if session is not None and room_id is not None and session.room_id != room_id:
        _broker_delete(broker, room_id)
        drop_lease(room_id)
        return
    rid = session.room_id if session is not None else room_id
    if rid:
        _broker_delete(broker, rid)
        if session is not None:
            _write_tombstone(session, reason)
            session.deleted = True
            session.delete_reason = reason
        drop_lease(rid)
    if session is not None and target.is_file():
        target.unlink()
    # Missing file is success (idempotent).


def finish(session: Session | None = None, *, broker: RoomBroker | None = None) -> None:
    delete_session(session, reason="finish", broker=broker)


def abandon(session: Session | None = None, *, broker: RoomBroker | None = None) -> None:
    delete_session(session, reason="abandon", broker=broker)


def retry(session: Session | None = None, *, broker: RoomBroker | None = None) -> Session:
    delete_session(session, reason="retry", broker=broker)
    fresh = new_session()
    save(fresh)
    if broker is not None:
        broker.create(fresh.room_id)
    return fresh
