"""Fail-closed identifier rules shared by claim, session, and placement."""

from __future__ import annotations

import re

from . import MAX_ID_LEN
from .errors import EscapePracticeError

SAFE_ID_RE = re.compile(rf"^[A-Za-z0-9._:-]{{1,{MAX_ID_LEN}}}$")


def require_safe_id(value: object, name: str) -> str:
    """Reject empty, whitespace-padded, control, or overlong identifiers.

    Confused-deputy / path-swap classes (CVE-2021-30465, CVE-2019-19921) start
    with crafted names. Practice IDs stay in a tight charset.
    """
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise EscapePracticeError(
            f"{name} must be a 1-{MAX_ID_LEN} char identifier [A-Za-z0-9._:-]"
        )
    return value
