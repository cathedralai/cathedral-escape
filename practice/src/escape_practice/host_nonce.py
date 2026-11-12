"""Per-window host nonce, planted outside every room (R6).

Generated and injected from outside the guest/room. Fresh per contest
window. Bound into the Stage C receipt. A room cannot choose or replay it.
"""

from __future__ import annotations

import secrets

from .errors import HostNonceError

ALLOWED_PLANT_ORIGINS = frozenset({"control_plane"})
FORBIDDEN_PLANT_ORIGINS = frozenset(
    {"room", "guest", "hotel", "ci_runner", "hotel_local", "separate_signer"}
)


def generate_host_nonce() -> str:
    """Fresh 32-hex nonce. Caller must be the control plane, not a room."""
    return secrets.token_hex(16)


def assert_plant_origin(origin: object) -> str:
    if origin in FORBIDDEN_PLANT_ORIGINS:
        raise HostNonceError(
            "host nonce must be generated and planted outside the room "
            "(control plane only; a room cannot choose it)"
        )
    if not isinstance(origin, str) or origin not in ALLOWED_PLANT_ORIGINS:
        raise HostNonceError(
            "host nonce must be generated and planted outside the room "
            "(control plane only; a room cannot choose it)"
        )
    return origin


def assert_nonce_matches_planted(*, planted: object, claimed: object) -> None:
    if not isinstance(planted, str) or not planted:
        raise HostNonceError("planted host nonce is missing")
    if not isinstance(claimed, str) or not claimed:
        raise HostNonceError("claimed host nonce is missing")
    if claimed != planted:
        raise HostNonceError(
            "nonce does not match planted host nonce "
            "(stale, replayed, or room-chosen)"
        )
