from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from escape_practice.claim import build_claim, sign_command, sign_command_with_key
from escape_practice.signer import HOTEL_LOCAL_TEST_KEY
from escape_practice.sim import run_command
from escape_practice.verify_practice import PracticeVerifyError, verify_claim

from helpers import host_session, signed_host_claim


def test_missing_claim_object() -> None:
    session, _ = signed_host_claim()
    with pytest.raises(PracticeVerifyError, match="object"):
        verify_claim(None, session)


def test_empty_claim_dict() -> None:
    session, _ = signed_host_claim()
    with pytest.raises(PracticeVerifyError):
        verify_claim({}, session)


def test_unsigned_fails_closed() -> None:
    session, claim = signed_host_claim()
    del claim["commands"][0]["practice_sig"]
    with pytest.raises(PracticeVerifyError, match="practice_sig required"):
        verify_claim(claim, session)


def test_forged_hmac_fails_closed() -> None:
    session, claim = signed_host_claim()
    claim["commands"][0]["stdout"] = session.host_nonce + "-tampered"
    # keep old sig
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_hotel_local_key_is_forge() -> None:
    session = host_session()
    run_command(session, ["cat", "/host-nonce"])
    claim = build_claim(session)
    claim["commands"][0]["practice_sig"] = sign_command_with_key(
        claim["commands"][0], HOTEL_LOCAL_TEST_KEY
    )
    with pytest.raises(PracticeVerifyError, match="practice_sig"):
        verify_claim(claim, session)


def test_replayed_claim_fails_closed() -> None:
    session, claim = signed_host_claim()
    verify_claim(claim, session)
    with pytest.raises(PracticeVerifyError, match="replayed"):
        verify_claim(claim, session)


def test_stale_nonce_fails_closed() -> None:
    session, claim = signed_host_claim()
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    with pytest.raises(PracticeVerifyError, match="stale"):
        verify_claim(claim, session, now=later)


def test_wrong_room_attested_fails_closed() -> None:
    session, claim = signed_host_claim()
    claim["commands"][0]["attested_room"] = "room-b"
    claim["commands"][0]["practice_sig"] = sign_command(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="origin bind"):
        verify_claim(claim, session)


def test_wrong_planted_nonce_fails_closed() -> None:
    session, claim = signed_host_claim()
    session.host_nonce = "cafebabe"
    with pytest.raises(PracticeVerifyError, match="planted host nonce"):
        verify_claim(claim, session)


def test_deleted_session_cannot_verify() -> None:
    session, claim = signed_host_claim()
    session.deleted = True
    with pytest.raises(PracticeVerifyError, match="deleted"):
        verify_claim(claim, session)


def test_proof_without_matching_stdout_fails() -> None:
    session, claim = signed_host_claim()
    claim["commands"][0]["stdout"] = "not-the-nonce"
    claim["commands"][0]["practice_sig"] = sign_command(claim["commands"][0])
    with pytest.raises(PracticeVerifyError, match="proof nonce"):
        verify_claim(claim, session)
