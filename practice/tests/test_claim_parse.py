from __future__ import annotations

import pytest

from escape_practice.claim import parse_claim, sign_command
from escape_practice.errors import ClaimParseError, OpenPolicyError
from escape_practice.open_policy import assert_open_target

from helpers import signed_host_claim


def test_parse_valid_claim() -> None:
    _, claim = signed_host_claim()
    parsed = parse_claim(claim)
    assert parsed["schema"] == "escape_practice_claim_v0"
    assert parsed["target"] == "host"


def test_parse_rejects_non_object() -> None:
    with pytest.raises(ClaimParseError, match="object"):
        parse_claim(["not", "an", "object"])


def test_parse_rejects_missing_schema() -> None:
    with pytest.raises(ClaimParseError, match="schema"):
        parse_claim({"target": "host"})


def test_parse_rejects_missing_commands() -> None:
    with pytest.raises(ClaimParseError, match="commands"):
        parse_claim(
            {
                "schema": "escape_practice_claim_v0",
                "target": "host",
                "window_id": "w1",
                "room_id": "a",
                "proof_token": {"kind": "host_nonce", "nonce": "x", "window_id": "w1"},
            }
        )


def test_parse_rejects_empty_commands() -> None:
    with pytest.raises(ClaimParseError, match="commands"):
        parse_claim(
            {
                "schema": "escape_practice_claim_v0",
                "target": "host",
                "window_id": "w1",
                "room_id": "a",
                "commands": [],
                "proof_token": {"kind": "host_nonce", "nonce": "x", "window_id": "w1"},
            }
        )


def test_parse_rejects_unsigned_command() -> None:
    _, claim = signed_host_claim()
    del claim["commands"][0]["practice_sig"]
    with pytest.raises(ClaimParseError, match="practice_sig required"):
        parse_claim(claim)


def test_parse_rejects_malformed_sig() -> None:
    _, claim = signed_host_claim()
    claim["commands"][0]["practice_sig"] = "not-hex"
    with pytest.raises(ClaimParseError, match="64 hex"):
        parse_claim(claim)


def test_parse_rejects_neighbour_target() -> None:
    _, claim = signed_host_claim()
    claim["target"] = "neighbour"
    with pytest.raises(OpenPolicyError):
        parse_claim(claim)


def test_parse_allows_extra_fields() -> None:
    _, claim = signed_host_claim()
    claim["hotel_root_key"] = "not-a-secret-just-extra"
    parsed = parse_claim(claim)
    assert parsed["hotel_root_key"] == "not-a-secret-just-extra"


def test_parse_rejects_proof_token_window_mismatch() -> None:
    _, claim = signed_host_claim()
    claim["proof_token"]["window_id"] = "other"
    with pytest.raises(ClaimParseError, match="window_id mismatch"):
        parse_claim(claim)


def test_parse_rejects_duplicate_seq() -> None:
    _, claim = signed_host_claim()
    extra = dict(claim["commands"][0])
    extra["seq"] = 1
    extra["practice_sig"] = sign_command(extra)
    claim["commands"].append(extra)
    with pytest.raises(ClaimParseError, match="unique"):
        parse_claim(claim)


def test_parse_rejects_non_string_argv() -> None:
    _, claim = signed_host_claim()
    claim["commands"][0]["argv"] = ["cat", 1]
    claim["commands"][0]["practice_sig"] = sign_command(claim["commands"][0])
    with pytest.raises(ClaimParseError, match="argv"):
        parse_claim(claim)


def test_open_policy_rejects_empty_and_unknown() -> None:
    with pytest.raises(OpenPolicyError):
        assert_open_target("")
    with pytest.raises(OpenPolicyError):
        assert_open_target("hypervisor")
    assert assert_open_target("host") == "host"
