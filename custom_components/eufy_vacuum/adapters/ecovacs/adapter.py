"""Ecovacs (Deebot) adapter — assembles + registers the adapter config for one vacuum.

Wraps the Home Assistant CORE ``ecovacs`` integration (``deebot-client``). Structure mirrors
``adapters/roborock/adapter.py`` and ``adapters/dreame/adapter.py``; the differences are all
consequences of what the upstream integration does and does not publish:

* ROOMS — the vacuum entity's ``rooms`` attribute, ``{slugified_name: id | [ids]}`` for the
  ACTIVE map. Declared as ``discovery.room_list_shape = "name_id_mapping"``.
* DISPATCH — ``vacuum.send_command`` ``spot_area`` ``{rooms: [ids], cleanings: n}`` through the
  shared ``generic_room_ids`` engine. ``params`` MUST stay a dict (upstream raises
  ``ServiceValidationError`` for a list), so ``params_as_list`` is deliberately absent.
* PER-ROOM SETTINGS — none on the wire. Suction (``vacuum.set_fan_speed``), water
  (``select.<obj>_water_flow_level``) and work mode (``select.<obj>_work_mode``) are
  DEVICE-GLOBAL, so they ride ``dispatch.global_pre_calls`` and per-room passes collapse to
  one batch scalar (``cleanings``).
* LIFECYCLE — there is no status sensor, so ``entities.task_status`` IS the vacuum entity
  and completion is its ``docked`` state, guarded by the framework's "observed active" check.
  The honest limitation: a mid-run recharge also reports ``docked`` and cannot be told apart
  from the end of a run from the entity alone.
* NO live pose / current-room entity exists, so the job segmenter and external-run room
  attribution are declared OFF explicitly (omission would silently run another brand's
  engine), and the native room-transition source stays off.

Everything here was assembled from the upstream source, not a probed device. Anything that
needs a real Deebot to confirm is marked ``# VERIFY``.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from ..entity_resolve import resolve_declared_entities
from ..registry import register_adapter_config
from . import vocabulary
from .const import ADAPTER_ID, LOW_BATTERY_THRESHOLD_PERCENT
from .entities import (
    ALL_SUFFIXES,
    DOMAIN_BINARY_SENSOR,
    DOMAIN_SELECT,
    DOMAIN_VACUUM,
    SUFFIX_ACTIVE_MAP,
    SUFFIX_BATTERY,
    SUFFIX_CLEANING_AREA,
    SUFFIX_CLEANING_TIME,
    SUFFIX_DOCK_STATUS,
    SUFFIX_ERROR_MESSAGE,
    SUFFIX_MOP_ATTACHED,
    SUFFIX_TOTAL_CLEANING_AREA,
    SUFFIX_TOTAL_CLEANING_COUNT,
    SUFFIX_TOTAL_CLEANING_TIME,
    SUFFIX_WATER_AMOUNT,
    SUFFIX_WORK_MODE,
    build_entity_id,
)
from .maintenance_components import MAINTENANCE_COMPONENTS
from .model_catalog import profile_for_model

_LOGGER = logging.getLogger(__name__)


def _device_for_vacuum(hass: HomeAssistant, vacuum_entity_id: str):
    """Return the device-registry entry backing this vacuum, or None."""
    entry = er.async_get(hass).async_get(vacuum_entity_id)
    if entry is None or entry.device_id is None:
        return None
    return dr.async_get(hass).async_get(entry.device_id)


def _narrow(options: list[dict], live_values) -> list[dict]:
    """Keep the declared rungs the device actually publishes, in DECLARED (ascending) order.

    The declared list is the ladder; the live list only says which rungs this model has.
    An empty/absent live list (cold boot, entity not up yet) keeps the full declared
    ladder rather than collapsing it. A live list sharing no word with the declared one
    also keeps the declared ladder — better the documented superset than an empty picker.
    """
    live = {str(v).strip().lower() for v in (live_values or []) if str(v).strip()}
    if not live:
        return list(options)
    kept = [o for o in options if str(o["value"]).lower() in live]
    return kept or list(options)


def register_ecovacs_adapter_for_vacuum(
    hass: HomeAssistant,
    vacuum_entity_id: str,
    *,
    entity_overrides: dict[str, str] | None = None,
) -> None:
    """Assemble and register the Ecovacs adapter config for one vacuum.

    Idempotent — re-calling for the same vacuum overwrites the previous registration.
    """
    from ...core.capabilities import detect_capabilities

    vid = vacuum_entity_id

    # --- model identity (device registry — the supported public source) -------
    device = _device_for_vacuum(hass, vid)
    # ``model`` is the free-text deviceName; ``model_id`` is the stable product class.
    detected_model = (
        (device.model_id or device.model) if device is not None else None
    )
    profile = profile_for_model(detected_model)

    water_id = build_entity_id(vid, SUFFIX_WATER_AMOUNT, DOMAIN_SELECT)
    work_mode_id = build_entity_id(vid, SUFFIX_WORK_MODE, DOMAIN_SELECT)
    water_state = hass.states.get(water_id)
    vacuum_state = hass.states.get(vid)

    # A mop is only controllable when the integration created the water select. The model
    # profile is the fallback for the cold-boot window; entity PRESENCE decides otherwise.
    water_registered = er.async_get(hass).async_get(water_id) is not None
    mop_settable = bool(
        profile["has_mop"] and (water_state is not None or water_registered)
    )

    fan_options = _narrow(
        vocabulary.FAN_SPEED_OPTIONS,
        (vacuum_state.attributes.get("fan_speed_list") if vacuum_state else None),
    )
    water_options = _narrow(
        vocabulary.WATER_LEVEL_OPTIONS,
        (water_state.attributes.get("options") if water_state else None),
    )
    fan_rank = [o["value"] for o in fan_options]
    water_rank = [o["value"] for o in water_options]

    has_station = bool(profile["has_station"])
    station_washable = bool(profile.get("station_washable", has_station))
    station_dryable = bool(profile.get("station_dryable", has_station))
    station_collectable = bool(profile.get("station_collectable", has_station))

    # --- global pre-calls (the ONLY way a per-room setting reaches this device) ---
    global_pre_calls: list[dict] = [
        {
            # Suction: max-wins across the batch (a fan entry must NOT carry a
            # "safest" policy, or suction drops to the weakest room's setting).
            "field": "fan_speed",
            "rank": fan_rank,
            "service": {
                "domain": DOMAIN_VACUUM,
                "service": "set_fan_speed",
                "value_key": "fan_speed",
            },
        },
    ]
    if mop_settable:
        global_pre_calls.append(
            {
                # Water is device-GLOBAL and has no "off" rung, so a mixed mop + vacuum
                # batch cannot zero it per room. ``safest`` makes a MIXED batch take the
                # LOWEST requested level instead of max-wins. Not best-effort under
                # ``safest``: a missing/rejected target aborts the dispatch, deliberately
                # (see dispatch/manager.py::_run_global_pre_calls).
                "field": "water_level",
                "rank": water_rank,
                "mixed_mode_water_policy": "safest",
                "service": {
                    "domain": DOMAIN_SELECT,
                    "service": "select_option",
                    "value_key": "option",
                    # BY ROLE so a rescued / renamed entity receives the push.
                    "target_role": "mop_intensity",
                },
            }
        )
        global_pre_calls.append(
            {
                # Work mode (vacuum / mop / vacuum+mop). Ordered MOST-cautious-FIRST so
                # max-wins resolves a mixed batch to the SAFEST mode: a batch containing
                # any vacuum-only room runs vacuum-only (under-mop is accepted over
                # wet-mop, the same asymmetry as ``mixed_mode_water_policy``). This rank
                # is a tie-break order, NOT an option list, so §9a's ordering rule (which
                # governs ``*_options``) does not apply to it.
                # The select is DISABLED BY DEFAULT upstream; absent target => the call is
                # logged and skipped (best-effort entry), and the device keeps its mode.
                "field": "clean_mode",
                "rank": ["vacuum_mop", "mop", "vacuum"],
                "value_map": vocabulary.CLEAN_MODE_VALUE_MAP,
                "service": {
                    "domain": DOMAIN_SELECT,
                    "service": "select_option",
                    "value_key": "option",
                    "target_entity_id": work_mode_id,
                },
            }
        )

    # --- capability gating ----------------------------------------------------
    entity_candidates: dict[str, list[str]] = {
        "dock_status": [build_entity_id(vid, SUFFIX_DOCK_STATUS)],
        "active_map": [build_entity_id(vid, SUFFIX_ACTIVE_MAP, DOMAIN_SELECT)],
        "cleaning_time": [build_entity_id(vid, SUFFIX_CLEANING_TIME)],
        "cleaning_area": [build_entity_id(vid, SUFFIX_CLEANING_AREA)],
    }
    capability_hints: dict[str, bool] = {
        "supports_mop_features": bool(profile["has_mop"]),
        "supports_mop_wash": station_washable,
        "supports_mop_dry": station_dryable,
        "supports_empty_dust": station_collectable,
        # FAIL CLOSED. ``custom_area`` takes coordinates in the device's own map frame and
        # this adapter does not yet convert the card's normalized box to it. Declared False
        # explicitly: the key must be PRESENT as False to disable (capabilities._hint_wins).
        "supports_zone_clean": False,
        "supports_path_control": False,
        "supports_goto": False,
        "supports_edge_mopping": False,
    }
    caps = detect_capabilities(
        hass,
        vacuum_entity_id=vid,
        detected_model=detected_model,
        entity_candidates=entity_candidates,
        model_family=profile["family"],
        capability_hints=capability_hints,
        entity_overrides=entity_overrides or {},
        maintenance_components=MAINTENANCE_COMPONENTS,
        # Arms the live:ENT-4 guard: a per-run metric must not be claimed by its lifetime
        # namesake (``_area_cleaned`` vs ``_total_area_cleaned``).
        reserved_suffixes=ALL_SUFFIXES,
    )

    # --- entity ID map --------------------------------------------------------
    entities = {
        # THE VACUUM ENTITY IS THE LIFECYCLE SOURCE — upstream publishes no status sensor.
        "task_status": vid,
        "active_map": build_entity_id(vid, SUFFIX_ACTIVE_MAP, DOMAIN_SELECT),
        "cleaning_time": build_entity_id(vid, SUFFIX_CLEANING_TIME),
        "cleaning_area": build_entity_id(vid, SUFFIX_CLEANING_AREA),
        "battery": build_entity_id(vid, SUFFIX_BATTERY),
        "error_message": build_entity_id(vid, SUFFIX_ERROR_MESSAGE),
        "dock_status": build_entity_id(vid, SUFFIX_DOCK_STATUS),
        "total_cleaning_area": build_entity_id(vid, SUFFIX_TOTAL_CLEANING_AREA),
        "total_cleaning_time": build_entity_id(vid, SUFFIX_TOTAL_CLEANING_TIME),
        "total_cleaning_count": build_entity_id(vid, SUFFIX_TOTAL_CLEANING_COUNT),
        # The global water select, named by role so the pre-call above resolves it at
        # call time (same role Roborock uses for its global mop-intensity select).
        "mop_intensity": water_id,
        "mop_active": build_entity_id(vid, SUFFIX_MOP_ATTACHED, DOMAIN_BINARY_SENSOR),
    }
    entities, entity_remaps = resolve_declared_entities(
        hass,
        vid,
        entities,
        overrides=entity_overrides,
        reserved_suffixes=ALL_SUFFIXES,
    )

    config = {
        "adapter_id": ADAPTER_ID,
        "source": "code",
        "display_name": profile["display_name"],
        "brand": "Ecovacs",
        # ``sensor.<obj>_cleaning_duration`` is a DURATION sensor whose native unit is
        # seconds with a SUGGESTED unit of minutes; HA reports the converted value.
        # VERIFY on a device: if the state reads in seconds, change this to "s".
        "cleaning_time_unit": "min",
        "entities": entities,
        "vocabulary": {
            "fan_speed_options": fan_options,
            "water_level_options": water_options,
            "clean_mode_options": vocabulary.CLEAN_MODE_OPTIONS,
            "not_error_sentinels": list(vocabulary.NOT_ERROR_SENTINELS),
            "active_run_task_states": sorted(vocabulary.ACTIVE_RUN_TASK_STATES),
        },
        "error_tracking": {
            # ``sensor.<obj>_error`` state IS the code (numeric string); the description is
            # an attribute. Mirrors Roborock's message_is_code route.
            "message_is_code": True,
            "task_status_error_value": "error",
            "grace_window_seconds": 5,
            "default_error_source": "robot",
            "unknown_error_message": "Unknown error during run",
        },
        # core owns the room-profile KEYS; the adapter owns every VALUE.
        "room_profiles": {
            "default_profile": "vacuum_quick",
            "builtins": vocabulary.ROOM_PROFILES,
            "custom_template": vocabulary.CUSTOM_ROOM_PROFILE,
            "normalize_defaults": vocabulary.CUSTOM_ROOM_PROFILE,
            "floor_type_water_defaults": vocabulary.FLOOR_TYPE_WATER_DEFAULTS,
            "floor_type_fan_defaults": vocabulary.FLOOR_TYPE_FAN_DEFAULTS,
            "legacy_aliases": vocabulary.LEGACY_ALIASES,
        },
        # REPLICA RNQ433CB — every card-facing flag here is copied by hand into the
        # dashboard snapshot at core/manager.py; add a flag here AND there or the card
        # never sees it (silent, all-green). See docs/dev/00c-replicas.md.
        "capabilities": {
            "supports_mop_features": caps.get(
                "supports_mop_features", bool(profile["has_mop"])
            ),
            "supports_water_control": mop_settable,
            "supports_mop_wash": caps.get("supports_mop_wash", station_washable),
            "supports_mop_dry": caps.get("supports_mop_dry", station_dryable),
            "supports_empty_dust": caps.get("supports_empty_dust", station_collectable),
            "supports_path_control": False,
            "supports_edge_mopping": False,
            "supports_zone_clean": False,
            "supports_goto": False,
            # Deebots with a map clean rooms in the order given. VERIFY on a device; if a
            # model re-orders for path efficiency, set False (gates strict-order opt-in).
            "honors_clean_order": True,
        },
        "charging": {
            "low_battery_threshold_percent": LOW_BATTERY_THRESHOLD_PERCENT,
        },
        # Completion keys on the vacuum entity reaching ``docked`` AFTER it was observed
        # active. There is no secondary "target cleared" signal (no current-room entity),
        # so the gate collapses to task_status alone — see the module docstring for the
        # mid-run-recharge caveat.
        "completion": {
            "task_status_value": "docked",
        },
        # Room clean: vacuum.send_command spot_area {rooms: [ids], cleanings: n}.
        "dispatch": {
            "template": "generic_room_ids",
            "service_domain": "vacuum",
            "service_name": "send_command",
            # `command` MUST be explicit — an absent key defaults to Eufy's `room_clean`.
            "command": "spot_area",
            "rooms_field": "rooms",
            "clean_passes_field": "cleanings",
            # `cleanings` is ONE batch scalar; the engine collapses to the max requested.
            "passes_max": 2,
            "passes_is_global": True,
            # params stays a DICT: the integration raises ServiceValidationError for a list.
            "global_pre_calls": global_pre_calls,
        },
        # No structured map geometry from this integration (the map is an SVG image).
        "mapping": {
            "segmenter_engine": "noop_fallback",
            "segmenter_tuning": {},
            "live_map_image_entity_pattern": "image.{object_id}_map",
        },
        # No counter stream to plateau-detect and no native current-room signal: declare
        # both engines OFF explicitly rather than inherit another brand's.
        "job_segmenter": {"engine": "noop_job_fallback"},
        "room_attribution": {
            "engine": "noop_room_attribution",
            "tuning": {},
        },
        "live_transition": {"enabled": False},
        # Rooms: the vacuum entity's `rooms` attribute, {slug: id | [ids]}, active map only.
        "discovery": {
            "source": "entity_attribute",
            "room_list_shape": "name_id_mapping",
            "room_list_entity": "vacuum_entity",
            "room_list_attribute": "rooms",
            "room_id_key": "id",
            "room_name_key": "name",
            # The active-map select is only created for multi-map models; a single-map
            # Deebot leaves it absent, so opt in to the single implicit map anchor.
            "implicit_map_id": "Main",
        },
        "setup": {
            "steps": ["add_vacuum", "import_active_map", "save_rooms"],
        },
        # Projected the way Roborock/Dreame project theirs: the schema requires
        # sensor_suffix + both interval fields on every entry.
        "maintenance_components": {
            component_id: {
                "sensor_suffix": component.get("sensor_suffix"),
                "maintenance_only": component.get("maintenance_only", False),
                "default_interval_hours": component.get("default_interval_hours", 0.0),
                "max_interval_hours": component.get("max_interval_hours", 0.0),
                "label": component["label"],
                "icon": component["icon"],
                **(
                    {"reset_button": component["reset_button"]}
                    if component.get("reset_button")
                    else {}
                ),
            }
            for component_id, component in MAINTENANCE_COMPONENTS.items()
        },
        # Dock wash/dry/empty observation + the three station action buttons
        # (``button.<obj>_wash_mop`` / ``_dry_mop`` / ``_empty_dustbin``). The station sensor
        # states are deebot-client's ``station.State`` names.
        "dock_events": {
            "enabled": True,
            "triggers": {
                "last_mop_wash": ["washing_mop"],
                "last_dry_start": ["drying_mop"],
                "last_dust_empty": ["emptying_dustbin"],
            },
            "debounce_seconds": {"last_mop_wash": 60},
            "action_controls": {
                "wash_mop": {
                    "entity_suffixes": ["wash_mop"],
                    "token_sets": [["wash", "mop"]],
                },
                "dry_mop": {
                    "entity_suffixes": ["dry_mop"],
                    "token_sets": [["dry", "mop"]],
                },
                "empty_dust": {
                    "entity_suffixes": ["empty_dustbin"],
                    "token_sets": [["empty", "dustbin"]],
                },
            },
        },
        # Bookkeeping so manager.refresh_vacuum_capabilities reproduces registration's
        # detect_capabilities INPUTS. Underscore keys are unknown-key-check exempt.
        "model_family": profile["family"],
        "capability_hints": dict(capability_hints),
        "_entity_candidates": entity_candidates,
        "_entity_remaps": entity_remaps,
        "_entity_overrides": dict(entity_overrides or {}),
        "_reserved_suffixes": list(ALL_SUFFIXES),
    }

    register_adapter_config(vid, config)
    _LOGGER.debug(
        "%s: registered adapter for %s (model=%s, mop_settable=%s)",
        ADAPTER_ID, vid, detected_model, mop_settable,
    )
