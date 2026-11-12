"""P0 / Open is host-only (T3). Neighbour stays P2.

Public Open on/off is a separate switch from the claim target. This module
enforces both: target=host, and the labeled staging double of the go-live
gate (`ESCAPE_OPEN`). That env name is the staging/practice double only. It
is not a claim that the live API or site uses the same name.
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from .errors import OpenClosedError, OpenPolicyError
from .placement import ESCAPE_GUEST

REHEARSAL_GUEST = "escape-rehearsal"

P0_OPEN_TARGET = "host"
P2_NEIGHBOUR_TARGET = "neighbour"
OPEN_SWITCH_ENV = "ESCAPE_OPEN"
OpenSeason = Literal["teaser", "open"]

# Staging/practice double. These strings are not secrets.
HOST_ONLY_PHRASE = "this season is host only"
NEIGHBOUR_LATER_PHRASE = "neighbour-room targets come in a later season"
OPEN_CTA_PHRASE = "start a room"
TEASER_KICKER = "opens soon"
OPEN_COPY = (
    "Open season target: reach the hotel host from inside the contest room. "
    "Neighbour-room targets come in a later season."
)
TEASER_COPY = (
    "Open season target: reach the hotel host from inside the contest room. "
    "Neighbour-room targets come in a later season."
)

_TRUTHY = frozenset({"1", "true", "on", "yes"})
_FALSY = frozenset({"0", "false", "off", "no", ""})
_NEIGHBOUR_CTA = (
    re.compile(r"or a neighbou?ring", re.IGNORECASE),
    re.compile(r"host or a neighbou?r", re.IGNORECASE),
    re.compile(r"the host, and a neighbou?r", re.IGNORECASE),
    re.compile(r"start a neighbou?r", re.IGNORECASE),
    re.compile(r"reach the host or a neighbou?r", re.IGNORECASE),
)
_HOST_ONLY = re.compile(r"host only", re.IGNORECASE)
_OPENS_SOON = re.compile(r"\bopens soon\b", re.IGNORECASE)
# Stage F is bounty. Until then the public page must not promise money.
# Word boundaries keep "window" and "winding" from matching "win".
_BOUNTY_COPY = re.compile(
    r"\b(bount(?:y|ies)|prizes?|payouts?|win|wins|winning)\b",
    re.IGNORECASE,
)
# A sentence that denies a bounty ("No bounty is offered yet", "Is there a
# bounty?") is the copy we want, so only sentences that claim one fail.
_BOUNTY_DENIAL = re.compile(r"\b(no|not|never|without)\b|n't\b|\?$", re.IGNORECASE)
_HIDDEN_MARKUP = re.compile(
    r"<!--.*?-->|<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def _bounty_claim(text: str) -> re.Match[str] | None:
    visible = re.sub(r"<[^>]+>", " ", _HIDDEN_MARKUP.sub(" ", text))
    for sentence in _SENTENCE_END.split(visible):
        sentence = sentence.strip()
        found = _BOUNTY_COPY.search(sentence)
        if found and not _BOUNTY_DENIAL.search(sentence):
            return found
    return None


_NEIGHBOUR_DEMOTED = re.compile(
    r"not in this season|later season|neighbour-room targets come in a later",
    re.IGNORECASE,
)


def assert_open_target(target: object) -> str:
    if not isinstance(target, str) or not target:
        raise OpenPolicyError("P0 practice rejects non-host target (neighbour is P2)")
    if target == P2_NEIGHBOUR_TARGET:
        raise OpenPolicyError("P0 practice rejects non-host target (neighbour is P2)")
    if target != P0_OPEN_TARGET:
        raise OpenPolicyError(f"P0 practice rejects non-host target {target!r} (neighbour is P2)")
    return target


def parse_open_switch(raw: object | None = None) -> bool:
    """Labeled staging/practice double. Unset or empty is closed (fail closed)."""
    if raw is None:
        raw = os.environ.get(OPEN_SWITCH_ENV, "")
    if not isinstance(raw, str):
        raise OpenPolicyError("ESCAPE_OPEN must be a string")
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise OpenPolicyError(f"ESCAPE_OPEN value {raw!r} is not a known switch")


def open_season(raw: object | None = None) -> OpenSeason:
    if parse_open_switch(raw):
        return "open"
    return "teaser"


def assert_public_open(raw: object | None = None) -> None:
    if not parse_open_switch(raw):
        raise OpenClosedError("public Open is closed")


def assert_public_open_guest(guest: object) -> str:
    """Public Open may only create on escape-sealed. The known-escape rehearsal guest is a separate pin."""
    if guest == REHEARSAL_GUEST:
        raise OpenPolicyError("known-escape rehearsal guest is not public Open")
    if guest != ESCAPE_GUEST:
        raise OpenPolicyError("only official entry guest is escape-sealed (Option B / T1)")
    return ESCAPE_GUEST


def neighbour_cta_present(text: object) -> bool:
    if not isinstance(text, str) or not text:
        return False
    return any(pattern.search(text) for pattern in _NEIGHBOUR_CTA)


def check_public_page_text(text: object, *, require_open: bool) -> dict[str, Any]:
    """Read-only checks on public copy. Used by the Stage E smoke."""
    if not isinstance(text, str) or not text.strip():
        raise OpenPolicyError("public page body is empty")
    if neighbour_cta_present(text):
        raise OpenPolicyError("public page still has a neighbour CTA")
    bounty = _bounty_claim(text)
    if bounty:
        raise OpenPolicyError(
            f"public page has bounty copy {bounty.group(0)!r}; Stage F is not on"
        )
    if not _HOST_ONLY.search(text):
        raise OpenPolicyError("public page does not say host only")
    if require_open:
        if _OPENS_SOON.search(text):
            raise OpenPolicyError("public page still says Opens soon; Open is not on")
        if OPEN_CTA_PHRASE not in text.lower():
            raise OpenPolicyError("public Open page has no start a room CTA")
    else:
        if OPEN_CTA_PHRASE in text.lower():
            raise OpenPolicyError("teaser page must not expose the Open CTA")
    if not _NEIGHBOUR_DEMOTED.search(text) and "neighbour" in text.lower():
        raise OpenPolicyError("neighbour is mentioned without a later-season demote")
    return {
        "host_only": True,
        "neighbour_cta": False,
        "require_open": require_open,
    }


def public_page_document(raw: object | None = None) -> dict[str, Any]:
    """Staging double of the public Open page."""
    season = open_season(raw)
    if season == "open":
        body = OPEN_COPY
        kicker = ""
        cta = OPEN_CTA_PHRASE
    elif season == "teaser":
        body = TEASER_COPY
        kicker = "Opens soon"
        cta = None
    else:
        unreachable: object = season
        raise OpenPolicyError(f"unhandled open season {unreachable!r}")
    copy = f"{HOST_ONLY_PHRASE}. {body}"
    if kicker:
        copy = f"{kicker}. {copy}"
    if cta:
        copy = f"{copy} {cta}."
    check_public_page_text(copy, require_open=(season == "open"))
    return {
        "season": season,
        "target": P0_OPEN_TARGET,
        "guest": ESCAPE_GUEST,
        "neighbour": "later_season",
        "neighbour_cta": False,
        "bounty_wired": False,
        "kicker": kicker,
        "cta": cta,
        "copy": copy,
        "notice": (
            "PRACTICE STAGING ONLY: ESCAPE_OPEN is a labeled double, "
            "not the live switch name"
        ),
    }


def open_topology_fields(raw: object | None = None) -> dict[str, Any]:
    enabled = parse_open_switch(raw)
    return {
        "public_open": enabled,
        "open_target": P0_OPEN_TARGET,
        "neighbour_in_season": False,
        "bounty_wired": False,
        "open_switch_env": OPEN_SWITCH_ENV,
        "open_switch_notice": (
            "ESCAPE_OPEN is the staging/practice double. "
            "It is not the live switch name."
        ),
    }
