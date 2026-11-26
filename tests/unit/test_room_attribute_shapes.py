"""``normalize_room_attribute`` -- the one place a ``name_id_mapping`` becomes a room list.

[RAS-1] every shape other than ``name_id_mapping`` is returned UNTOUCHED, so the three
        existing brands' discovery is byte-identical.
[RAS-2] ``{name: id}`` -> ``[{id, name}]``, with the device's slug shown as a title.
[RAS-3] a name that carries several ids (the device repeats a room name) is numbered so
        every id stays addressable instead of the later ones being dropped.
[RAS-4] anything that is not a mapping is "missing or invalid" (None), never an empty list
        that would read as "this map has no rooms".
"""

from __future__ import annotations

import pytest

from custom_components.eufy_vacuum.rooms.source_refresh import (
    SHAPE_NAME_ID_MAPPING,
    normalize_room_attribute,
)


@pytest.mark.parametrize("shape", [None, "flat_list", "per_map_mapping"])
def test_other_shapes_pass_through_untouched(shape):
    """[RAS-1]"""
    raw = [{"id": 1, "name": "Kitchen"}]
    assert normalize_room_attribute(raw, shape) is raw
    mapping = {"Main": [{"id": 1}]}
    assert normalize_room_attribute(mapping, shape) is mapping


def test_name_id_mapping_flattens_and_titles():
    """[RAS-2]"""
    rows = normalize_room_attribute(
        {"living_room": 1, "kitchen": 4}, SHAPE_NAME_ID_MAPPING
    )
    assert rows == [
        {"id": 1, "name": "Living Room"},
        {"id": 4, "name": "Kitchen"},
    ]


def test_repeated_name_keeps_every_id():
    """[RAS-3]"""
    rows = normalize_room_attribute({"bedroom": [2, 3]}, SHAPE_NAME_ID_MAPPING)
    assert rows == [
        {"id": 2, "name": "Bedroom 1"},
        {"id": 3, "name": "Bedroom 2"},
    ]


@pytest.mark.parametrize("raw", [None, [], "rooms", 3])
def test_non_mapping_is_invalid_not_empty(raw):
    """[RAS-4]"""
    assert normalize_room_attribute(raw, SHAPE_NAME_ID_MAPPING) is None
