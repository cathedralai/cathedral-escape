"""Nonce / window freshness. Stale planted nonces fail closed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import MAX_CLOCK_SKEW_SECONDS
from .errors import PracticeVerifyError

MAX_TTL_SECONDS = 24 * 3600


def parse_iso8601(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise PracticeVerifyError("planted_at required (ISO-8601)")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PracticeVerifyError("planted_at is not ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat()


def assert_fresh(*, planted_at: object, ttl_seconds: object, now: datetime | None = None) -> None:
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise PracticeVerifyError("ttl_seconds must be a positive int")
    if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        raise PracticeVerifyError("ttl_seconds out of range")
    planted = parse_iso8601(planted_at)
    moment = now if now is not None else now_utc()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # CVE-2016-7434: a nonsensical origin timestamp must not skip validation.
    if planted - moment > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise PracticeVerifyError("planted_at is in the future; clock skew fail closed")
    expiry = planted + timedelta(seconds=ttl_seconds)
    if moment > expiry:
        raise PracticeVerifyError("stale host nonce; window expired")
