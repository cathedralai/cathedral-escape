"""Persisted escape-room leases. Heartbeat + TTL are the live-room contract.

Only `kind=escape_room` / `guest=escape-sealed` leases are first-class. Foreign
rows may sit in the same file so a sweeper restart can prove it skipped them.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from . import DEFAULT_TTL_SECONDS
from .errors import LifecycleError
from .freshness import MAX_TTL_SECONDS, now_iso, now_utc, parse_iso8601
from .ids import require_safe_id
from .placement import ESCAPE_GUEST
from .store import state_dir

ESCAPE_ROOM_KIND = "escape_room"
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}
T = TypeVar("T")


@dataclass
class RoomLease:
    room_id: str
    window_id: str
    kind: str
    guest: str
    planted_at: str
    last_heartbeat_at: str
    ttl_seconds: int

    def is_escape_room(self) -> bool:
        return self.kind == ESCAPE_ROOM_KIND and self.guest == ESCAPE_GUEST


def leases_path() -> Path:
    return state_dir() / "leases.json"


def inflight_path() -> Path:
    return state_dir() / "sweep-inflight.json"


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _parse_object(raw: bytes, *, label: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"corrupt {label} store; fail closed") from exc
    if not isinstance(loaded, dict):
        raise LifecycleError(f"corrupt {label} store; fail closed")
    return loaded


def _locked(path: Path, fn: Callable[[int], T], *, create: bool = True) -> T:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _thread_lock(path)
    flags = os.O_RDWR | os.O_CREAT if create else os.O_RDWR
    with lock:
        try:
            fd = os.open(path, flags, 0o644)
        except FileNotFoundError:
            if create:
                raise
            return fn(-1)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fn(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _read_fd(fd: int) -> bytes:
    chunks = []
    while True:
        piece = os.read(fd, 65536)
        if not piece:
            break
        chunks.append(piece)
    return b"".join(chunks)


def _write_fd(fd: int, payload: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, payload)
    os.fsync(fd)


def _lease_from_dict(room_id: str, data: object) -> RoomLease:
    if not isinstance(data, dict):
        raise LifecycleError("lease must be an object")
    ttl = data.get("ttl_seconds", DEFAULT_TTL_SECONDS)
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0 or ttl > MAX_TTL_SECONDS:
        raise LifecycleError("lease ttl_seconds must be a positive int")
    kind = data.get("kind", ESCAPE_ROOM_KIND)
    guest = data.get("guest", ESCAPE_GUEST)
    if not isinstance(kind, str) or not kind:
        raise LifecycleError("lease kind required")
    if not isinstance(guest, str) or not guest:
        raise LifecycleError("lease guest required")
    planted = parse_iso8601(data.get("planted_at") or now_iso()).replace(microsecond=0).isoformat()
    heartbeat_raw = data.get("last_heartbeat_at") or planted
    last_hb = parse_iso8601(heartbeat_raw).replace(microsecond=0).isoformat()
    return RoomLease(
        room_id=require_safe_id(data.get("room_id", room_id), "room_id"),
        window_id=require_safe_id(data.get("window_id"), "window_id"),
        kind=kind,
        guest=guest,
        planted_at=planted,
        last_heartbeat_at=last_hb,
        ttl_seconds=ttl,
    )


def _load_rooms(fd: int) -> dict[str, RoomLease]:
    raw = _read_fd(fd)
    body = _parse_object(raw, label="leases")
    rooms_raw = body.get("rooms", body)
    if rooms_raw is None:
        return {}
    if not isinstance(rooms_raw, dict):
        raise LifecycleError("corrupt leases store; fail closed")
    rooms: dict[str, RoomLease] = {}
    for key, value in rooms_raw.items():
        rooms[str(key)] = _lease_from_dict(str(key), value)
    return rooms


def _dump_rooms(rooms: dict[str, RoomLease]) -> bytes:
    payload = {"rooms": {room_id: asdict(lease) for room_id, lease in rooms.items()}}
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_leases(path: Path | None = None) -> dict[str, RoomLease]:
    store = path or leases_path()
    if not store.is_file():
        return {}

    def _read(fd: int) -> dict[str, RoomLease]:
        if fd < 0:
            return {}
        return _load_rooms(fd)

    return _locked(store, _read, create=False)


def put_lease(lease: RoomLease, path: Path | None = None) -> RoomLease:
    require_safe_id(lease.room_id, "room_id")
    require_safe_id(lease.window_id, "window_id")
    store = path or leases_path()

    def _put(fd: int) -> RoomLease:
        rooms = _load_rooms(fd)
        rooms[lease.room_id] = lease
        _write_fd(fd, _dump_rooms(rooms))
        return lease

    return _locked(store, _put)


def drop_lease(room_id: str, path: Path | None = None) -> None:
    store = path or leases_path()
    if not store.is_file():
        return

    def _drop(fd: int) -> None:
        rooms = _load_rooms(fd)
        rooms.pop(room_id, None)
        _write_fd(fd, _dump_rooms(rooms))

    _locked(store, _drop)


def register_lease(
    *,
    room_id: str,
    window_id: str,
    planted_at: str | None = None,
    last_heartbeat_at: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    kind: str = ESCAPE_ROOM_KIND,
    guest: str = ESCAPE_GUEST,
    path: Path | None = None,
) -> RoomLease:
    if kind != ESCAPE_ROOM_KIND or guest != ESCAPE_GUEST:
        raise LifecycleError("lease registry is escape-sealed rooms only")
    planted = planted_at or now_iso()
    lease = RoomLease(
        room_id=require_safe_id(room_id, "room_id"),
        window_id=require_safe_id(window_id, "window_id"),
        kind=kind,
        guest=guest,
        planted_at=planted,
        last_heartbeat_at=last_heartbeat_at or planted,
        ttl_seconds=ttl_seconds,
    )
    if lease.ttl_seconds <= 0 or lease.ttl_seconds > MAX_TTL_SECONDS:
        raise LifecycleError("lease ttl_seconds must be a positive int")
    return put_lease(lease, path=path)


def heartbeat(
    room_id: str,
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> RoomLease:
    require_safe_id(room_id, "room_id")
    store = path or leases_path()
    moment = (now or now_utc()).replace(microsecond=0).isoformat()

    def _beat(fd: int) -> RoomLease:
        rooms = _load_rooms(fd)
        lease = rooms.get(room_id)
        if lease is None:
            raise LifecycleError(f"no lease for {room_id}; heartbeat fail closed")
        if not lease.is_escape_room():
            raise LifecycleError("heartbeat is for escape-sealed rooms only")
        lease.last_heartbeat_at = moment
        rooms[room_id] = lease
        _write_fd(fd, _dump_rooms(rooms))
        return lease

    return _locked(store, _beat)


def lease_expiry(lease: RoomLease) -> datetime:
    last = parse_iso8601(lease.last_heartbeat_at)
    planted = parse_iso8601(lease.planted_at)
    idle = last + timedelta(seconds=lease.ttl_seconds)
    hard = planted + timedelta(seconds=MAX_TTL_SECONDS)
    return idle if idle <= hard else hard


def is_expired(lease: RoomLease, now: datetime | None = None) -> bool:
    moment = now if now is not None else now_utc()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment > lease_expiry(lease)


def load_inflight(path: Path | None = None) -> list[str]:
    store = path or inflight_path()
    if not store.is_file():
        return []

    def _read(fd: int) -> list[str]:
        if fd < 0:
            return []
        body = _parse_object(_read_fd(fd), label="sweep-inflight")
        ids = body.get("room_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            raise LifecycleError("corrupt sweep-inflight store; fail closed")
        return list(ids)

    return _locked(store, _read, create=False)


def write_inflight(room_ids: list[str], path: Path | None = None) -> None:
    store = path or inflight_path()

    def _write(fd: int) -> None:
        payload = (json.dumps({"room_ids": list(room_ids)}, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        _write_fd(fd, payload)

    _locked(store, _write)


def mark_inflight(room_id: str, path: Path | None = None) -> list[str]:
    require_safe_id(room_id, "room_id")
    store = path or inflight_path()

    def _mark(fd: int) -> list[str]:
        body = _parse_object(_read_fd(fd), label="sweep-inflight")
        ids = body.get("room_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            raise LifecycleError("corrupt sweep-inflight store; fail closed")
        if room_id not in ids:
            ids.append(room_id)
        _write_fd(fd, (json.dumps({"room_ids": ids}, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return list(ids)

    return _locked(store, _mark)


def clear_inflight(room_id: str, path: Path | None = None) -> None:
    store = path or inflight_path()
    if not store.is_file():
        return

    def _clear(fd: int) -> None:
        body = _parse_object(_read_fd(fd), label="sweep-inflight")
        ids = body.get("room_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            raise LifecycleError("corrupt sweep-inflight store; fail closed")
        ids = [x for x in ids if x != room_id]
        _write_fd(fd, (json.dumps({"room_ids": ids}, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    _locked(store, _clear)
