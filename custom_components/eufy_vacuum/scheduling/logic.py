"""Pure scheduling + presence rules — no Home Assistant imports, no I/O.

Everything here takes plain values and returns plain values so it can be reasoned about
(and tested) without a running hass. ``scheduling/manager.py`` owns the timers, the state
listeners and the actual start/pause/dock calls; this module owns every DECISION.

Vocabulary
----------
* ``days``       list of ints, Monday = 0 … Sunday = 6 (``datetime.weekday()``).
* ``time``       ``"HH:MM"`` local time, 24 h.
* ``when_home``  what a schedule does if someone is home at its time:
                 ``run`` (ignore presence), ``skip`` (drop this occurrence),
                 ``defer`` (hold it until everyone has left, same day only).
* presence       judged from ``person.*`` / ``device_tracker.*`` states. ``home`` is
                 PRESENT; ``unavailable`` / ``unknown`` are treated as PRESENT too — an
                 unattended robot must never start because a phone lost its signal.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable, Iterable

WHEN_HOME_VALUES = ("run", "skip", "defer")
ARRIVE_ACTIONS = ("none", "pause", "dock")

#: States that mean "this person is not home and we know it".
HOME_STATE = "home"
UNKNOWN_STATES = frozenset({"unavailable", "unknown", ""})

#: States of a room-occupancy source that mean "someone is in there".
OCCUPIED_STATES = frozenset({"on", "home", "occupied", "detected", "true", "present"})

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

MAX_DELAY_MINUTES = 240
MAX_INTERVAL_HOURS = 168


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def parse_hhmm(value: Any) -> dtime | None:
    """``"07:30"`` -> ``time(7, 30)``; anything else -> None."""
    match = _TIME_RE.match(_clean_str(value))
    if not match:
        return None
    return dtime(int(match.group(1)), int(match.group(2)))


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def normalize_schedule(raw: dict[str, Any], *, schedule_id: str | None = None) -> tuple[dict | None, str | None]:
    """Validate + coerce a schedule. Returns ``(schedule, None)`` or ``(None, error)``.

    The error is a short machine key (``invalid_time`` …) the service layer turns into a
    user-facing refusal; a malformed schedule is REFUSED, never repaired into something
    that would run at a time nobody asked for.
    """
    raw = raw or {}

    parsed = parse_hhmm(raw.get("time"))
    if parsed is None:
        return None, "invalid_time"

    days_in = raw.get("days")
    if not isinstance(days_in, (list, tuple)) or not days_in:
        return None, "invalid_days"
    days: list[int] = []
    for day in days_in:
        try:
            value = int(day)
        except (TypeError, ValueError):
            return None, "invalid_days"
        if not 0 <= value <= 6:
            return None, "invalid_days"
        if value not in days:
            days.append(value)
    days.sort()

    profile_id = _clean_str(raw.get("profile_id"))
    if not profile_id:
        return None, "profile_required"

    when_home = _clean_str(raw.get("when_home")) or "run"
    if when_home not in WHEN_HOME_VALUES:
        return None, "invalid_when_home"

    name = _clean_str(raw.get("name")) or f"Clean at {parsed.strftime('%H:%M')}"

    return (
        {
            "id": schedule_id or _clean_str(raw.get("id")) or uuid.uuid4().hex[:10],
            "name": name[:60],
            "enabled": bool(raw.get("enabled", True)),
            "days": days,
            "time": parsed.strftime("%H:%M"),
            "profile_id": profile_id,
            "map_id": _clean_str(raw.get("map_id")),
            "when_home": when_home,
        },
        None,
    )


def occurrence_key(schedule: dict[str, Any], now: datetime) -> str:
    """Identity of one firing of a schedule — ``"<date>T<HH:MM>"``.

    Stored as ``last_fired`` so a minute tick that lands twice (clock jump, listener
    re-armed on reload) cannot start the same occurrence twice.
    """
    return f"{now.date().isoformat()}T{schedule.get('time', '')}"


def is_due(schedule: dict[str, Any], now: datetime) -> bool:
    """True when ``now`` is inside this schedule's minute and it has not fired for it yet."""
    if not schedule.get("enabled", True):
        return False
    if now.weekday() not in (schedule.get("days") or []):
        return False
    if now.strftime("%H:%M") != schedule.get("time"):
        return False
    return schedule.get("last_fired") != occurrence_key(schedule, now)


def next_run(schedule: dict[str, Any], now: datetime) -> datetime | None:
    """The next wall-clock moment this schedule fires after ``now`` (None if disabled)."""
    if not schedule.get("enabled", True):
        return None
    at = parse_hhmm(schedule.get("time"))
    days = schedule.get("days") or []
    if at is None or not days:
        return None
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() not in days:
            continue
        candidate = datetime.combine(day, at, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


def is_present(state: str | None) -> bool:
    """One person/tracker: PRESENT unless we positively know they are elsewhere."""
    value = _clean_str(state).lower()
    return value == HOME_STATE or value in UNKNOWN_STATES


def anyone_home(states: Iterable[str | None]) -> bool:
    """True if any tracked person may be home. No trackers at all -> False (no signal)."""
    return any(is_present(s) for s in states)


def everyone_away(states: Iterable[str | None]) -> bool:
    """True only when there IS at least one tracker and every one is positively away."""
    states = list(states)
    return bool(states) and not anyone_home(states)


def in_window(now: datetime, start: Any, end: Any) -> bool:
    """Is ``now`` inside ``[start, end)``? Blank on either side = always.

    A window whose end is before its start wraps midnight (``22:00``–``06:00``).
    """
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s is None or e is None:
        return True
    current = now.time().replace(second=0, microsecond=0)
    if s == e:
        return True
    if s < e:
        return s <= current < e
    return current >= s or current < e


def leave_interval_elapsed(last_ts: float | None, now_ts: float, min_hours: float) -> bool:
    """Has the minimum gap since the last presence-triggered run passed?"""
    if not last_ts or min_hours <= 0:
        return True
    return (now_ts - float(last_ts)) >= min_hours * 3600.0


def occupied_rooms(
    rules: dict[str, list[str]] | None,
    get_state: Callable[[str], str | None],
) -> set[str]:
    """Room ids (as strings) with at least one occupancy source reporting occupied."""
    occupied: set[str] = set()
    for room_id, entity_ids in (rules or {}).items():
        for entity_id in entity_ids or []:
            if _clean_str(get_state(entity_id)).lower() in OCCUPIED_STATES:
                occupied.add(str(room_id))
                break
    return occupied


def normalize_presence(raw: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Validate + coerce one vacuum's presence settings."""
    raw = raw or {}

    persons_in = raw.get("persons") or []
    if not isinstance(persons_in, (list, tuple)):
        return None, "invalid_persons"
    persons: list[str] = []
    for entity_id in persons_in:
        value = _clean_str(entity_id).lower()
        if value.split(".", 1)[0] not in ("person", "device_tracker"):
            return None, "invalid_persons"
        if value not in persons:
            persons.append(value)

    try:
        delay = int(raw.get("leave_delay_minutes", 10))
        interval = float(raw.get("leave_min_interval_hours", 12))
    except (TypeError, ValueError):
        return None, "invalid_number"
    if not 0 <= delay <= MAX_DELAY_MINUTES or not 0 <= interval <= MAX_INTERVAL_HOURS:
        return None, "invalid_number"

    window_start = _clean_str(raw.get("leave_window_start"))
    window_end = _clean_str(raw.get("leave_window_end"))
    for value in (window_start, window_end):
        if value and parse_hhmm(value) is None:
            return None, "invalid_time"
    if bool(window_start) != bool(window_end):
        return None, "invalid_window"

    arrive = _clean_str(raw.get("arrive_action")) or "none"
    if arrive not in ARRIVE_ACTIONS:
        return None, "invalid_arrive_action"

    quiet_in = raw.get("quiet_rules") or {}
    if not isinstance(quiet_in, dict):
        return None, "invalid_quiet_rules"
    quiet: dict[str, list[str]] = {}
    for room_id, entity_ids in quiet_in.items():
        if not isinstance(entity_ids, (list, tuple)):
            return None, "invalid_quiet_rules"
        cleaned = [e for e in (_clean_str(x).lower() for x in entity_ids) if "." in e]
        if cleaned:
            quiet[str(room_id)] = list(dict.fromkeys(cleaned))

    leave_enabled = bool(raw.get("leave_enabled", False))
    leave_profile = _clean_str(raw.get("leave_profile_id"))
    if leave_enabled and not leave_profile:
        return None, "profile_required"
    if leave_enabled and not persons:
        return None, "persons_required"

    return (
        {
            "persons": persons,
            "leave_enabled": leave_enabled,
            "leave_profile_id": leave_profile,
            "leave_delay_minutes": delay,
            "leave_min_interval_hours": interval,
            "leave_window_start": window_start,
            "leave_window_end": window_end,
            "arrive_action": arrive,
            "quiet_rules": quiet,
        },
        None,
    )
