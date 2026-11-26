"""Ecovacs vocabulary — the words the HA core ``ecovacs`` integration speaks.

EVERY WORD HERE IS READ FROM UPSTREAM SOURCE, NOT A LIVE DEVICE. They come from the core
integration (``vacuum.py`` / ``select.py`` / ``strings.json``) and the ``deebot-client``
enums it names with ``get_name_key`` (``enum.name.lower()``):

    FanSpeedLevel   QUIET, NORMAL, MAX, MAX_PLUS            (low -> high, per upstream comment)
    WaterAmount     LOW, MEDIUM, HIGH, ULTRAHIGH
    WorkMode        VACUUM_AND_MOP, VACUUM, MOP, MOP_AFTER_VACUUM
    station State   IDLE, EMPTYING_DUSTBIN, WASHING_MOP, DRYING_MOP
    vacuum state    idle / cleaning / returning / docked / error / paused   (HA VacuumActivity)

⚠ Suction differs from Dreame/Roborock in one word that matters: the middle rung is
``normal``, not ``standard``/``balanced``. The option lists below follow the DEVICE's
spelling, because ``vacuum.set_fan_speed`` is validated against the entity's own
``fan_speed_list``.

⚠ What the device exposes per MODEL varies (``caps.fan_speed.types``, ``caps.water.amount``).
The adapter narrows these ladders to what the live entity publishes at registration; the
lists here are the full superset and the fallback for the cold-boot window.

LISTS ARE ORDERED LEAST EFFORT FIRST (porting guide §9a): index 0 = quietest / least water.
"""

from __future__ import annotations

# --- option vocabularies ------------------------------------------------------

#: ``vacuum.<obj>`` ``fan_speed_list`` (also the value ``vacuum.set_fan_speed`` takes).
FAN_SPEED_OPTIONS: list[dict] = [
    {"value": "quiet", "label": "Quiet"},
    {"value": "normal", "label": "Standard"},
    {"value": "max", "label": "Max"},
    {"value": "max_plus", "label": "Max+"},
]

#: ``select.<obj>_water_flow_level`` options. THERE IS NO "OFF" on this axis: whether the
#: mop runs at all is the WORK MODE, not a zero water level (the same shape as Dreame, and
#: the reason ``FLOOR_TYPE_WATER_DEFAULTS`` is empty — see the note there).
WATER_LEVEL_OPTIONS: list[dict] = [
    {"value": "low", "label": "Low"},
    {"value": "medium", "label": "Medium"},
    {"value": "high", "label": "High"},
    {"value": "ultrahigh", "label": "Ultrahigh"},
]

#: CANONICAL framework values (see ``profiles/room_profiles.py::canonical_clean_mode``);
#: ``CLEAN_MODE_VALUE_MAP`` translates to the device's ``work_mode`` words at dispatch.
CLEAN_MODE_OPTIONS: list[dict] = [
    {"value": "vacuum", "label": "Vacuum"},
    {"value": "mop", "label": "Mop"},
    {"value": "vacuum_mop", "label": "Vacuum & Mop"},
]

#: canonical -> ``select.<obj>_work_mode`` option. ``mop_after_vacuum`` (a fourth device
#: mode) is intentionally not a canonical mode: the framework has no "sequenced within one
#: room" concept, and the user can still pick it in the Ecovacs app.
CLEAN_MODE_VALUE_MAP: dict[str, str] = {
    "vacuum": "vacuum",
    "mop": "mop",
    "vacuum_mop": "vacuum_and_mop",
}

# --- room profiles ------------------------------------------------------------
#
# Same profile KEYS as every brand so stored rooms and the picker survive a brand switch;
# only the VALUES are Ecovacs'. No ``clean_intensity`` / ``path_type`` axis: Ecovacs exposes
# no per-room (or even global) pass-density setting through the core integration.
# ``water_level`` is "" on a vacuum-only profile — there is no no-water word to write.

ROOM_PROFILES: dict[str, dict] = {
    "vacuum_quick": {
        "label": "Vacuum Only Quick",
        "clean_mode": "vacuum",
        "fan_speed": "normal",
        "water_level": "",
        "clean_passes": 1,
        "edge_mopping": False,
        "mop_required": False,
    },
    "vacuum_deep": {
        "label": "Vacuum Only Deep",
        "clean_mode": "vacuum",
        "fan_speed": "max",
        "water_level": "",
        "clean_passes": 2,
        "edge_mopping": False,
        "mop_required": False,
    },
    "vacuum_mop_quick": {
        "label": "Quick",
        "clean_mode": "vacuum_mop",
        "fan_speed": "normal",
        "water_level": "medium",
        "clean_passes": 1,
        "edge_mopping": False,
        "mop_required": True,
    },
    "vacuum_mop_deep": {
        "label": "Deep",
        "clean_mode": "vacuum_mop",
        "fan_speed": "max",
        "water_level": "high",
        "clean_passes": 2,
        # No per-room (or any) edge-mop control in the core integration.
        "edge_mopping": False,
        "mop_required": True,
    },
}

#: The user-editable slot. Vacuum-only and dry, matching every sibling.
CUSTOM_ROOM_PROFILE: dict = {
    "label": "User Profile 1",
    "clean_mode": "vacuum",
    "fan_speed": "normal",
    "water_level": "",
    "clean_passes": 1,
    "edge_mopping": False,
    "mop_required": False,
}

#: ⚠ DELIBERATELY EMPTY, AND NOT AN OMISSION. ``profiles/room_profiles.py::no_water_value``
#: reads the carpet entry as "this brand's word for no water" — and Ecovacs has none (the
#: lowest rung is ``low``). Inventing "off" would put a value on the wire that is not in the
#: device's option list, and the dispatch ``options_key`` filter would drop it silently.
#: The carpet guarantee is still enforced by the MODE DOWNGRADE in ``profiles/manager.py``
#: (a carpet room in a mop mode is rewritten to ``vacuum``), which this brand's
#: ``CLEAN_MODE_VALUE_MAP`` sends as ``work_mode: vacuum``. Same reasoning as Dreame.
FLOOR_TYPE_WATER_DEFAULTS: dict[str, str] = {}

#: Carpet suction boost, kept for the same reason the siblings keep theirs.
FLOOR_TYPE_FAN_DEFAULTS: dict[str, str] = {
    "carpet_low_pile": "max",
    "carpet_high_pile": "max_plus",
}

#: DECLARED EMPTY, not absent ("this brand supports the contract and has none").
LEGACY_ALIASES: dict[str, str] = {}

# --- lifecycle vocabulary (values of the VACUUM entity's state) ----------------
#
# There is no ``task_status`` sensor upstream, so the vacuum entity itself is the
# lifecycle source (``entities.task_status`` points at it). Its state is HA's
# ``VacuumActivity``; ``paused`` and ``idle`` are neither active nor terminal.

#: A clean is IN PROGRESS — keeps the pose sampler's parked check and the job-active gate
#: honest. ``returning`` is included: a mid-job return-to-charge resumes, and the robot is
#: still part of the job until it docks.
ACTIVE_RUN_TASK_STATES: set[str] = {
    "cleaning",
    "returning",
}

#: ``sensor.<obj>_error`` carries the integration's error CODE as its state; ``0`` is
#: "no error" in the deebot protocol.
NOT_ERROR_SENTINELS: list[str] = ["0", "", "unknown", "unavailable", "none"]
