"""Shared builders for practice unit tests."""

from __future__ import annotations

from escape_practice.claim import build_claim, sign_command
from escape_practice.sim import Session, run_command


def host_session(*, window_id: str = "w1", room_id: str = "a", nonce: str = "deadbeef") -> Session:
    return Session(window_id=window_id, room_id=room_id, host_nonce=nonce, commands=[])


def make_session(
    window_id: str = "w1",
    room_id: str = "a",
    host_nonce: str = "deadbeef",
) -> Session:
    return host_session(window_id=window_id, room_id=room_id, nonce=host_nonce)


def signed_host_claim(session: Session | None = None) -> tuple[Session, dict]:
    session = session or host_session()
    run_command(session, ["cat", "/host-nonce"])
    return session, build_claim(session)


def signed_breakout(
    session: Session | None = None,
    extra_argv: list[str] | None = None,
) -> tuple[Session, dict]:
    session = session or make_session()
    if extra_argv:
        run_command(session, extra_argv)
    run_command(session, ["cat", "/host-nonce"])
    return session, build_claim(session)


def resign(cmd: dict) -> None:
    cmd["practice_sig"] = sign_command(cmd)
