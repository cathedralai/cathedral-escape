from __future__ import annotations

import json
from pathlib import Path

from escape_practice.__main__ import main
from escape_practice.claim import build_claim
from escape_practice.sim import load, new_session, run_command, save


def test_cli_full_flow(tmp_path: Path, capsys) -> None:
    assert main(["window"]) == 0
    assert "PRACTICE ONLY" in capsys.readouterr().out
    assert main(["try", "--", "id"]) == 0
    assert main(["try", "--", "cat", "/host-nonce"]) == 0
    claim = tmp_path / "c.json"
    assert main(["claim", str(claim)]) == 0
    assert main(["verify", str(claim)]) == 0
    assert main(["status"]) == 0
    assert main(["heartbeat"]) == 0
    assert main(["sweep"]) == 0
    assert main(["finish"]) == 0
    assert main(["status"]) == 1
    assert main(["sweep"]) == 0


def test_cli_abandon_retry_and_errors(tmp_path: Path, capsys) -> None:
    assert main(["window"]) == 0
    assert main(["abandon"]) == 0
    assert main(["window"]) == 0
    assert main(["retry"]) == 0
    assert main(["try"]) == 2
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert main(["verify", str(empty)]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert main(["verify", str(bad)]) == 1
    assert main(["claim", str(tmp_path / "nope.json")]) == 1
    capsys.readouterr()


def test_cli_forged_and_replay(tmp_path: Path) -> None:
    session = new_session()
    run_command(session, ["cat", "/host-nonce"])
    save(session)
    claim_path = tmp_path / "c.json"
    claim_path.write_text(json.dumps(build_claim(session)), encoding="utf-8")
    assert main(["verify", str(claim_path)]) == 0
    assert main(["verify", str(claim_path)]) == 1
    forged = json.loads(claim_path.read_text(encoding="utf-8"))
    forged["commands"][0]["practice_sig"] = "00" * 32
    claim_path.write_text(json.dumps(forged), encoding="utf-8")
    # session still exists; replay store already has the good digest, this is a new digest
    session2 = load()
    run_command(session2, ["id"])  # keep session alive
    save(session2)
    assert main(["verify", str(claim_path)]) == 1
