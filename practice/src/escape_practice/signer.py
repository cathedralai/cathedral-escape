"""Contest receipt signer lives on the production API only (T2 / R9 / C v1).

The signing key lives only in the production API (the control plane). Never on any hotel. No separate
signer box for v1. No CI-runner signer. Hotel-local signing is always a fail.

Practice HMAC is a public test vector for the control-plane practice claim
path. It is not a hotel key and not a secret. A hotel-local key must never
verify. Stage C receipts use throwaway keys generated at test time, not
this public vector.
"""

from __future__ import annotations

from . import PRACTICE_KEY
from .errors import SignerTopologyError

# Public test vector only: models a key that would exist *on the hotel* after a
# host break-out (CVE-2019-5736 class). Verifier must reject it.
HOTEL_LOCAL_TEST_KEY = b"hotel-local-v0-not-accepted-by-verifier"

# C v1 lock: control plane (production API) only.
ALLOWED_SIGNER_LOCATIONS = frozenset({"control_plane"})
FORBIDDEN_SIGNER_LOCATIONS = frozenset(
    {"separate_signer", "hotel", "hotel_local", "ci_runner", "room", "guest"}
)
PRACTICE_SIGNER_LOCATION = "control_plane"


def assert_signer_location(location: object) -> str:
    if isinstance(location, str) and location in FORBIDDEN_SIGNER_LOCATIONS:
        raise SignerTopologyError(
            "C v1 contest signer must be the production API control plane "
            "(the contest signing key is held by the API only); "
            "no separate signer box, no CI-runner signer, "
            "hotel-local is a fail (T2 / R9)"
        )
    if not isinstance(location, str) or location not in ALLOWED_SIGNER_LOCATIONS:
        raise SignerTopologyError(
            "C v1 contest signer must be the production API control plane "
            "(the contest signing key is held by the API only); "
            "no separate signer box, no CI-runner signer, "
            "hotel-local is a fail (T2 / R9)"
        )
    return location


def accepted_hmac_key() -> bytes:
    """Key the practice verifier will accept. Control-plane test vector only."""
    return PRACTICE_KEY


def is_hotel_local_key(key: bytes) -> bool:
    return key == HOTEL_LOCAL_TEST_KEY
