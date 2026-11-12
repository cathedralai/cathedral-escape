from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(home: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ESCAPE_PRACTICE_HOME"] = str(home)
    # pytest-cov injects COV_* / COVERAGE_* so child CLIs write parallel
    # .coverage.* files without branch=true; combining those with the parent
    # data file fails CI. E2E proves the CLI, not subprocess coverage.
    for key in list(env):
        if key.startswith(("COV_", "COVERAGE_")):
            del env[key]
    return subprocess.run(
        [sys.executable, "-m", "escape_practice", *args],
        cwd=home,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def test_e2e_window_try_claim_verify_finish(practice_home: Path, tmp_path: Path) -> None:
    window = _run(practice_home, "window")
    assert window.returncode == 0
    assert "PRACTICE ONLY" in window.stdout

    miss = _run(practice_home, "try", "--", "cat", "/etc/hostname")
    assert miss.returncode == 0
    claim_path = tmp_path / "claim.json"
    no_proof = _run(practice_home, "claim", str(claim_path), check=False)
    assert no_proof.returncode == 1
    assert "host nonce" in no_proof.stderr

    hit = _run(practice_home, "try", "--", "cat", "/host-nonce")
    assert hit.returncode == 0
    assert json.loads(hit.stdout)["attested_room"].startswith("practice-room-")

    claimed = _run(practice_home, "claim", str(claim_path))
    assert claimed.returncode == 0
    doc = json.loads(claim_path.read_text(encoding="utf-8"))
    assert doc["target"] == "host"
    assert doc["schema"] == "escape_practice_claim_v0"

    verified = _run(practice_home, "verify", str(claim_path))
    assert verified.returncode == 0
    assert "not AMD" in verified.stdout

    replay = _run(practice_home, "verify", str(claim_path), check=False)
    assert replay.returncode == 1
    assert "replayed" in replay.stderr

    finished = _run(practice_home, "finish")
    assert finished.returncode == 0
    assert "delete-always" in finished.stdout

    gone = _run(practice_home, "status", check=False)
    assert gone.returncode == 1
    assert "no practice session" in gone.stdout


def test_e2e_abandon_and_retry_delete_always(practice_home: Path) -> None:
    _run(practice_home, "window")
    abandoned = _run(practice_home, "abandon")
    assert "delete-always" in abandoned.stdout
    _run(practice_home, "window")
    retried = _run(practice_home, "retry")
    assert retried.returncode == 0
    status = _run(practice_home, "status")
    assert status.returncode == 0
    body = json.loads(status.stdout)
    assert body["window_id"].startswith("practice-window-")


def test_e2e_empty_claim_fails_closed(practice_home: Path, tmp_path: Path) -> None:
    _run(practice_home, "window")
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    result = _run(practice_home, "verify", str(empty), check=False)
    assert result.returncode == 1
    assert "empty" in result.stderr


def test_e2e_try_requires_argv(practice_home: Path) -> None:
    _run(practice_home, "window")
    result = _run(practice_home, "try", check=False)
    assert result.returncode == 2


def test_e2e_forged_claim_rejected(practice_home: Path, tmp_path: Path) -> None:
    _run(practice_home, "window")
    _run(practice_home, "try", "--", "cat", "/host-nonce")
    claim_path = tmp_path / "claim.json"
    _run(practice_home, "claim", str(claim_path))
    doc = json.loads(claim_path.read_text(encoding="utf-8"))
    doc["commands"][0]["practice_sig"] = "00" * 32
    claim_path.write_text(json.dumps(doc), encoding="utf-8")
    result = _run(practice_home, "verify", str(claim_path), check=False)
    assert result.returncode == 1
    assert "practice_sig" in result.stderr
