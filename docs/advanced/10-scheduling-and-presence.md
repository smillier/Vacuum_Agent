# Scheduling and presence

Vacuum Agent can start cleans on a clock and react to who is home. Both live in the
**Rooms** view sidebar (the **Schedules** and **Presence** panels) and are also plain
services, so you can drive them from automations.

A scheduled or presence-triggered clean is started through **exactly the same protected
path as pressing Start** — room rules, blockers, the access graph, battery checks and the
"already running" guard all still apply. The scheduler only decides *when*, and which rooms
to leave out.

## Schedules

A schedule starts one **saved run profile** at a time of day on chosen weekdays
(Monday = 0 … Sunday = 6). Save a run profile first (Rooms view → *Run Profiles*), then add
a schedule for it.

Each schedule has a **When someone is home** policy:

| Policy | At the start time, if anyone is home |
|---|---|
| `run` | starts anyway |
| `skip` | that day's clean is dropped |
| `defer` | the clean waits and starts after everyone has left — **the same day only**, never the next |

`skip` and `defer` need people chosen under **Presence**; with none chosen they behave like `run`.

A reduced run (some rooms blocked) is **not** auto-confirmed — nobody is there to approve
it. It is reported as not started, with the reason, on the schedule row and in the event.

## Presence

Choose the `person.*` / `device_tracker.*` entities to watch. A tracker that is
`unavailable` or `unknown` counts as **home**, so a phone dropping off the network can never
start the robot.

- **Clean when everyone leaves** — once every watched person is away for the *leave delay*,
  start the chosen run profile. Optional *minimum hours between leave cleans* and an optional
  *time window* (which may cross midnight). Deferred schedules for the day run first.
- **When someone arrives** — `none`, `pause`, or `dock` a clean that is in progress.
- **Quiet rooms** — per room, one or more occupancy entities (for example a
  `binary_sensor` with device class occupancy). While any of them is `on`, that room is left
  out of a scheduled or presence-triggered clean. If every room is occupied, nothing starts.

> A run that had to drop an occupied room is sent as a flat room clean. A profile's
> multi-step plan (charge stops, zone steps) is preserved only when no room had to be dropped.

Nothing but the stored configuration survives a Home Assistant restart: the leave-delay
timer and an in-progress occurrence are in memory by design.

## Services

Service names are generic; the `eufy_vacuum.` prefix is only the integration domain Home Assistant files every service of this integration under.

| Service | What it does |
|---|---|
| `eufy_vacuum.get_schedules` | Schedules (with next run), presence settings and live presence state |
| `eufy_vacuum.save_schedule` | Create a schedule, or edit one by passing `schedule_id` |
| `eufy_vacuum.delete_schedule` | Remove a schedule |
| `eufy_vacuum.run_schedule_now` | Start a schedule immediately, ignoring its time and when-home policy |
| `eufy_vacuum.set_presence_settings` | Replace the vacuum's presence settings |

## Event

Every automatic start, skip, defer, pause or dock fires `vacuum_agent_schedule_action` with
`vacuum_entity_id`, `source` (`schedule`, `presence_deferred`, `presence_leave`, `manual`),
`action` (`started`, `skipped`, `deferred`, `paused`, `docked`), `reason`, `schedule_id`,
`profile_id` and `map_id` — see the generated [event reference](../dev/reference/EVENTS.md).

```yaml
automation:
  - alias: Tell me when the robot could not start
    trigger:
      - platform: event
        event_type: vacuum_agent_schedule_action
        event_data:
          action: skipped
    action:
      - service: notify.notify
        data:
          message: "Robot did not start: {{ trigger.event.data.reason }}"
```
