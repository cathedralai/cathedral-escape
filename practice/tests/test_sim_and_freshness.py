from __future__ import annotations

from pathlib import Path

import pytest

from escape_practice.errors import EscapePracticeError, PlacementError, PracticeVerifyError
from escape_practice.freshness import assert_fresh, parse_iso8601
from escape_practice.placement import Hotel, Inventory
from escape_practice.replay import consume, reset, seen
from escape_practice.sim import Session, load, new_session, run_command, save


def test_run_command_validates_argv() -> None:
    session = Session(window_id="w1", room_id="a", host_nonce="x", commands=[])
    with pytest.raises(EscapePracticeError, match="argv"):
        run_command(session, [])
    with pytest.raises(EscapePracticeError, match="argv"):
        run_command(session, ["cat", ""])
    rec = run_command(session, ["id"])
    assert "uid=1000" in rec["stdout"]
    rec2 = run_command(session, ["echo", "hi"])
    assert rec2["stdout"].startswith("practice:")


def test_deleted_session_cannot_run() -> None:
    session = Session(window_id="w1", room_id="a", host_nonce="x", commands=[], deleted=True)
    with pytest.raises(EscapePracticeError, match="deleted"):
        run_command(session, ["id"])


def test_load_missing_session() -> None:
    with pytest.raises(FileNotFoundError):
        load()


def test_from_dict_fail_closed() -> None:
    with pytest.raises(EscapePracticeError, match="object"):
        Session.from_dict([])
    with pytest.raises(EscapePracticeError, match="window_id"):
        Session.from_dict({"room_id": "a", "host_nonce": "x"})
    with pytest.raises(EscapePracticeError, match="ttl"):
        Session.from_dict({"window_id": "w", "room_id": "a", "host_nonce": "x", "ttl_seconds": 0})


def test_save_load_roundtrip() -> None:
    session = new_session()
    run_command(session, ["cat", "/etc/hostname"])
    save(session)
    loaded = load()
    assert loaded.window_id == session.window_id
    assert loaded.host_nonce == session.host_nonce
    assert len(loaded.commands) == 1


def test_freshness_rejects_bad_planted_at() -> None:
    with pytest.raises(PracticeVerifyError, match="ISO-8601"):
        parse_iso8601("not-a-date")
    with pytest.raises(PracticeVerifyError, match="ttl"):
        assert_fresh(planted_at="2026-10-27T00:00:00+00:00", ttl_seconds=0)
    naive = parse_iso8601("2026-10-27T00:00:00")
    assert naive.tzinfo is not None


def test_replay_store_corrupt_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "used.json"
    store.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PracticeVerifyError, match="corrupt"):
        consume("a" * 64, path=store)


def test_replay_seen_and_reset(tmp_path: Path) -> None:
    store = tmp_path / "used.json"
    digest = "b" * 64
    consume(digest, path=store)
    assert seen(digest, path=store)
    reset(path=store)
    assert not seen(digest, path=store)


def test_inventory_unknown_hotel_fails_closed() -> None:
    inventory = Inventory(hotels=[Hotel(hotel_id="h1", pool_class="sealed")])
    with pytest.raises(PlacementError, match="unknown hotel"):
        inventory.get("missing")
