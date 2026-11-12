from __future__ import annotations

import pytest

from escape_practice.errors import PlacementError
from escape_practice.placement import (
    Hotel,
    Inventory,
    RoomOnHotel,
    assert_prefer_sealed,
    place_customer_room,
    place_escape_room,
)


def _escape_hotel(**kwargs: object) -> Hotel:
    values: dict = {
        "hotel_id": "escape-hotel-1",
        "pool_class": "sealed",
        "labels": {"escape": "true", "reserved_for": "escape"},
        "reserved_for": "escape",
        "rooms": [],
        "dedicated_escape": False,
    }
    values.update(kwargs)
    return Hotel(**values)


def test_escape_lands_on_reserved_sealed_hotel() -> None:
    hotel = _escape_hotel()
    inventory = Inventory(hotels=[hotel])
    assert place_escape_room("escape-sealed", hotel, inventory) is hotel


def test_deny_nc_sealed() -> None:
    hotel = _escape_hotel(hotel_id="nc", pool_class="nc-sealed")
    with pytest.raises(PlacementError, match="nc-sealed"):
        place_escape_room("escape-sealed", hotel, Inventory(hotels=[hotel]))


def test_deny_non_escape_guest() -> None:
    hotel = _escape_hotel()
    with pytest.raises(PlacementError, match="escape-sealed"):
        place_escape_room("polaris", hotel, Inventory(hotels=[hotel]))


def test_deny_unlabeled_customer_hotel() -> None:
    hotel = Hotel(hotel_id="cust-1", pool_class="sealed", labels={})
    with pytest.raises(PlacementError, match="reserved/labeled"):
        place_escape_room("escape-sealed", hotel, Inventory(hotels=[hotel]))


def test_deny_hotel_hosting_customer_room() -> None:
    hotel = _escape_hotel(rooms=[RoomOnHotel("cust-room", "polaris")])
    with pytest.raises(PlacementError, match="non-escape"):
        place_escape_room("escape-sealed", hotel, Inventory(hotels=[hotel]))


def test_move_to_dedicated_escape_hotel_is_required() -> None:
    shared = _escape_hotel(hotel_id="shared-escape")
    dedicated = _escape_hotel(hotel_id="dedicated-escape", dedicated_escape=True)
    inventory = Inventory(hotels=[shared, dedicated])
    with pytest.raises(PlacementError, match="dedicated"):
        place_escape_room("escape-sealed", shared, inventory)
    assert place_escape_room("escape-sealed", dedicated, inventory) is dedicated


def test_customer_denied_on_escape_hotel() -> None:
    hotel = _escape_hotel()
    with pytest.raises(PlacementError, match="customer guests deny"):
        place_customer_room("polaris", hotel)


def test_customer_ok_on_customer_hotel() -> None:
    hotel = Hotel(hotel_id="cust-1", pool_class="sealed", labels={})
    assert place_customer_room("polaris", hotel) is hotel


def test_empty_hotel_id_fails_closed() -> None:
    with pytest.raises(PlacementError, match="hotel_id"):
        Hotel(hotel_id="", pool_class="sealed", labels={"escape": "true"})


def test_prefer_sealed_required() -> None:
    with pytest.raises(PlacementError, match="prefer sealed"):
        assert_prefer_sealed(["unsealed"])
    with pytest.raises(PlacementError, match="nc-sealed"):
        assert_prefer_sealed(["sealed", "nc-sealed"])
    assert_prefer_sealed(["sealed"])
