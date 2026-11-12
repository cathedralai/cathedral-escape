from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from escape_practice.claim import build_claim, host_nonce_argv, loads_strict, parse_claim
from escape_practice.redact import redact_text
from escape_practice.errors import ClaimParseError, EscapePracticeError, LifecycleError, PlacementError
from escape_practice.freshness import assert_fresh, parse_iso8601
from escape_practice.lifecycle import delete_session, retry
from escape_practice.placement import Hotel, Inventory, place_customer_room, place_escape_room
from escape_practice.replay import consume
from escape_practice import MAX_ARGV_LEN
from escape_practice.sim import Session, load, run_command, save, state_dir
from escape_practice.verify_practice import verify_claim

from helpers import host_session, signed_host_claim


def test_parse_command_boundary_rejects() -> None:
    _, claim = signed_host_claim()
    claim["commands"] = ["nope"]
    with pytest.raises(ClaimParseError, match="object"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["seq"] = 0
    with pytest.raises(ClaimParseError, match="command.seq"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["argv"] = []
    with pytest.raises(ClaimParseError, match="command.argv"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["argv"] = ["x"] * 40
    with pytest.raises(ClaimParseError, match="too long"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["stdout"] = 1
    with pytest.raises(ClaimParseError, match="command.stdout"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["stdout"] = "z" * 64_001
    with pytest.raises(ClaimParseError, match="too large"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["exit_code"] = True
    with pytest.raises(ClaimParseError, match="exit_code"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"] = [dict(claim["commands"][0], seq=i) for i in range(1, 301)]
    with pytest.raises(ClaimParseError, match="too many"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["proof_token"] = []
    with pytest.raises(ClaimParseError, match="proof_token"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["proof_token"]["kind"] = "neighbour_nonce"
    with pytest.raises(ClaimParseError, match="host_nonce"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["commands"][0]["attested_room"] = ""
    with pytest.raises(ClaimParseError, match="attested_room"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    parsed = parse_claim(claim)
    assert parsed["commands"][0]["exit_code"] == 0


def test_build_claim_deleted_and_host_argv() -> None:
    session = host_session()
    session.deleted = True
    with pytest.raises(ClaimParseError, match="deleted"):
        build_claim(session)
    assert host_nonce_argv() == ["cat", "/host-nonce"]


def test_parse_rejects_whitespace_and_unsafe_ids() -> None:
    _, claim = signed_host_claim()
    claim["room_id"] = "  a  "
    with pytest.raises(ClaimParseError, match="room_id"):
        parse_claim(claim)
    _, claim = signed_host_claim()
    claim["window_id"] = "w1/../etc"
    claim["proof_token"]["window_id"] = "w1/../etc"
    with pytest.raises(ClaimParseError, match="window_id"):
        parse_claim(claim)


def test_freshness_more_edges() -> None:
    with pytest.raises(Exception):
        parse_iso8601("")
    with pytest.raises(Exception):
        assert_fresh(planted_at="2026-10-27T00:00:00+00:00", ttl_seconds="1")
    with pytest.raises(Exception):
        assert_fresh(planted_at="2026-10-27T00:00:00+00:00", ttl_seconds=99_999)
    planted = "2026-10-27T00:00:00+00:00"
    assert_fresh(planted_at=planted, ttl_seconds=3600, now=datetime(2026, 10, 27, 0, 10))
    # within the published NTP-style skew window, a slightly-future plant is ok
    assert_fresh(
        planted_at="2026-10-27T00:02:00+00:00",
        ttl_seconds=3600,
        now=datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc),
    )


def test_lifecycle_unknown_reason_and_load_from_disk() -> None:
    session = host_session()
    save(session)
    with pytest.raises(LifecycleError, match="unknown delete"):
        delete_session(session, reason="maybe")  # type: ignore[arg-type]
    fresh = retry(None)
    assert fresh.window_id
    session2 = host_session(window_id="gone")
    session2.deleted = True
    save(session2)
    with pytest.raises(EscapePracticeError, match="deleted"):
        load()


def test_placement_label_and_class_edges() -> None:
    labeled = Hotel(
        hotel_id="h",
        pool_class="sealed",
        labels={"reserved_for": "escape"},
    )
    inventory = Inventory(hotels=[labeled])
    assert inventory.get("h") is labeled
    assert place_escape_room("escape-sealed", labeled, inventory) is labeled
    weird = Hotel(hotel_id="w", pool_class="other", labels={"escape": "true"})
    with pytest.raises(PlacementError, match="sealed hotel"):
        place_escape_room("escape-sealed", weird, Inventory(hotels=[weird]))
    cust = Hotel(hotel_id="c", pool_class="sealed", labels={})
    with pytest.raises(PlacementError, match="customer guest"):
        place_customer_room("", cust)
    with pytest.raises(PlacementError, match="customer guest"):
        place_customer_room("escape-sealed", cust)


def test_sim_from_dict_and_argv_limit() -> None:
    with pytest.raises(EscapePracticeError, match="commands"):
        Session.from_dict({"window_id": "w", "room_id": "a", "host_nonce": "x", "commands": {"nope": 1}})
    with pytest.raises(EscapePracticeError, match="deleted must be a bool"):
        Session.from_dict({"window_id": "w", "room_id": "a", "host_nonce": "x", "deleted": "yes"})
    with pytest.raises(EscapePracticeError, match="delete_reason"):
        Session.from_dict({"window_id": "w", "room_id": "a", "host_nonce": "x", "delete_reason": 1})
    session = host_session()
    with pytest.raises(EscapePracticeError, match="too long"):
        run_command(session, ["x"] * (MAX_ARGV_LEN + 1))


def test_state_dir_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ESCAPE_PRACTICE_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert state_dir() == tmp_path / ".escape-practice"


def test_loads_strict_and_redact() -> None:
    with pytest.raises(ClaimParseError, match="not JSON"):
        loads_strict("{")
    assert "<redacted>" in redact_text(
        "prefix escape-practice-v0-not-a-hotel-key suffix",
        [b"escape-practice-v0-not-a-hotel-key"],
    )
    assert redact_text("xy", ["xy"]) == "xy"


def test_replay_bad_digest() -> None:
    with pytest.raises(Exception, match="digest"):
        consume("short")


def test_verify_without_replay_consume() -> None:
    session, claim = signed_host_claim()
    verify_claim(claim, session, replay=False)
    verify_claim(claim, session, replay=False)
