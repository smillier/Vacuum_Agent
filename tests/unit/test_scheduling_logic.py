"""Scheduling + presence DECISIONS (``scheduling/logic.py``) — pure, no hass.

[SL-1]  a malformed schedule is refused with a reason, never repaired into a different one.
[SL-2]  ``is_due`` fires once per occurrence: right weekday, right minute, not yet stamped.
[SL-3]  ``next_run`` walks forward across days and skips disabled schedules.
[SL-4]  unavailable / unknown trackers count as PRESENT — an unattended robot must not
        start because a phone dropped off the network.
[SL-5]  ``in_window`` handles blank (always), normal and midnight-wrapping windows.
[SL-6]  the leave-run minimum interval gate.
[SL-7]  quiet rooms are those with any occupancy source reporting occupied.
[SL-8]  presence settings are validated: a leave run needs a profile and people.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.eufy_vacuum.scheduling import logic

# 2026-11-23 is a Monday.
MON_0730 = datetime(2026, 11, 23, 7, 30, tzinfo=timezone.utc)


def _sched(**over):
    base = {"days": [0, 2], "time": "07:30", "profile_id": "p1"}
    base.update(over)
    sched, err = logic.normalize_schedule(base)
    assert err is None, err
    return sched


@pytest.mark.parametrize(
    "raw, reason",
    [
        ({"days": [0], "time": "7:30", "profile_id": "p"}, "invalid_time"),
        ({"days": [0], "time": "25:00", "profile_id": "p"}, "invalid_time"),
        ({"days": [], "time": "07:30", "profile_id": "p"}, "invalid_days"),
        ({"days": [7], "time": "07:30", "profile_id": "p"}, "invalid_days"),
        ({"days": ["x"], "time": "07:30", "profile_id": "p"}, "invalid_days"),
        ({"days": [0], "time": "07:30", "profile_id": " "}, "profile_required"),
        ({"days": [0], "time": "07:30", "profile_id": "p", "when_home": "maybe"}, "invalid_when_home"),
    ],
)
def test_malformed_schedule_is_refused(raw, reason):
    """[SL-1]"""
    sched, err = logic.normalize_schedule(raw)
    assert sched is None and err == reason


def test_schedule_is_normalised():
    """[SL-1]"""
    s = _sched(days=[2, 0, 2], name="  ", when_home="defer")
    assert s["days"] == [0, 2]
    assert s["name"] == "Clean at 07:30"
    assert s["when_home"] == "defer" and s["enabled"] is True


def test_is_due_only_on_its_day_and_minute_and_once():
    """[SL-2]"""
    s = _sched()
    assert logic.is_due(s, MON_0730)
    assert not logic.is_due(s, MON_0730.replace(minute=31))
    assert not logic.is_due(s, MON_0730.replace(day=24))  # Tuesday
    s["last_fired"] = logic.occurrence_key(s, MON_0730)
    assert not logic.is_due(s, MON_0730)
    assert logic.is_due(s, MON_0730.replace(day=25))  # Wednesday, new occurrence
    assert not logic.is_due({**s, "enabled": False, "last_fired": None}, MON_0730)


def test_next_run_walks_days_and_skips_disabled():
    """[SL-3]"""
    s = _sched()
    # Right at the minute -> the NEXT occurrence is Wednesday.
    assert logic.next_run(s, MON_0730) == datetime(2026, 11, 25, 7, 30, tzinfo=timezone.utc)
    # Earlier the same day -> today.
    assert logic.next_run(s, MON_0730.replace(hour=6)) == MON_0730
    assert logic.next_run({**s, "enabled": False}, MON_0730) is None


def test_unknown_trackers_count_as_present():
    """[SL-4]"""
    assert logic.anyone_home(["not_home", "unavailable"])
    assert logic.anyone_home([None])
    assert not logic.anyone_home(["not_home", "work"])
    assert logic.everyone_away(["not_home", "work"])
    assert not logic.everyone_away(["not_home", "unknown"])
    assert not logic.everyone_away([])  # no trackers is no signal, not "away"


def test_in_window():
    """[SL-5]"""
    t = lambda h, m=0: MON_0730.replace(hour=h, minute=m)  # noqa: E731
    assert logic.in_window(t(3), "", "")
    assert logic.in_window(t(7), "08:00", "18:00") is False
    assert logic.in_window(t(10), "08:00", "18:00") is True
    assert logic.in_window(t(18), "08:00", "18:00") is False  # end exclusive
    assert logic.in_window(t(23), "22:00", "06:00") is True
    assert logic.in_window(t(5), "22:00", "06:00") is True
    assert logic.in_window(t(12), "22:00", "06:00") is False


def test_leave_interval():
    """[SL-6]"""
    assert logic.leave_interval_elapsed(None, 1000.0, 12)
    assert logic.leave_interval_elapsed(0.0, 1000.0, 12)
    assert not logic.leave_interval_elapsed(1000.0, 1000.0 + 3600, 12)
    assert logic.leave_interval_elapsed(1000.0, 1000.0 + 12 * 3600, 12)
    assert logic.leave_interval_elapsed(1000.0, 1001.0, 0)


def test_occupied_rooms():
    """[SL-7]"""
    states = {"binary_sensor.a": "off", "binary_sensor.b": "on", "binary_sensor.c": "unavailable"}
    rules = {
        "1": ["binary_sensor.a", "binary_sensor.b"],
        "2": ["binary_sensor.a"],
        "3": ["binary_sensor.c"],
        "4": ["binary_sensor.missing"],
    }
    assert logic.occupied_rooms(rules, states.get) == {"1"}
    assert logic.occupied_rooms(None, states.get) == set()


def test_presence_validation():
    """[SL-8]"""
    ok, err = logic.normalize_presence(
        {
            "persons": ["Person.Me", "device_tracker.phone", "person.me"],
            "leave_enabled": True,
            "leave_profile_id": "p1",
            "quiet_rules": {"3": ["binary_sensor.bed", "nonsense"]},
        }
    )
    assert err is None
    assert ok["persons"] == ["person.me", "device_tracker.phone"]
    assert ok["quiet_rules"] == {"3": ["binary_sensor.bed"]}
    assert ok["arrive_action"] == "none" and ok["leave_delay_minutes"] == 10

    bad = lambda **kw: logic.normalize_presence(kw)[1]  # noqa: E731
    assert bad(persons=["light.kitchen"]) == "invalid_persons"
    assert bad(leave_enabled=True, persons=["person.me"]) == "profile_required"
    assert bad(leave_enabled=True, leave_profile_id="p") == "persons_required"
    assert bad(leave_window_start="08:00") == "invalid_window"
    assert bad(leave_window_start="8", leave_window_end="9") == "invalid_time"
    assert bad(arrive_action="explode") == "invalid_arrive_action"
    assert bad(leave_delay_minutes=999) == "invalid_number"
    assert bad(quiet_rules=["x"]) == "invalid_quiet_rules"
