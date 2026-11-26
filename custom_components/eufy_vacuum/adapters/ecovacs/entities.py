"""Ecovacs (HA core ``ecovacs`` integration) entity name patterns + builder.

The integration sets ``_attr_has_entity_name = True`` and names each companion entity from
its translation (``strings.json``), so HA derives the object id as
``{vacuum_object_id}_{slugified_name}``:

    sensor.{object_id}_area_cleaned          ("Area cleaned"      stats_area)
    sensor.{object_id}_cleaning_duration     ("Cleaning duration" stats_time)
    sensor.{object_id}_main_brush_lifespan   ("Main brush lifespan")
    select.{object_id}_water_flow_level      ("Water flow level"  water_amount)
    button.{object_id}_wash_mop              ("Wash mop"          station action)
    image.{object_id}_map                    ("Map")

Suffixes below are read from the upstream ``strings.json`` entity names, NOT from a live
device: the install this was written for had not been probed. The shared entity resolver
(``resolve_declared_entities``) repairs a localized / renamed id by translation_key where
it can, and ``entity_overrides`` lets a user pin the rest.

There is deliberately NO task-status / charging / current-room suffix here: the upstream
integration publishes none. The vacuum entity's own state (cleaning / returning / docked /
paused / idle / error) is the lifecycle signal — see ``adapter.py``.
"""

from __future__ import annotations

# === STATS (per-run, then lifetime) =====================================
SUFFIX_CLEANING_TIME = "_cleaning_duration"          # sensor — per-run (HA converts s -> min)
SUFFIX_CLEANING_AREA = "_area_cleaned"               # sensor — per-run m2
# Lifetime halves of the per-run pair — declared so they enter ALL_SUFFIXES and the
# live:ENT-4 exclusivity guard can tell a per-run metric from its lifetime namesake
# (``_area_cleaned`` is an endswith-match of ``_total_area_cleaned``).
SUFFIX_TOTAL_CLEANING_AREA = "_total_area_cleaned"        # sensor — lifetime m2
SUFFIX_TOTAL_CLEANING_TIME = "_total_cleaning_duration"   # sensor — lifetime
SUFFIX_TOTAL_CLEANING_COUNT = "_total_cleanings"          # sensor — lifetime runs

# === DEVICE ==============================================================
SUFFIX_BATTERY = "_battery"                          # sensor
SUFFIX_ERROR_MESSAGE = "_error"                      # sensor — error CODE (description attr)
SUFFIX_DOCK_STATUS = "_station_state"                # sensor enum — idle/washing_mop/drying_mop/emptying_dustbin
SUFFIX_ACTIVE_MAP = "_active_map"                    # select — multi-map pointer
SUFFIX_WATER_AMOUNT = "_water_flow_level"            # select (low/medium/high/ultrahigh) OR number
SUFFIX_WORK_MODE = "_work_mode"                      # select — vacuum/mop/vacuum_and_mop/mop_after_vacuum
SUFFIX_CLEAN_COUNT = "_clean_count"                  # number — device clean passes (1..4)
SUFFIX_MOP_ATTACHED = "_mop_attached"                # binary_sensor — mop pad / tank present
SUFFIX_MAP = "_map"                                  # image (SVG)

# === ENTITY DOMAINS ======================================================
DOMAIN_VACUUM = "vacuum"
DOMAIN_SENSOR = "sensor"
DOMAIN_BINARY_SENSOR = "binary_sensor"
DOMAIN_SELECT = "select"
DOMAIN_NUMBER = "number"
DOMAIN_BUTTON = "button"
DOMAIN_IMAGE = "image"


#: Every entity suffix this adapter knows, derived from the ``SUFFIX_*`` constants rather
#: than hand-listed (a hand list drifts the moment a suffix is added). Consumed as
#: ``reserved_suffixes`` so sibling matching can tell when a LONGER declared suffix
#: already owns an entity.
ALL_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        {
            value
            for name, value in list(globals().items())
            if name.startswith("SUFFIX_") and isinstance(value, str) and value
        }
    )
)


def build_entity_id(
    vacuum_entity_id: str,
    suffix: str,
    domain: str = DOMAIN_SENSOR,
) -> str:
    """Return the full HA entity ID for one companion entity.

    ``build_entity_id("vacuum.deebot", "_area_cleaned")`` -> ``"sensor.deebot_area_cleaned"``.
    """
    object_id = vacuum_entity_id.split(".", 1)[-1]
    return f"{domain}.{object_id}{suffix}"
