"""Build, parse, and HMAC-sign a practice claim. Not a hotel receipt."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from . import (
    HOST_NONCE_PATH,
    MAX_ARGV_LEN,
    MAX_CLAIM_BYTES,
    MAX_COMMANDS,
    MAX_STDOUT_CHARS,
    PRACTICE_KEY,
    SCHEMA,
)
from .errors import ClaimParseError, EscapePracticeError
from .ids import require_safe_id
from .open_policy import assert_open_target
from .sim import Session

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _canonical(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign_command_with_key(cmd: dict, key: bytes) -> str:
    body = {k: v for k, v in cmd.items() if k != "practice_sig"}
    return hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()


def sign_command(cmd: dict) -> str:
    return sign_command_with_key(cmd, PRACTICE_KEY)


def authorizing_body(claim: dict[str, Any]) -> dict[str, Any]:
    """Fields that authorize a verify. Unsigned extras (including notice) do not."""
    commands = []
    for cmd in claim.get("commands") or []:
        if not isinstance(cmd, dict):
            continue
        row = {
            "seq": cmd.get("seq"),
            "argv": cmd.get("argv"),
            "stdout": cmd.get("stdout"),
            "attested_room": cmd.get("attested_room"),
            "practice_sig": cmd.get("practice_sig"),
        }
        if "exit_code" in cmd:
            row["exit_code"] = cmd.get("exit_code")
        commands.append(row)
    token = claim.get("proof_token") if isinstance(claim.get("proof_token"), dict) else {}
    return {
        "schema": claim.get("schema"),
        "target": claim.get("target"),
        "window_id": claim.get("window_id"),
        "room_id": claim.get("room_id"),
        "commands": commands,
        "proof_token": {
            "kind": token.get("kind"),
            "nonce": token.get("nonce"),
            "window_id": token.get("window_id"),
        },
    }


def claim_digest(claim: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(authorizing_body(claim))).hexdigest()


def nonce_use_digest(*, window_id: str, room_id: str, nonce: str) -> str:
    """One-use key for a planted nonce. Extra unsigned fields cannot mint a new use."""
    return hashlib.sha256(_canonical({"window_id": window_id, "room_id": room_id, "nonce": nonce})).hexdigest()


def loads_strict(text: str) -> object:
    """JSON load that rejects oversize payloads and duplicate keys fail-closed."""
    if not isinstance(text, str):
        raise ClaimParseError("claim must be text")
    if len(text.encode("utf-8")) > MAX_CLAIM_BYTES:
        raise ClaimParseError("claim too large")

    def _reject_dupes(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise ClaimParseError("duplicate JSON keys; fail closed")
            seen.add(key)
            out[key] = value
        return out

    try:
        return json.loads(text, object_pairs_hook=_reject_dupes)
    except ClaimParseError:
        raise
    except json.JSONDecodeError as exc:
        raise ClaimParseError("claim is not JSON") from exc


def _require_str(value: object, name: str) -> str:
    try:
        return require_safe_id(value, name)
    except EscapePracticeError as exc:
        raise ClaimParseError(str(exc)) from exc


def _parse_command(cmd: object, *, index: int) -> dict[str, Any]:
    if not isinstance(cmd, dict):
        raise ClaimParseError("command must be object")
    seq = cmd.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise ClaimParseError("command.seq must be an integer")
    if seq < 1:
        raise ClaimParseError("command.seq must be >= 1")
    argv = cmd.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part for part in argv):
        raise ClaimParseError("command.argv must be a non-empty list of strings")
    if len(argv) > MAX_ARGV_LEN:
        raise ClaimParseError("command.argv too long")
    stdout = cmd.get("stdout")
    if not isinstance(stdout, str):
        raise ClaimParseError("command.stdout must be a string")
    if len(stdout) > MAX_STDOUT_CHARS:
        raise ClaimParseError("command.stdout too large")
    attested = _require_str(cmd.get("attested_room"), "command.attested_room")
    sig = cmd.get("practice_sig")
    if not isinstance(sig, str) or not sig:
        raise ClaimParseError(f"practice_sig required at seq={seq}")
    if not _HEX64.fullmatch(sig):
        raise ClaimParseError(f"practice_sig must be 64 hex chars at seq={seq}")
    parsed = dict(cmd)
    parsed["seq"] = seq
    parsed["argv"] = list(argv)
    parsed["stdout"] = stdout
    parsed["attested_room"] = attested
    parsed["practice_sig"] = sig
    if "exit_code" in cmd:
        exit_code = cmd["exit_code"]
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise ClaimParseError("command.exit_code must be an int")
        parsed["exit_code"] = exit_code
    return parsed


def parse_claim(raw: object) -> dict[str, Any]:
    """Strict parse of required fields. Extra fields are allowed (CLAIM-FORMAT v0)."""
    if not isinstance(raw, dict):
        raise ClaimParseError("claim must be an object")
    if raw.get("schema") != SCHEMA:
        raise ClaimParseError("bad schema")
    target = assert_open_target(raw.get("target"))
    window_id = _require_str(raw.get("window_id"), "window_id")
    room_id = _require_str(raw.get("room_id"), "room_id")
    commands = raw.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ClaimParseError("commands required")
    if len(commands) > MAX_COMMANDS:
        raise ClaimParseError("too many commands")
    parsed_cmds = [_parse_command(cmd, index=i) for i, cmd in enumerate(commands)]
    seqs = [cmd["seq"] for cmd in parsed_cmds]
    if len(seqs) != len(set(seqs)):
        raise ClaimParseError("command seq values must be unique")
    token = raw.get("proof_token")
    if token is None:
        raise ClaimParseError("proof_token required")
    if not isinstance(token, dict):
        raise ClaimParseError("proof_token must be an object")
    if token.get("kind") != "host_nonce":
        raise ClaimParseError("proof_token.kind must be host_nonce")
    nonce = _require_str(token.get("nonce"), "proof_token.nonce")
    token_window = _require_str(token.get("window_id"), "proof_token.window_id")
    if token_window != window_id:
        raise ClaimParseError("proof_token.window_id mismatch")
    parsed = dict(raw)
    parsed.update(
        {
            "schema": SCHEMA,
            "target": target,
            "window_id": window_id,
            "room_id": room_id,
            "commands": parsed_cmds,
            "proof_token": {**token, "kind": "host_nonce", "nonce": nonce, "window_id": token_window},
        }
    )
    return parsed


def build_claim(session: Session, target: str = "host") -> dict[str, Any]:
    if session.deleted:
        raise ClaimParseError("session is deleted; delete-always forbids reuse")
    assert_open_target(target)
    signed_cmds = []
    proof_nonce = None
    for cmd in session.commands:
        row = dict(cmd)
        row["practice_sig"] = sign_command(row)
        signed_cmds.append(row)
        if cmd.get("stdout") == session.host_nonce:
            proof_nonce = session.host_nonce
    if proof_nonce is None:
        raise ClaimParseError("no command returned the host nonce; try: escape-practice try cat /host-nonce")
    return {
        "schema": SCHEMA,
        "target": "host",
        "window_id": session.window_id,
        "room_id": session.room_id,
        "commands": signed_cmds,
        "proof_token": {
            "kind": "host_nonce",
            "nonce": proof_nonce,
            "window_id": session.window_id,
        },
        "notice": "PRACTICE ONLY: not sealed, not AMD-verified, no capacity",
    }


def host_nonce_argv() -> list[str]:
    return ["cat", HOST_NONCE_PATH]
