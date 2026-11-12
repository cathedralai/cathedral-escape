"""Isolation fence / placement checks (T1). No live broker: inventory is injected.

Rules:
1. Escape hotels are reserved and labeled for Escape.
2. Customer guests deny those hotels.
3. Escape never lands on a hotel that currently hosts a non-escape room.
4. When a dedicated Escape hotel exists, Escape must move there.
5. Only official entry guest is escape-sealed. Prefer sealed. Deny nc-sealed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .errors import EscapePracticeError, PlacementError
from .ids import require_safe_id

ESCAPE_GUEST = "escape-sealed"
SEALED_CLASS = "sealed"
DENIED_CLASSES = frozenset({"nc-sealed", "unsealed"})


@dataclass
class RoomOnHotel:
    room_id: str
    guest: str


@dataclass
class Hotel:
    hotel_id: str
    pool_class: str
    labels: dict[str, str] = field(default_factory=dict)
    reserved_for: str | None = None
    rooms: list[RoomOnHotel] = field(default_factory=list)
    dedicated_escape: bool = False

    def __post_init__(self) -> None:
        try:
            self.hotel_id = require_safe_id(self.hotel_id, "hotel_id")
        except EscapePracticeError as exc:
            raise PlacementError(str(exc)) from exc
        if not isinstance(self.pool_class, str) or not self.pool_class:
            raise PlacementError("pool_class required")

    def is_escape_reserved(self) -> bool:
        if self.labels.get("escape") == "true":
            return True
        if self.labels.get("reserved_for") == "escape":
            return True
        return self.reserved_for in ("escape", ESCAPE_GUEST)

    def hosts_non_escape(self) -> bool:
        return any(room.guest != ESCAPE_GUEST for room in self.rooms)


@dataclass
class Inventory:
    hotels: list[Hotel]

    def dedicated_escape_hotels(self) -> list[Hotel]:
        return [h for h in self.hotels if h.dedicated_escape and h.is_escape_reserved()]

    def get(self, hotel_id: str) -> Hotel:
        for hotel in self.hotels:
            if hotel.hotel_id == hotel_id:
                return hotel
        raise PlacementError(f"unknown hotel {hotel_id!r}; fail closed")


def _require_escape_guest(guest: object) -> str:
    if guest != ESCAPE_GUEST:
        raise PlacementError("only official entry guest is escape-sealed (Option B / T1)")
    return ESCAPE_GUEST


def place_escape_room(guest: object, hotel: Hotel, inventory: Inventory) -> Hotel:
    """Admit an Escape room onto hotel or raise PlacementError."""
    _require_escape_guest(guest)
    if hotel.pool_class in DENIED_CLASSES:
        raise PlacementError(f"deny {hotel.pool_class}; Escape never schedules onto nc-sealed")
    if hotel.pool_class != SEALED_CLASS:
        raise PlacementError("Escape must land on a sealed hotel")
    if not hotel.is_escape_reserved():
        raise PlacementError("hotel is not reserved/labeled for Escape")
    if hotel.hosts_non_escape():
        raise PlacementError("Escape never lands on a hotel hosting a non-escape room")
    dedicated = inventory.dedicated_escape_hotels()
    if dedicated and hotel.hotel_id not in {h.hotel_id for h in dedicated}:
        raise PlacementError(
            "dedicated Escape hotel exists; move there is required, not polish"
        )
    return hotel


def place_customer_room(guest: object, hotel: Hotel) -> Hotel:
    """Customer placement denies Escape-labeled hotels."""
    if not isinstance(guest, str) or not guest or guest == ESCAPE_GUEST:
        raise PlacementError("customer guest required")
    if hotel.is_escape_reserved():
        raise PlacementError("customer guests deny hotels labeled escape / reserved_for=escape")
    return hotel


def assert_prefer_sealed(prefer: Sequence[object]) -> None:
    if SEALED_CLASS not in prefer:
        raise PlacementError("Escape must prefer sealed")
    if any(item in DENIED_CLASSES for item in prefer):
        raise PlacementError("prefer must not include nc-sealed")
