"""Practice verifier: happy path, bindings, tamper, replay, sessionless."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from escape_practice.claim import build_claim
from escape_practice.sim import run_command
from escape_practice.verify_practice import PracticeVerifyError, verify_claim

from helpers import make_session, resign, signed_breakout


def test_happy_path_claim_verifies(tmp_path: Path) -> None:
    session, claim = signed_breakout(extra_argv=["id"])
    out = tmp_path / "claim.json"
    out.write_text(json.dumps(claim), encoding="utf-8")
    verify_claim(json.loads(out.read_text(encoding="utf-8")), session)


def test_wrong_nonce_rejected() -> None:
    """Fails on planted-nonce binding even when stdout and sig match the fake nonce."""
    session, claim = signed_breakout()
    claim["proof_token"]["nonce"] = "cafebabe"
    claim["commands"][0]["stdout"] = "cafebabe"
    resign(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="planted host nonce"):
        verify_claim(claim, session)


def test_wrong_room_rejected_room_binding_only() -> None:
    """Re-sign a valid claim for the wrong room so only attested_room can fail."""
    session, claim = signed_breakout()
    claim["commands"][0]["attested_room"] = "other-room"
    resign(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="attested_room"):
        verify_claim(claim, session)


def test_tampered_stdout_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["stdout"] = "tampered"
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_tampered_argv_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["argv"] = ["cat", "/etc/shadow"]
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_tampered_seq_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["seq"] = 99
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_bad_signature_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["practice_sig"] = "00" * 32
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_missing_signature_rejected() -> None:
    session, claim = signed_breakout()
    del claim["commands"][0]["practice_sig"]
    with pytest.raises(PracticeVerifyError, match="practice_sig required"):
        verify_claim(claim, session)


def test_malformed_signature_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["practice_sig"] = "not-hex"
    with pytest.raises(PracticeVerifyError, match="64 hex"):
        verify_claim(claim, session)


def test_replayed_claim_from_another_session_rejected() -> None:
    session_a, claim_a = signed_breakout(make_session(host_nonce="aaa111"))
    session_b = make_session(host_nonce="bbb222")
    run_command(session_b, ["cat", "/host-nonce"])
    with pytest.raises(PracticeVerifyError, match="planted host nonce"):
        verify_claim(claim_a, session_b)


def test_sessionless_verify_fail_closed() -> None:
    _session, claim = signed_breakout()
    with pytest.raises(PracticeVerifyError, match="session required"):
        verify_claim(claim, None)
    with pytest.raises(PracticeVerifyError, match="session required"):
        verify_claim(claim)


def test_out_of_window_rejected() -> None:
    """v0 has no clock; out-of-window is a window_id that is not this session."""
    session, claim = signed_breakout()
    claim["window_id"] = "practice-window-other"
    claim["proof_token"]["window_id"] = "practice-window-other"
    with pytest.raises(PracticeVerifyError, match="out of window"):
        verify_claim(claim, session)


def test_neighbour_target_rejected_on_verify() -> None:
    session, claim = signed_breakout()
    claim["target"] = "neighbour"
    with pytest.raises(PracticeVerifyError, match="non-host"):
        verify_claim(claim, session)


def test_build_claim_rejects_neighbour_target() -> None:
    session = make_session()
    run_command(session, ["cat", "/host-nonce"])
    with pytest.raises(ValueError, match="neighbour is P2"):
        build_claim(session, target="neighbour")


def test_without_nonce_cannot_claim() -> None:
    session = make_session()
    run_command(session, ["cat", "/etc/hostname"])
    with pytest.raises(ValueError, match="host nonce"):
        build_claim(session)


def test_no_command_returns_nonce_rejected() -> None:
    session, claim = signed_breakout()
    claim["commands"][0]["stdout"] = "not-the-nonce"
    resign(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="proof nonce"):
        verify_claim(claim, session)


def test_proof_token_window_mismatch_rejected() -> None:
    session, claim = signed_breakout()
    claim["proof_token"]["window_id"] = "other-window"
    with pytest.raises(PracticeVerifyError, match="proof_token.window_id"):
        verify_claim(claim, session)


def test_claim_room_mismatch_vs_session_rejected() -> None:
    session, claim = signed_breakout()
    claim["room_id"] = "other-room"
    claim["commands"][0]["attested_room"] = "other-room"
    resign(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="room_id does not match session"):
        verify_claim(claim, session)
