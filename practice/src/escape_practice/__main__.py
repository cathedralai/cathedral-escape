"""CLI: escape-practice window | try | claim | verify | finish | abandon | retry | heartbeat | sweep"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import PRACTICE_KEY
from .claim import build_claim, loads_strict
from .errors import EscapePracticeError
from .lifecycle import abandon as lifecycle_abandon
from .lifecycle import finish as lifecycle_finish
from .lifecycle import retry as lifecycle_retry
from .redact import redact_text
from .signer import HOTEL_LOCAL_TEST_KEY
from .sim import heartbeat_session, load, new_session, run_command, save
from .sweep import sweep_abandoned
from .verify_practice import PracticeVerifyError, verify_claim


def _error_line(exc: BaseException) -> str:
    secrets: list[object] = [PRACTICE_KEY, HOTEL_LOCAL_TEST_KEY]
    try:
        secrets.append(load().host_nonce)
    except (FileNotFoundError, EscapePracticeError, OSError, KeyError, TypeError, ValueError):
        pass
    return redact_text(f"error: {exc}", secrets)


def _print_session(prefix: str, path: Path) -> None:
    print(f"{prefix}: {path}")
    print("notice: PRACTICE ONLY: invented nonce, not a live hotel")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="escape-practice",
        description="Free Escape practice harness. No broker, no capacity, no payout.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("window", help="plant a new practice host nonce session")

    try_p = sub.add_parser("try", help="run one invented command inside the practice room")
    try_p.add_argument("argv", nargs=argparse.REMAINDER, help="command argv after --")

    claim_p = sub.add_parser("claim", help="write a practice claim JSON")
    claim_p.add_argument("out", type=Path)

    ver = sub.add_parser("verify", help="check a practice claim against the local session")
    ver.add_argument("claim", type=Path)

    sub.add_parser("finish", help="delete-always: finish the practice room")
    sub.add_parser("abandon", help="delete-always: abandon the practice room")
    sub.add_parser("retry", help="delete-always: delete current room and plant a new window")
    sub.add_parser("status", help="print whether a practice session exists")
    sub.add_parser("heartbeat", help="refresh the room lease so the sweeper will not reap it")
    sub.add_parser("sweep", help="reap abandoned rooms whose heartbeat TTL has expired")

    args = parser.parse_args(argv)
    command = args.command

    try:
        if command == "window":
            path = save(new_session())
            _print_session("practice session written", path)
            return 0

        if command == "try":
            argv = list(args.argv)
            if argv and argv[0] == "--":
                argv = argv[1:]
            if not argv:
                print("usage: escape-practice try -- cat /host-nonce", file=sys.stderr)
                return 2
            session = load()
            record = run_command(session, argv)
            save(session)
            print(json.dumps(record, indent=2, sort_keys=True))
            return 0

        if command == "claim":
            session = load()
            doc = build_claim(session)
            args.out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
            return 0

        if command == "verify":
            session = load()
            raw_text = args.claim.read_text(encoding="utf-8")
            if not raw_text.strip():
                raise PracticeVerifyError("claim file is empty; fail closed")
            raw = loads_strict(raw_text)
            verify_claim(raw, session)
            print("ok: practice claim verifies (still not AMD / not live)")
            return 0

        if command == "finish":
            lifecycle_finish()
            print("deleted (finish): delete-always")
            return 0

        if command == "abandon":
            lifecycle_abandon()
            print("deleted (abandon): delete-always")
            return 0

        if command == "retry":
            fresh = lifecycle_retry()
            path = save(fresh)
            _print_session("deleted previous room; new practice session", path)
            return 0

        if command == "status":
            try:
                session = load()
            except FileNotFoundError:
                print("no practice session")
                return 1
            print(
                json.dumps(
                    {
                        "window_id": session.window_id,
                        "room_id": session.room_id,
                        "commands": len(session.commands),
                        "deleted": session.deleted,
                        "last_heartbeat_at": session.last_heartbeat_at,
                        "ttl_seconds": session.ttl_seconds,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if command == "heartbeat":
            session = load()
            heartbeat_session(session)
            save(session)
            print(
                json.dumps(
                    {
                        "room_id": session.room_id,
                        "last_heartbeat_at": session.last_heartbeat_at,
                        "ttl_seconds": session.ttl_seconds,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if command == "sweep":
            report = sweep_abandoned()
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0

        raise AssertionError(f"unhandled command {command!r}")
    except FileNotFoundError as e:
        print(_error_line(e), file=sys.stderr)
        return 1
    except (
        EscapePracticeError,
        PracticeVerifyError,
        ValueError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        OSError,
    ) as e:
        print(_error_line(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
