"""Invented room + host-nonce fence. No broker, no real hotel."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import DEFAULT_TTL_SECONDS, HOST_NONCE_PATH, MAX_ARGV_LEN
from .errors import EscapePracticeError
from .freshness import MAX_TTL_SECONDS, now_iso, now_utc, parse_iso8601
from .host_nonce import assert_plant_origin, generate_host_nonce
from .ids import require_safe_id
from .leases import heartbeat, register_lease
from .store import atomic_write, state_dir, state_path

# Re-export so existing imports keep working.
__all__ = [
    "Session",
    "heartbeat_session",
    "load",
    "new_session",
    "run_command",
    "save",
    "state_dir",
    "state_path",
]


def _require_nonempty_str(value: object, name: str) -> str:
    return require_safe_id(value, name)


@dataclass
class Session:
    window_id: str
    room_id: str
    host_nonce: str
    commands: list[dict] = field(default_factory=list)
    planted_at: str = field(default_factory=now_iso)
    last_heartbeat_at: str = field(default_factory=now_iso)
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    deleted: bool = False
    delete_reason: str | None = None
    nonce_origin: str = "control_plane"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: object) -> Session:
        if not isinstance(data, dict):
            raise EscapePracticeError("session must be an object")
        ttl = data.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise EscapePracticeError("ttl_seconds must be a positive int")
        commands = data.get("commands") or []
        if not isinstance(commands, list):
            raise EscapePracticeError("commands must be a list")
        deleted = data.get("deleted", False)
        if not isinstance(deleted, bool):
            raise EscapePracticeError("deleted must be a bool")
        reason = data.get("delete_reason")
        if reason is not None and not isinstance(reason, str):
            raise EscapePracticeError("delete_reason must be a string")
        planted = (
            parse_iso8601(data["planted_at"]).replace(microsecond=0).isoformat()
            if data.get("planted_at")
            else now_iso()
        )
        heartbeat_raw = data.get("last_heartbeat_at") or planted
        last_heartbeat = parse_iso8601(heartbeat_raw).replace(microsecond=0).isoformat()
        origin = data.get("nonce_origin", "control_plane")
        return cls(
            window_id=_require_nonempty_str(data.get("window_id"), "window_id"),
            room_id=_require_nonempty_str(data.get("room_id"), "room_id"),
            host_nonce=_require_nonempty_str(data.get("host_nonce"), "host_nonce"),
            commands=list(commands),
            planted_at=planted,
            last_heartbeat_at=last_heartbeat,
            ttl_seconds=ttl,
            deleted=deleted,
            delete_reason=reason,
            nonce_origin=assert_plant_origin(origin),
        )


def new_session(*, ttl_seconds: int | None = None) -> Session:
    planted = now_iso()
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0 or ttl > MAX_TTL_SECONDS:
        raise EscapePracticeError("ttl_seconds must be a positive int")
    return Session(
        window_id=f"practice-window-{secrets.token_hex(8)}",
        room_id=f"practice-room-{secrets.token_hex(4)}",
        host_nonce=generate_host_nonce(),
        commands=[],
        planted_at=planted,
        last_heartbeat_at=planted,
        ttl_seconds=ttl,
        nonce_origin="control_plane",
    )


def save(session: Session, path: Path | None = None) -> Path:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, session.to_json())
    if not session.deleted:
        register_lease(
            room_id=session.room_id,
            window_id=session.window_id,
            planted_at=session.planted_at,
            last_heartbeat_at=session.last_heartbeat_at,
            ttl_seconds=session.ttl_seconds,
        )
    return path


def heartbeat_session(session: Session, *, now: datetime | None = None) -> Session:
    moment = now if now is not None else now_utc()
    session.last_heartbeat_at = moment.replace(microsecond=0).isoformat()
    heartbeat(session.room_id, now=moment)
    return session


def load(path: Path | None = None) -> Session:
    path = path or state_path()
    if not path.is_file():
        raise FileNotFoundError(f"no practice session at {path}; run: escape-practice window")
    session = Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if session.deleted:
        raise EscapePracticeError("session is deleted; delete-always forbids reuse")
    return session


def run_command(session: Session, argv: object) -> dict:
    """Simulate one command inside the room. Only /host-nonce is the break-out."""
    if session.deleted:
        raise EscapePracticeError("session is deleted; delete-always forbids reuse")
    if not isinstance(argv, list) or not argv:
        raise EscapePracticeError("argv must be a non-empty list")
    if len(argv) > MAX_ARGV_LEN:
        raise EscapePracticeError("argv too long")
    if any(not isinstance(part, str) or not part for part in argv):
        raise EscapePracticeError("argv entries must be non-empty strings")
    stdout = ""
    exit_code = 0
    if argv == ["cat", HOST_NONCE_PATH]:
        # Invented fence: reading this path means the contestant "reached host".
        stdout = session.host_nonce
    elif argv[0] == "cat" and len(argv) == 2:
        stdout = f"practice-file:{argv[1]}\n"
    elif argv == ["id"]:
        stdout = "uid=1000(practice) gid=1000(practice)\n"
    else:
        stdout = f"practice: ran {' '.join(argv)}\n"
    record = {
        "seq": len(session.commands) + 1,
        "argv": list(argv),
        "stdout": stdout,
        "exit_code": exit_code,
        "attested_room": session.room_id,
    }
    session.last_heartbeat_at = now_iso()
    session.commands.append(record)
    return record
