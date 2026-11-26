"""Scheduling + presence services — read / save / delete schedules, run one now, set presence.

The engine is ``scheduling/manager.py``; these handlers are thin and only translate a
refused write (``{"saved": False, "reason": ...}``) into a ``ServiceValidationError`` so a
YAML author or the card sees the refusal instead of a success-shaped response.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from ..const import (
    DATA_SCHEDULER,
    DOMAIN,
    SERVICE_DELETE_SCHEDULE,
    SERVICE_GET_SCHEDULES,
    SERVICE_RUN_SCHEDULE_NOW,
    SERVICE_SAVE_SCHEDULE,
    SERVICE_SET_PRESENCE_SETTINGS,
)

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    SERVICE_GET_SCHEDULES,
    SERVICE_SAVE_SCHEDULE,
    SERVICE_DELETE_SCHEDULE,
    SERVICE_RUN_SCHEDULE_NOW,
    SERVICE_SET_PRESENCE_SETTINGS,
)

_GET_SCHEDULES_SCHEMA = vol.Schema({vol.Required("vacuum_entity_id"): cv.entity_id})

_SAVE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("vacuum_entity_id"): cv.entity_id,
        # Absent = create; present = edit that schedule in place.
        vol.Optional("schedule_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("enabled"): cv.boolean,
        # Monday = 0 … Sunday = 6.
        vol.Required("days"): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))]),
        vol.Required("time"): cv.string,
        vol.Required("profile_id"): cv.string,
        vol.Optional("map_id"): cv.string,
        vol.Optional("when_home"): vol.In(["run", "skip", "defer"]),
    }
)

_SCHEDULE_ID_SCHEMA = vol.Schema(
    {
        vol.Required("vacuum_entity_id"): cv.entity_id,
        vol.Required("schedule_id"): cv.string,
    }
)

_PRESENCE_SCHEMA = vol.Schema(
    {
        vol.Required("vacuum_entity_id"): cv.entity_id,
        vol.Optional("persons"): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional("leave_enabled"): cv.boolean,
        vol.Optional("leave_profile_id"): cv.string,
        vol.Optional("leave_delay_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=240)),
        vol.Optional("leave_min_interval_hours"): vol.All(vol.Coerce(float), vol.Range(min=0, max=168)),
        vol.Optional("leave_window_start"): cv.string,
        vol.Optional("leave_window_end"): cv.string,
        vol.Optional("arrive_action"): vol.In(["none", "pause", "dock"]),
        # {room_id: [occupancy entity ids]} — a room with any source "on" is left out.
        vol.Optional("quiet_rules"): dict,
    }
)


def _scheduler(hass: HomeAssistant):
    scheduler = hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
    if scheduler is None:
        raise ServiceValidationError("The scheduler is not running.")
    return scheduler


def _refuse_if_failed(payload: dict, flag: str) -> dict:
    if not payload.get(flag):
        raise ServiceValidationError(
            f"Refused: {payload.get('reason', 'unknown')}"
        )
    return payload


def register(hass: HomeAssistant) -> None:
    """Register scheduling + presence services."""

    async def get_schedules(call: ServiceCall) -> dict:
        return _scheduler(hass).get_overview(call.data["vacuum_entity_id"])

    async def save_schedule(call: ServiceCall) -> dict:
        payload = await _scheduler(hass).async_save_schedule(
            call.data["vacuum_entity_id"], dict(call.data)
        )
        return _refuse_if_failed(payload, "saved")

    async def delete_schedule(call: ServiceCall) -> dict:
        payload = await _scheduler(hass).async_delete_schedule(
            call.data["vacuum_entity_id"], call.data["schedule_id"]
        )
        return _refuse_if_failed(payload, "deleted")

    async def run_schedule_now(call: ServiceCall) -> dict:
        # A refused start is a RESULT, not an exception: the caller (card or automation)
        # needs the reason ("someone_home", "active_job_running", …) to show or branch on.
        return await _scheduler(hass).async_run_now(
            call.data["vacuum_entity_id"], call.data["schedule_id"]
        )

    async def set_presence_settings(call: ServiceCall) -> dict:
        payload = await _scheduler(hass).async_set_presence(
            call.data["vacuum_entity_id"], dict(call.data)
        )
        return _refuse_if_failed(payload, "saved")

    hass.services.async_register(
        DOMAIN, SERVICE_GET_SCHEDULES, get_schedules,
        schema=_GET_SCHEDULES_SCHEMA, supports_response=True,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_SCHEDULE, save_schedule,
        schema=_SAVE_SCHEDULE_SCHEMA, supports_response=True,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_SCHEDULE, delete_schedule,
        schema=_SCHEDULE_ID_SCHEMA, supports_response=True,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RUN_SCHEDULE_NOW, run_schedule_now,
        schema=_SCHEDULE_ID_SCHEMA, supports_response=True,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PRESENCE_SETTINGS, set_presence_settings,
        schema=_PRESENCE_SCHEMA, supports_response=True,
    )
