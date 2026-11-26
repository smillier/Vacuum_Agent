// Service wrappers for scheduling + presence (scheduling/manager.py).
//
// Every call returns the unwrapped service payload, or null on failure — a refused write
// is a ServiceValidationError server-side, which callService reports as null. Callers
// treat null as "did not save" and toast; they never throw into the render cycle.

const DOMAIN = "eufy_vacuum";

export function applySchedulesActions(proto) {
  proto.getSchedules = async function ({ vacuum_entity_id } = {}) {
    const vacuumEntityId = vacuum_entity_id ?? this.state?.vacuumEntityId?.();
    if (!vacuumEntityId) return null;
    return this.callService(
      DOMAIN, "get_schedules", { vacuum_entity_id: vacuumEntityId }, true
    );
  };

  proto.saveSchedule = async function (data = {}) {
    return this.callService(DOMAIN, "save_schedule", data, true);
  };

  proto.deleteSchedule = async function ({ vacuum_entity_id, schedule_id } = {}) {
    return this.callService(
      DOMAIN, "delete_schedule", { vacuum_entity_id, schedule_id }, true
    );
  };

  proto.runScheduleNow = async function ({ vacuum_entity_id, schedule_id } = {}) {
    return this.callService(
      DOMAIN, "run_schedule_now", { vacuum_entity_id, schedule_id }, true
    );
  };

  proto.setPresenceSettings = async function (data = {}) {
    return this.callService(DOMAIN, "set_presence_settings", data, true);
  };
}
