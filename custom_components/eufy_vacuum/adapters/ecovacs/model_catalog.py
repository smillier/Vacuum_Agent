"""Ecovacs model catalog.

The HA core integration registers the device with ``model = deviceName`` (free text such as
``"DEEBOT OZMO 920 Series"``) and ``model_id = class`` (the Ecovacs product class id). Neither
is a catalogue key I could verify without a live device, so this catalog ships NO per-model
rows: every Deebot resolves to ``DEFAULT_PROFILE`` and **live entity presence is the gate**
(``select.<obj>_water_flow_level`` exists => water control; a station sensor exists =>
station). That is the honest position — an invented model table would claim hardware
knowledge nobody measured.

Add a row to ``MODEL_PROFILES`` keyed on ``device.model_id`` (preferred, stable) or the
``deviceName`` once a model has been verified on hardware.
"""

from __future__ import annotations

# model string -> capability profile. EMPTY on purpose, see the module docstring.
MODEL_PROFILES: dict[str, dict] = {}

# Unknown model -> conservative baseline. The mop/station flags are OPTIMISTIC because they
# degrade safely: a device without the entity simply has no matching control, and
# entity-presence detection in ``adapter.py`` is the real gate. Zone/goto/path fail CLOSED.
DEFAULT_PROFILE: dict = {
    "family": "generic",
    "display_name": "Ecovacs Deebot",
    "has_mop": True,
    "has_station": True,
    "station_collectable": True,
    "station_washable": True,
    "station_dryable": True,
}


def profile_for_model(model: str | None) -> dict:
    """Return the capability profile for a device-registry model string."""
    base = MODEL_PROFILES.get(model or "", DEFAULT_PROFILE)
    return {**DEFAULT_PROFILE, **base}
