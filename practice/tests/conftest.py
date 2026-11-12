from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def practice_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "escape-practice-home"
    home.mkdir()
    monkeypatch.setenv("ESCAPE_PRACTICE_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return home
