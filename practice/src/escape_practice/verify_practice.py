"""Practice claim checks. Explicitly not isolation.attestation_of_host / verify_receipts.py.

Fail closed on missing, forged, replayed, stale, wrong-room, or unsigned claims.
Session is required. The practice HMAC key is public in this repo, so a
sessionless check (schema + "some stdout equals the claimed nonce") proves
nothing and is rejected fail-closed.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from pathlib import Path
from typing import Any

from .claim import nonce_use_digest, parse_claim, sign_command
from .errors import ClaimParseError, OpenPolicyError, PracticeVerifyError
from .freshness import assert_fresh
from .replay import consume as consume_replay
from .sim import Session

# Re-export so existing imports keep working.
__all__ = ["PracticeVerifyError", "verify_claim"]


def verify_claim(
    claim: object,
    session: Session | None = None,
    *,
    now: datetime | None = None,
    replay: bool = True,
    replay_path: Path | None = None,
) -> dict[str, Any]:
    if session is None:
        raise PracticeVerifyError(
            "session required: sessionless verify is fail-closed "
            "(practice HMAC key is public; a claimed nonce without a planted "
            "session proves nothing)"
        )
    if session.deleted:
        raise PracticeVerifyError("session is deleted; delete-always forbids reuse")
    try:
        parsed = parse_claim(claim)
    except ClaimParseError as exc:
        raise PracticeVerifyError(str(exc)) from exc
    except OpenPolicyError as exc:
        raise PracticeVerifyError("P0 practice rejects non-host target (neighbour is P2)") from exc

    room_id = parsed["room_id"]
    window_id = parsed["window_id"]
    nonce = parsed["proof_token"]["nonce"]

    if session.window_id != window_id:
        raise PracticeVerifyError("claim window_id does not match session (out of window)")
    if session.room_id != room_id:
        raise PracticeVerifyError("claim room_id does not match session")
    if session.host_nonce != nonce:
        raise PracticeVerifyError(
            "nonce does not match planted host nonce (replay or wrong window)"
        )
    assert_fresh(planted_at=session.planted_at, ttl_seconds=session.ttl_seconds, now=now)

    found = False
    for cmd in parsed["commands"]:
        if cmd["attested_room"] != room_id:
            raise PracticeVerifyError("attested_room must equal room_id (origin bind)")
        expected = sign_command(cmd)
        if not hmac.compare_digest(cmd["practice_sig"], expected):
            raise PracticeVerifyError(f"bad practice_sig at seq={cmd['seq']}")
        if cmd["stdout"] == nonce:
            found = True
    if not found:
        raise PracticeVerifyError("no attested command returned the proof nonce")

    if replay:
        consume_replay(
            nonce_use_digest(window_id=window_id, room_id=room_id, nonce=nonce),
            path=replay_path,
        )
    if session.deleted:
        raise PracticeVerifyError("session is deleted; delete-always forbids reuse")
    return parsed
