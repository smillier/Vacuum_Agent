"""Ecovacs maintenance component catalog.

The core integration publishes a LIFESPAN sensor per consumable (value = ``percent``
remaining, unit ``%``) and a RESET button per consumable
(``button.<obj>_reset_<component>_lifespan``; disabled in the entity registry by default,
so a user must enable it before the reset action resolves). The framework's maintenance
manager already handles a percent-unit source (``maintenance/manager.py`` reads the
``unit_of_measurement`` and derives ``remaining_percent`` from it), so each component below
only declares which sensor + button to bind.

Component ids are the framework's canonical ones (``main_brush`` / ``side_brush`` /
``filter``) so the cards, their translated headings and the shared upkeep guides line up.
``default_interval_hours`` / ``max_interval_hours`` are ADVISORY: the device, not a
framework interval, drives the real countdown (same as Roborock/Dreame).

Only the three robot consumables every Deebot carries are declared. Station parts
(``mop_washing_tray``, ``station_filter``, ``dust_bag``, ``strainer``, ...) exist upstream
but are model-dependent and are left out until a model that has them is verified.
"""

from __future__ import annotations

MAINTENANCE_COMPONENTS: dict[str, dict] = {
    "main_brush": {
        "sensor_suffix": "main_brush_lifespan",
        "reset_button": {
            "entity_suffixes": ["reset_main_brush_lifespan"],
            "token_sets": [["reset", "main", "brush", "lifespan"]],
        },
        "default_interval_hours": 300.0,
        "max_interval_hours": 450.0,
        "label": "Main Brush",
        "icon": "mdi:broom",
    },
    "side_brush": {
        "sensor_suffix": "side_brush_lifespan",
        "reset_button": {
            "entity_suffixes": ["reset_side_brush_lifespan"],
            "token_sets": [["reset", "side", "brush", "lifespan"]],
        },
        "default_interval_hours": 200.0,
        "max_interval_hours": 300.0,
        "label": "Side Brush",
        "icon": "mdi:broom",
    },
    "filter": {
        "sensor_suffix": "filter_lifespan",
        "reset_button": {
            "entity_suffixes": ["reset_filter_lifespan"],
            "token_sets": [["reset", "filter", "lifespan"]],
        },
        "default_interval_hours": 150.0,
        "max_interval_hours": 200.0,
        "label": "Filter",
        "icon": "mdi:air-filter",
    },
}
