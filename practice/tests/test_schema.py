"""Malformed claims / CLAIM-FORMAT.md schema violations."""

from __future__ import annotations

import pytest

from escape_practice.verify_practice import PracticeVerifyError, verify_claim

from helpers import signed_breakout


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda c: c.update(schema="escape_official_claim_v0"), "bad schema"),
        (lambda c: c.pop("schema"), "bad schema"),
        (lambda c: c.pop("window_id"), "window_id"),
        (lambda c: c.update(window_id=""), "window_id"),
        (lambda c: c.update(window_id=1), "window_id"),
        (lambda c: c.pop("room_id"), "room_id"),
        (lambda c: c.update(room_id=""), "room_id"),
        (lambda c: c.pop("commands"), "commands required"),
        (lambda c: c.update(commands=[]), "commands required"),
        (lambda c: c.update(commands="not-a-list"), "commands required"),
        (lambda c: c.update(commands=["not-an-object"]), "command must be object"),
        (lambda c: c.pop("proof_token"), "proof_token required"),
        (lambda c: c.update(proof_token="nonce"), "proof_token must be an object"),
        (lambda c: c["proof_token"].update(kind="neighbour_nonce"), "host_nonce"),
        (lambda c: c["proof_token"].update(nonce=""), "proof_token.nonce"),
        (lambda c: c["proof_token"].pop("nonce"), "proof_token.nonce"),
        (lambda c: c.update(target=""), "non-host"),
        (lambda c: c.pop("target"), "non-host"),
    ],
)
def test_malformed_claim_rejected(mutate, match: str) -> None:
    session, claim = signed_breakout()
    mutate(claim)
    with pytest.raises(PracticeVerifyError, match=match):
        verify_claim(claim, session)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("seq", "1", "command.seq"),
        ("seq", True, "command.seq"),
        ("seq", 0, "command.seq must be >= 1"),
        ("argv", [], "command.argv"),
        ("argv", "cat /host-nonce", "command.argv"),
        ("argv", [1], "command.argv"),
        ("stdout", None, "command.stdout"),
        ("stdout", 12, "command.stdout"),
        ("attested_room", "", "command.attested_room"),
        ("attested_room", None, "command.attested_room"),
    ],
)
def test_malformed_command_fields_rejected(field: str, value: object, match: str) -> None:
    session, claim = signed_breakout()
    claim["commands"][0][field] = value
    with pytest.raises(PracticeVerifyError, match=match):
        verify_claim(claim, session)


@pytest.mark.parametrize("field", ["seq", "argv", "stdout", "attested_room"])
def test_missing_required_command_field_rejected(field: str) -> None:
    session, claim = signed_breakout()
    del claim["commands"][0][field]
    with pytest.raises(PracticeVerifyError, match=field):
        verify_claim(claim, session)


def test_claim_must_be_object() -> None:
    session, _claim = signed_breakout()
    with pytest.raises(PracticeVerifyError, match="claim must be an object"):
        verify_claim(["not", "a", "claim"], session)  # type: ignore[arg-type]


def test_v0_has_no_time_fields_and_does_not_require_expiry() -> None:
    """CLAIM-FORMAT.md v0 has no issued_at/expires_at; a claim without them verifies."""
    session, claim = signed_breakout()
    assert "issued_at" not in claim
    assert "expires_at" not in claim
    assert "exp" not in claim
    verify_claim(claim, session)


def test_extra_fields_allowed() -> None:
    session, claim = signed_breakout()
    assert "notice" in claim
    assert "exit_code" in claim["commands"][0]
    verify_claim(claim, session)
