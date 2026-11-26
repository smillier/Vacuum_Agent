"""Identity + tuning constants for the Ecovacs (Deebot) adapter.

Brand-level values only. ``ADAPTER_ID`` is BRAND-level (``"ecovacs"``) and immutable once
shipped (it is persisted in stored configs); per-model differences are gated from the
device registry + live entities, never by a per-model adapter id.
"""

from __future__ import annotations

# Framework domain is UNCHANGED — Ecovacs runs inside the same integration, storage and
# HA platforms as Eufy/Roborock/Dreame. const.py only varies identity strings.
DOMAIN = "eufy_vacuum"
NAME = "Vacuum Agent"

ADAPTER_ID = "ecovacs"

# The HA integration domain(s) that PROVIDE this brand's vacuum entity, matched against
# the ENTITY registry's ``platform`` (never blank, unlike device-registry free text).
# Ecovacs ships in HA core as ``ecovacs`` (manifest domain, deebot-client based).
UPSTREAM_PLATFORMS: tuple[str, ...] = ("ecovacs",)

# Deebot firmware auto-returns to charge at a low floor; the framework only uses this to
# classify a low-battery return vs a user/finish return. PROVISIONAL — not yet observed
# on hardware; 20 mirrors the other brands' default.
LOW_BATTERY_THRESHOLD_PERCENT = 20
