"""Used-claim store. Replayed claims fail closed.

Consume is serialized (thread lock + flock) so two concurrent verifies of the
same nonce cannot both succeed (CVE-2024-23651 / CVE-2023-27561 TOCTOU class).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
from pathlib import Path
from typing import Iterable

from .errors import PracticeVerifyError
from .store import state_dir

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


def replay_path() -> Path:
    return state_dir() / "used-claims.json"


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _parse_used(raw: bytes) -> list[str]:
    if not raw.strip():
        return []
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PracticeVerifyError("corrupt used-claims store; fail closed") from exc
    if not isinstance(loaded, list) or any(not isinstance(x, str) for x in loaded):
        raise PracticeVerifyError("corrupt used-claims store; fail closed")
    return loaded


def _load(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return _parse_used(path.read_bytes())


def consume(claim_digest: str, path: Path | None = None) -> None:
    if not isinstance(claim_digest, str) or not _HEX64.fullmatch(claim_digest):
        raise PracticeVerifyError("claim digest required")
    store = path or replay_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    lock = _thread_lock(store)
    with lock:
        fd = os.open(store, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            chunks = []
            while True:
                piece = os.read(fd, 65536)
                if not piece:
                    break
                chunks.append(piece)
            used = _parse_used(b"".join(chunks))
            if claim_digest in used:
                raise PracticeVerifyError("replayed claim")
            used.append(claim_digest)
            payload = (json.dumps(used, indent=2) + "\n").encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def seen(claim_digest: str, path: Path | None = None) -> bool:
    store = path or replay_path()
    lock = _thread_lock(store)
    with lock:
        return claim_digest in _load(store)


def reset(digests: Iterable[str] | None = None, path: Path | None = None) -> None:
    store = path or replay_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    lock = _thread_lock(store)
    with lock:
        fd = os.open(store, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            payload = (json.dumps(list(digests or []), indent=2) + "\n").encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
