"""Harness sim + CLI smoke. Kept next to the original practice tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from escape_practice import HOST_NONCE_PATH
from escape_practice.__main__ import main
from escape_practice.sim import load, new_session, run_command, save


def test_host_nonce_path_is_the_breakout() -> None:
    session = new_session()
    other = run_command(session, ["cat", "/etc/hostname"])
    assert other["stdout"] != session.host_nonce
    hit = run_command(session, ["cat", HOST_NONCE_PATH])
    assert hit["stdout"] == session.host_nonce
    assert hit["attested_room"] == session.room_id


def test_cli_window_try_claim_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESCAPE_PRACTICE_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert main(["window"]) == 0
    session = load()
    assert session.host_nonce
    assert main(["try", "--", "cat", "/host-nonce"]) == 0
    claim_path = tmp_path / "out.json"
    assert main(["claim", str(claim_path)]) == 0
    assert main(["verify", str(claim_path)]) == 0
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["schema"] == "escape_practice_claim_v0"
    assert claim["proof_token"]["nonce"] == session.host_nonce


def test_cli_verify_without_session_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESCAPE_PRACTICE_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    claim_path = tmp_path / "out.json"
    claim_path.write_text("{}", encoding="utf-8")
    assert main(["verify", str(claim_path)]) == 1


def test_session_roundtrip_disk(tmp_path: Path) -> None:
    session = new_session()
    path = save(session, tmp_path / "session.json")
    loaded = load(path)
    assert loaded.host_nonce == session.host_nonce
    assert loaded.window_id == session.window_id
    assert loaded.room_id == session.room_id
