"""Shared error types. All fail closed: never used as a soft/best-effort signal."""

from __future__ import annotations


class EscapePracticeError(ValueError):
    """Base for practice-harness failures."""


class ClaimParseError(EscapePracticeError):
    """Claim JSON failed schema / type / bound checks."""


class PracticeVerifyError(EscapePracticeError):
    """Claim did not verify. Alias kept for the historic import path too."""


class LifecycleError(EscapePracticeError):
    """Delete-always / room lifecycle violation."""


class PlacementError(EscapePracticeError):
    """Isolation fence refused the placement."""


class SignerTopologyError(EscapePracticeError):
    """Contest signer is not outside the hotel (T2 / R9)."""


class RehearsalDraftError(EscapePracticeError):
    """Known-escape rehearsal guest draft failed its invariants."""


class OpenPolicyError(EscapePracticeError):
    """P0 Open is host-only; neighbour is P2."""


class OpenClosedError(OpenPolicyError):
    """Public Open is closed. Operator capped creates may still work."""


class StagingInjectorError(EscapePracticeError):
    """Staging nonce plant refused. This is not the live R6 host-plant path."""


class ReceiptKeyError(EscapePracticeError):
    """Stage C receipt key material is missing, malformed, or mismatched."""


class HostNonceError(EscapePracticeError):
    """Host nonce was missing, stale, replayed, or chosen inside a room."""


class ReceiptVerifyError(PracticeVerifyError):
    """Stage C contest receipt did not verify. Fail closed."""


class OfficialPathError(EscapePracticeError):
    """Official verify was asked to use a path other than named AMD SEV-SNP."""


class LiveCapacityBlocked(RuntimeError):
    """Live hotel / broker / AMD path. Practice and CI must not call it."""
