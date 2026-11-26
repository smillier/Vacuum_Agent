"""Ecovacs adapter config-shape assertions.

The Ecovacs adapter wraps the HA CORE ``ecovacs`` integration, which publishes no status
sensor, no current-room entity and no per-room settings. These tests pin the places where
that shapes the config, because each was a decision rather than a default:

[ECO-1] the VACUUM entity is the lifecycle source and completion keys on ``docked``.
[ECO-2] dispatch is ``spot_area`` through the shared ``generic_room_ids`` engine, with a
        DICT ``params`` (the integration raises on a list) -- so ``params_as_list`` is absent.
[ECO-3] rooms are read from the vacuum ``rooms`` attribute as a ``name_id_mapping``.
[ECO-4] both run-segmentation engines are declared OFF explicitly (omission would silently
        run another brand's counter-plateau / winding engine).
[ECO-5] the brand claims exactly the ``ecovacs`` platform.
[ECO-6] a mop-capable install (water select present) gets the water + work-mode pre-calls;
        a mop-less one gets suction only, so the strict ``safest`` water entry can never
        abort a vacuum-only robot's clean on a target that does not exist.
[ECO-7] the fan / water ladders narrow to what the live entities publish.
"""

from __future__ import annotations

import pytest

from custom_components.eufy_vacuum.adapters.ecovacs.adapter import (
    register_ecovacs_adapter_for_vacuum,
)
from custom_components.eufy_vacuum.adapters.ecovacs.const import UPSTREAM_PLATFORMS
from custom_components.eufy_vacuum.adapters.registry import get_adapter_config

_VAC = "vacuum.deebot_cfg"


@pytest.fixture
def ecovacs_config(hass):
    hass.states.async_set(_VAC, "docked", {"fan_speed_list": ["quiet", "normal", "max"]})
    register_ecovacs_adapter_for_vacuum(hass, _VAC)
    return get_adapter_config(_VAC)


def test_vacuum_entity_is_the_lifecycle_source(ecovacs_config):
    """[ECO-1]"""
    assert ecovacs_config["entities"]["task_status"] == _VAC
    assert ecovacs_config["completion"]["task_status_value"] == "docked"


def test_dispatch_is_spot_area_with_dict_params(ecovacs_config):
    """[ECO-2]"""
    dispatch = ecovacs_config["dispatch"]
    assert dispatch["template"] == "generic_room_ids"
    assert dispatch["command"] == "spot_area"
    assert dispatch["rooms_field"] == "rooms"
    assert dispatch["clean_passes_field"] == "cleanings"
    assert dispatch["passes_is_global"] is True
    assert "params_as_list" not in dispatch


def test_rooms_are_a_name_id_mapping_on_the_vacuum_attribute(ecovacs_config):
    """[ECO-3]"""
    discovery = ecovacs_config["discovery"]
    assert discovery["room_list_shape"] == "name_id_mapping"
    assert discovery["room_list_entity"] == "vacuum_entity"
    assert discovery["room_list_attribute"] == "rooms"


def test_segmentation_engines_are_declared_off(ecovacs_config):
    """[ECO-4]"""
    assert ecovacs_config["job_segmenter"]["engine"] == "noop_job_fallback"
    assert ecovacs_config["room_attribution"]["engine"] == "noop_room_attribution"
    assert ecovacs_config["live_transition"]["enabled"] is False


def test_brand_claims_the_core_ecovacs_platform():
    """[ECO-5]"""
    assert UPSTREAM_PLATFORMS == ("ecovacs",)


def test_mopless_install_gets_suction_precall_only(ecovacs_config):
    """[ECO-6] no water select in the state machine or registry => no mop pre-calls."""
    fields = [e["field"] for e in ecovacs_config["dispatch"]["global_pre_calls"]]
    assert fields == ["fan_speed"]
    assert ecovacs_config["capabilities"]["supports_water_control"] is False


def test_mop_install_gets_water_and_work_mode_precalls(hass):
    """[ECO-6] a water select present => water (safest) + work-mode pre-calls."""
    vid = "vacuum.deebot_mop"
    hass.states.async_set(vid, "docked", {"fan_speed_list": ["quiet", "normal", "max"]})
    hass.states.async_set(
        "select.deebot_mop_water_flow_level", "medium", {"options": ["low", "medium", "high"]}
    )
    register_ecovacs_adapter_for_vacuum(hass, vid)
    cfg = get_adapter_config(vid)
    pre = {e["field"]: e for e in cfg["dispatch"]["global_pre_calls"]}
    assert set(pre) == {"fan_speed", "water_level", "clean_mode"}
    assert pre["water_level"]["mixed_mode_water_policy"] == "safest"
    assert pre["water_level"]["service"]["target_role"] == "mop_intensity"
    # A batch with any vacuum-only room must resolve to the safest (vacuum) work mode.
    assert pre["clean_mode"]["rank"][-1] == "vacuum"
    assert cfg["capabilities"]["supports_water_control"] is True


def test_ladders_narrow_to_live_options(hass):
    """[ECO-7]"""
    vid = "vacuum.deebot_narrow"
    hass.states.async_set(vid, "docked", {"fan_speed_list": ["quiet", "normal", "max"]})
    hass.states.async_set(
        "select.deebot_narrow_water_flow_level", "low", {"options": ["low", "medium"]}
    )
    register_ecovacs_adapter_for_vacuum(hass, vid)
    vocab = get_adapter_config(vid)["vocabulary"]
    assert [o["value"] for o in vocab["fan_speed_options"]] == ["quiet", "normal", "max"]
    assert [o["value"] for o in vocab["water_level_options"]] == ["low", "medium"]
