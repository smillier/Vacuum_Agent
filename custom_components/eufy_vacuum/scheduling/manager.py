"""Scheduling + presence engine.

Owns the TIMERS and LISTENERS; every decision (is it due, is anyone home, is the room
occupied) lives in ``scheduling/logic.py``. A scheduled or presence-triggered run is
started through exactly the same protected path as a button press
(``manager.start_run_profile`` / ``start_selected_rooms``), so room rules, blockers,
access graph, battery and in-flight guards all still apply — this module only decides
WHEN, and which rooms to leave out.

Storage: ``manager.data["scheduling"][<vacuum_entity_id>]`` ::

    {
      "schedules": {<id>: {id, name, enabled, days, time, profile_id, map_id,
                           when_home, last_fired, last_result}},
      "presence":  {persons, leave_enabled, leave_profile_id, leave_delay_minutes,
                    leave_min_interval_hours, leave_window_start, leave_window_end,
                    arrive_action, quiet_rules},
      "state":     {"deferred": {<schedule_id>: "<YYYY-MM-DD>"}, "last_leave_run": <ts>}
    }

Behaviour worth knowing:

* **Unattended safety.** Presence trackers reporting ``unavailable`` / ``unknown`` count as
  PRESENT. A reduced run (blocked rooms) is NOT auto-confirmed: it is reported as skipped
  with its reason, because nobody is there to approve it.
* **Defer** holds an occurrence until everyone leaves, but only until midnight of the day
  it was due — a 07:30 clean never runs at 23:50 because someone finally went out.
* **Quiet rooms** are left out of a run while their occupancy source is on. A run that
  needed that filter is dispatched as a flat room clean; a profile's multi-step plan
  (charge stops, zone steps) is only preserved when no room had to be dropped.
* Nothing here survives a Home Assistant restart except the stored configuration: the
  leave-delay timer and any in-progress occurrence are in memory by design.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from ..const import EVENT_SCHEDULE_ACTION
from . import logic

_LOGGER = logging.getLogger(__name__)

SOURCE_SCHEDULE = "schedule"
SOURCE_DEFERRED = "presence_deferred"
SOURCE_LEAVE = "presence_leave"
SOURCE_MANUAL = "manual"


class ScheduleManager:
    """Fires schedules on the clock and reacts to people leaving / arriving."""

    def __init__(self, hass: HomeAssistant, *, runtime_manager) -> None:
        self._hass = hass
        self._manager = runtime_manager
        self._unsub_clock = None
        # vacuum_entity_id -> unsubscribe for that vacuum's person listener
        self._unsub_presence: dict[str, Any] = {}
        # vacuum_entity_id -> cancel for the pending leave-delay timer
        self._leave_timers: dict[str, Any] = {}
        # vacuum_entity_id -> last observed "everyone away" verdict
        self._was_away: dict[str, bool] = {}

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Arm the minute clock and every vacuum's presence listener."""
        if self._unsub_clock is None:
            self._unsub_clock = async_track_time_change(
                self._hass, self._on_minute, second=0
            )
        self.refresh_listeners()

    def stop(self) -> None:
        if self._unsub_clock is not None:
            self._unsub_clock()
            self._unsub_clock = None
        for unsub in list(self._unsub_presence.values()):
            unsub()
        self._unsub_presence.clear()
        for cancel in list(self._leave_timers.values()):
            cancel()
        self._leave_timers.clear()
        self._was_away.clear()

    def refresh_listeners(self, vacuum_entity_id: str | None = None) -> None:
        """(Re)subscribe the person trackers named in the stored presence settings."""
        targets = (
            [vacuum_entity_id]
            if vacuum_entity_id
            else list(self._manager.get_known_vacuum_ids())
        )
        for vid in targets:
            unsub = self._unsub_presence.pop(vid, None)
            if unsub is not None:
                unsub()
            self._cancel_leave_timer(vid)
            persons = list(self._cfg(vid)["presence"].get("persons") or [])
            if not persons:
                self._was_away.pop(vid, None)
                continue
            self._was_away[vid] = logic.everyone_away(self._person_states(vid))

            @callback
            def _on_person(event: Event, _vid: str = vid) -> None:
                self._on_person_change(_vid, event)

            self._unsub_presence[vid] = async_track_state_change_event(
                self._hass, persons, _on_person
            )

    # ------------------------------------------------------------------ storage

    def _cfg(self, vacuum_entity_id: str) -> dict[str, Any]:
        root = self._manager.data.setdefault("scheduling", {})
        cfg = root.setdefault(vacuum_entity_id, {})
        cfg.setdefault("schedules", {})
        cfg.setdefault("presence", {})
        cfg.setdefault("state", {})
        cfg["state"].setdefault("deferred", {})
        return cfg

    async def _save(self) -> None:
        await self._manager.async_save()

    # ------------------------------------------------------------------ public API

    def get_overview(self, vacuum_entity_id: str) -> dict[str, Any]:
        """Everything the card needs: schedules (with next run), presence, live states."""
        cfg = self._cfg(vacuum_entity_id)
        now = dt_util.now()
        schedules = []
        for sched in sorted(
            cfg["schedules"].values(), key=lambda s: (s.get("time", ""), s.get("name", ""))
        ):
            upcoming = logic.next_run(sched, now)
            schedules.append(
                {
                    **sched,
                    "next_run": upcoming.isoformat() if upcoming else None,
                    "deferred": cfg["state"]["deferred"].get(sched["id"])
                    == now.date().isoformat(),
                }
            )
        persons = list(cfg["presence"].get("persons") or [])
        states = self._person_states(vacuum_entity_id)
        return {
            "vacuum_entity_id": vacuum_entity_id,
            "schedules": schedules,
            "presence": dict(cfg["presence"]),
            "presence_state": {
                "persons": {p: s for p, s in zip(persons, states)},
                "everyone_away": logic.everyone_away(states),
                "anyone_home": logic.anyone_home(states) if persons else None,
                "occupied_rooms": sorted(self._occupied(vacuum_entity_id)),
                "leave_pending": vacuum_entity_id in self._leave_timers,
            },
        }

    async def async_save_schedule(
        self, vacuum_entity_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        cfg = self._cfg(vacuum_entity_id)
        existing = cfg["schedules"].get(str(raw.get("schedule_id") or ""))
        schedule, error = logic.normalize_schedule(
            raw, schedule_id=existing["id"] if existing else None
        )
        if schedule is None:
            return {"saved": False, "reason": error}
        if existing:
            # Editing the time must re-arm today's occurrence; editing anything else must not.
            if existing.get("time") == schedule["time"]:
                schedule["last_fired"] = existing.get("last_fired")
            if existing.get("last_result"):
                schedule["last_result"] = existing["last_result"]
        cfg["schedules"][schedule["id"]] = schedule
        cfg["state"]["deferred"].pop(schedule["id"], None)
        await self._save()
        return {"saved": True, "schedule": schedule}

    async def async_delete_schedule(
        self, vacuum_entity_id: str, schedule_id: str
    ) -> dict[str, Any]:
        cfg = self._cfg(vacuum_entity_id)
        removed = cfg["schedules"].pop(str(schedule_id), None)
        cfg["state"]["deferred"].pop(str(schedule_id), None)
        if removed is None:
            return {"deleted": False, "reason": "schedule_not_found"}
        await self._save()
        return {"deleted": True, "schedule_id": str(schedule_id)}

    async def async_set_presence(
        self, vacuum_entity_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        presence, error = logic.normalize_presence(raw)
        if presence is None:
            return {"saved": False, "reason": error}
        cfg = self._cfg(vacuum_entity_id)
        cfg["presence"] = presence
        await self._save()
        self.refresh_listeners(vacuum_entity_id)
        return {"saved": True, "presence": presence}

    async def async_run_now(
        self, vacuum_entity_id: str, schedule_id: str
    ) -> dict[str, Any]:
        """Run one schedule immediately, ignoring its time and its presence policy."""
        sched = self._cfg(vacuum_entity_id)["schedules"].get(str(schedule_id))
        if sched is None:
            return {"started": False, "reason": "schedule_not_found"}
        return await self._start_for(vacuum_entity_id, sched, source=SOURCE_MANUAL)

    # ------------------------------------------------------------------ presence reads

    def _person_states(self, vacuum_entity_id: str) -> list[str | None]:
        persons = self._cfg(vacuum_entity_id)["presence"].get("persons") or []
        out: list[str | None] = []
        for entity_id in persons:
            state = self._hass.states.get(entity_id)
            out.append(state.state if state is not None else None)
        return out

    def _occupied(self, vacuum_entity_id: str) -> set[str]:
        rules = self._cfg(vacuum_entity_id)["presence"].get("quiet_rules") or {}

        def _state(entity_id: str) -> str | None:
            state = self._hass.states.get(entity_id)
            return state.state if state is not None else None

        return logic.occupied_rooms(rules, _state)

    # ------------------------------------------------------------------ clock

    @callback
    def _on_minute(self, now: datetime) -> None:
        local = dt_util.as_local(now)
        for vid in list(self._manager.get_known_vacuum_ids()):
            cfg = self._cfg(vid)
            for sched in list(cfg["schedules"].values()):
                if logic.is_due(sched, local):
                    # Stamp BEFORE the task runs so a second tick in the same minute
                    # (clock correction, listener re-armed) cannot double-fire.
                    sched["last_fired"] = logic.occurrence_key(sched, local)
                    self._hass.async_create_task(self._fire_schedule(vid, sched["id"]))

    async def _fire_schedule(self, vacuum_entity_id: str, schedule_id: str) -> None:
        cfg = self._cfg(vacuum_entity_id)
        sched = cfg["schedules"].get(schedule_id)
        if sched is None:
            return
        persons = cfg["presence"].get("persons") or []
        policy = sched.get("when_home", "run")
        if persons and policy != "run" and logic.anyone_home(self._person_states(vacuum_entity_id)):
            if policy == "defer":
                cfg["state"]["deferred"][schedule_id] = dt_util.now().date().isoformat()
                await self._record(
                    vacuum_entity_id, sched, SOURCE_SCHEDULE, "deferred", "someone_home"
                )
            else:
                await self._record(
                    vacuum_entity_id, sched, SOURCE_SCHEDULE, "skipped", "someone_home"
                )
            await self._save()
            return
        await self._start_for(vacuum_entity_id, sched, source=SOURCE_SCHEDULE)

    # ------------------------------------------------------------------ presence events

    @callback
    def _on_person_change(self, vacuum_entity_id: str, event: Event) -> None:
        states = self._person_states(vacuum_entity_id)
        away_now = logic.everyone_away(states)
        away_before = self._was_away.get(vacuum_entity_id, False)
        self._was_away[vacuum_entity_id] = away_now

        new = event.data.get("new_state")
        old = event.data.get("old_state")
        arrived = (
            new is not None
            and new.state == logic.HOME_STATE
            and (old is None or old.state != logic.HOME_STATE)
        )
        if arrived:
            self._cancel_leave_timer(vacuum_entity_id)
            self._hass.async_create_task(self._on_arrival(vacuum_entity_id))
            return

        if away_now and not away_before:
            presence = self._cfg(vacuum_entity_id)["presence"]
            delay = int(presence.get("leave_delay_minutes", 10))
            self._cancel_leave_timer(vacuum_entity_id)

            @callback
            def _fire(_now: datetime, _vid: str = vacuum_entity_id) -> None:
                self._leave_timers.pop(_vid, None)
                self._hass.async_create_task(self._on_everyone_left(_vid))

            self._leave_timers[vacuum_entity_id] = async_call_later(
                self._hass, max(delay, 0) * 60, _fire
            )

    def _cancel_leave_timer(self, vacuum_entity_id: str) -> None:
        cancel = self._leave_timers.pop(vacuum_entity_id, None)
        if cancel is not None:
            cancel()

    async def _on_arrival(self, vacuum_entity_id: str) -> None:
        """Someone came home: pause or dock a run the robot is making right now."""
        action = self._cfg(vacuum_entity_id)["presence"].get("arrive_action", "none")
        if action == "none":
            return
        map_id = self._resolve_map(vacuum_entity_id, "")
        if not map_id:
            return
        job = self._manager.get_active_job(
            vacuum_entity_id=vacuum_entity_id, map_id=map_id
        )
        status = str(job.get("status") or "")
        try:
            if action == "pause" and status == "started":
                await self._manager.async_pause_active_job(
                    vacuum_entity_id=vacuum_entity_id, map_id=map_id
                )
                self._fire_event(vacuum_entity_id, SOURCE_LEAVE, "paused", "arrival", map_id=map_id)
            elif action == "dock" and status in ("started", "paused"):
                await self._manager.async_cancel_active_job(
                    vacuum_entity_id=vacuum_entity_id,
                    map_id=map_id,
                    cancel_reason="presence_arrival",
                )
                self._fire_event(vacuum_entity_id, SOURCE_LEAVE, "docked", "arrival", map_id=map_id)
            else:
                return
            await self._save()
        except Exception:  # pragma: no cover - never let a listener task raise
            _LOGGER.exception(
                "scheduler: arrival action %r failed for %s", action, vacuum_entity_id
            )

    async def _on_everyone_left(self, vacuum_entity_id: str) -> None:
        """The leave delay elapsed: run anything deferred today, then the leave profile."""
        cfg = self._cfg(vacuum_entity_id)
        # Re-check: the delay exists so a phone dropping off Wi-Fi does not start a run.
        if not logic.everyone_away(self._person_states(vacuum_entity_id)):
            return

        today = dt_util.now().date().isoformat()
        for schedule_id, day in list(cfg["state"]["deferred"].items()):
            cfg["state"]["deferred"].pop(schedule_id, None)
            sched = cfg["schedules"].get(schedule_id)
            if sched is None or day != today:
                continue
            result = await self._start_for(vacuum_entity_id, sched, source=SOURCE_DEFERRED)
            if result.get("started"):
                await self._save()
                return  # one run per departure; the robot is now busy

        presence = cfg["presence"]
        if not presence.get("leave_enabled") or not presence.get("leave_profile_id"):
            await self._save()
            return
        now = dt_util.now()
        if not logic.in_window(
            now, presence.get("leave_window_start"), presence.get("leave_window_end")
        ):
            self._fire_event(
                vacuum_entity_id, SOURCE_LEAVE, "skipped", "outside_window",
                profile_id=presence["leave_profile_id"],
            )
            return
        if not logic.leave_interval_elapsed(
            cfg["state"].get("last_leave_run"),
            _time.time(),
            float(presence.get("leave_min_interval_hours", 12)),
        ):
            self._fire_event(
                vacuum_entity_id, SOURCE_LEAVE, "skipped", "too_soon",
                profile_id=presence["leave_profile_id"],
            )
            return
        result = await self._run_profile(
            vacuum_entity_id, presence["leave_profile_id"], "", source=SOURCE_LEAVE
        )
        if result.get("started"):
            cfg["state"]["last_leave_run"] = _time.time()
        await self._save()

    # ------------------------------------------------------------------ starting runs

    def _resolve_map(self, vacuum_entity_id: str, map_id: str) -> str:
        if map_id:
            return str(map_id)
        from ..rooms.room_discovery import get_active_map_id

        return str(get_active_map_id(self._hass, vacuum_entity_id) or "")

    async def _start_for(
        self, vacuum_entity_id: str, sched: dict[str, Any], *, source: str
    ) -> dict[str, Any]:
        result = await self._run_profile(
            vacuum_entity_id,
            sched["profile_id"],
            sched.get("map_id", ""),
            source=source,
            schedule_id=sched["id"],
        )
        sched["last_result"] = {
            "at": dt_util.now().isoformat(),
            "source": source,
            "started": bool(result.get("started")),
            "reason": result.get("reason", ""),
        }
        await self._save()
        return result

    async def _run_profile(
        self,
        vacuum_entity_id: str,
        profile_id: str,
        map_id: str,
        *,
        source: str,
        schedule_id: str | None = None,
    ) -> dict[str, Any]:
        """Start one saved profile, minus any room whose quiet rule says it is occupied."""
        extra = {"profile_id": profile_id, "schedule_id": schedule_id}
        resolved_map = self._resolve_map(vacuum_entity_id, map_id)
        if not resolved_map:
            return self._skipped(vacuum_entity_id, source, "no_map", resolved_map, extra)

        inflight = self._manager.get_job_inflight_state(
            vacuum_entity_id=vacuum_entity_id, map_id=resolved_map
        )
        if inflight.get("in_flight"):
            return self._skipped(
                vacuum_entity_id, source, str(inflight.get("reason") or "busy"), resolved_map, extra
            )

        try:
            occupied = self._occupied(vacuum_entity_id)
            if occupied:
                result = await self._start_without_rooms(
                    vacuum_entity_id, resolved_map, profile_id, occupied
                )
            else:
                result = await self._manager.start_run_profile(
                    vacuum_entity_id=vacuum_entity_id,
                    map_id=resolved_map,
                    profile_id=profile_id,
                )
        except Exception as err:  # noqa: BLE001 - an unattended start must report, not raise
            _LOGGER.exception(
                "scheduler: scheduled start failed for %s (%s)", vacuum_entity_id, profile_id
            )
            return self._skipped(vacuum_entity_id, source, f"error: {err}", resolved_map, extra)

        started = bool(result.get("started"))
        reason = str(result.get("reason") or ("" if started else "not_started"))
        if started:
            await self._manager.async_save()
        self._fire_event(
            vacuum_entity_id, source, "started" if started else "skipped", reason,
            map_id=resolved_map, **extra,
        )
        return {"started": started, "reason": reason, "result": result}

    async def _start_without_rooms(
        self,
        vacuum_entity_id: str,
        map_id: str,
        profile_id: str,
        occupied: set[str],
    ) -> dict[str, Any]:
        """Apply the profile, drop occupied rooms, dispatch the rest as a flat clean."""
        applied = self._manager.apply_run_profile(
            vacuum_entity_id=vacuum_entity_id, map_id=map_id, profile_id=profile_id
        )
        if not applied.get("applied"):
            return {"started": False, "reason": applied.get("reason", "profile_not_found")}
        wanted = [str(r) for r in applied.get("applied_room_ids", [])]
        remaining = [r for r in wanted if r not in occupied]
        if not remaining:
            return {"started": False, "reason": "all_rooms_occupied"}
        if len(remaining) == len(wanted):
            # Nothing had to be dropped: take the normal path, which keeps multi-step plans.
            return await self._manager.start_run_profile(
                vacuum_entity_id=vacuum_entity_id, map_id=map_id, profile_id=profile_id
            )
        self._manager.set_rooms_enabled_subset(
            vacuum_entity_id=vacuum_entity_id, map_id=map_id, room_ids=remaining
        )
        self._manager.build_queue(vacuum_entity_id=vacuum_entity_id, map_id=map_id)
        self._manager.build_room_payload(vacuum_entity_id=vacuum_entity_id, map_id=map_id)
        result = await self._manager.start_selected_rooms(
            vacuum_entity_id=vacuum_entity_id, map_id=map_id
        )
        result = dict(result)
        result["skipped_occupied_rooms"] = sorted(set(wanted) - set(remaining))
        return result

    # ------------------------------------------------------------------ events / records

    def _skipped(
        self,
        vacuum_entity_id: str,
        source: str,
        reason: str,
        map_id: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        self._fire_event(vacuum_entity_id, source, "skipped", reason, map_id=map_id, **extra)
        return {"started": False, "reason": reason}

    async def _record(
        self,
        vacuum_entity_id: str,
        sched: dict[str, Any],
        source: str,
        action: str,
        reason: str,
    ) -> None:
        sched["last_result"] = {
            "at": dt_util.now().isoformat(),
            "source": source,
            "started": False,
            "reason": reason,
        }
        self._fire_event(
            vacuum_entity_id, source, action, reason,
            schedule_id=sched["id"], profile_id=sched["profile_id"],
            map_id=sched.get("map_id", ""),
        )

    def _fire_event(
        self,
        vacuum_entity_id: str,
        source: str,
        action: str,
        reason: str,
        *,
        schedule_id: str | None = None,
        profile_id: str | None = None,
        map_id: str = "",
    ) -> None:
        self._hass.bus.async_fire(
            EVENT_SCHEDULE_ACTION,
            {
                "vacuum_entity_id": vacuum_entity_id,
                "source": source,
                "action": action,
                "reason": reason,
                "schedule_id": schedule_id,
                "profile_id": profile_id,
                "map_id": map_id,
            },
        )
