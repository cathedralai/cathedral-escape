"""Atomic file replace and practice-home paths. Partial writes must not become the live store."""

from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("ESCAPE_PRACTICE_HOME")
    if override:
        return Path(override)
    # CWD-local so practice never writes outside the worktree / CI sandbox.
    return Path.cwd() / ".escape-practice"


def state_path() -> Path:
    return state_dir() / "session.json"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
