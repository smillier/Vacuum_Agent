/**
 * ============================================================
 * STATE: SCHEDULES + PRESENCE
 * ============================================================
 *
 * The backend (scheduling/manager.py) is the source of truth. This module owns only the
 * card-side copy of its overview and the two forms being edited:
 *
 *   - the SCHEDULE draft (add / edit one schedule), and
 *   - the PRESENCE draft (people, leave run, arrive action, quiet rooms).
 *
 * Both drafts are plain objects mutated WITHOUT a re-render on text input, so a hass
 * state push in the middle of typing re-renders from the draft instead of wiping it.
 * ============================================================
 */

const PERSON_DOMAINS = ["person.", "device_tracker."];

export function applySchedulesState(proto) {
  proto._ensureSchedulesState = function () {
    if (!this._schedulesState) {
      this._schedulesState = {
        overview: null,
        editorOpen: false,
        scheduleDraft: null,
        presenceDraft: null,
      };
    }
    return this._schedulesState;
  };

  // ---- overview (what the backend last said) -------------------------------

  proto.setSchedulesOverview = function (payload) {
    const s = this._ensureSchedulesState();
    s.overview = payload ?? null;
    // A fresh overview after a SAVE is the new truth; drop the stale presence draft.
    // (Callers that merely refresh while the user is mid-edit go through
    // refreshSchedules, which skips this when a draft is open.)
    if (!s.presenceDraftDirty) s.presenceDraft = null;
  };

  proto.schedulesOverview = function () {
    return this._ensureSchedulesState().overview;
  };

  proto.schedulesList = function () {
    return this.schedulesOverview()?.schedules ?? [];
  };

  proto.presenceState = function () {
    return this.schedulesOverview()?.presence_state ?? null;
  };

  proto.hasSchedulesOverview = function () {
    return this.schedulesOverview() !== null;
  };

  // ---- schedule editor -----------------------------------------------------

  proto._emptyScheduleDraft = function () {
    return {
      schedule_id: "",
      name: "",
      time: "09:00",
      days: [0, 1, 2, 3, 4],
      profile_id: "",
      when_home: "run",
      enabled: true,
    };
  };

  proto.isScheduleEditorOpen = function () {
    return this._ensureSchedulesState().editorOpen;
  };

  proto.scheduleDraft = function () {
    return this._ensureSchedulesState().scheduleDraft ?? this._emptyScheduleDraft();
  };

  proto.openScheduleEditor = function (schedule = null) {
    const s = this._ensureSchedulesState();
    s.editorOpen = true;
    s.scheduleDraft = schedule
      ? {
          schedule_id: schedule.id,
          name: schedule.name ?? "",
          time: schedule.time ?? "09:00",
          days: [...(schedule.days ?? [])],
          profile_id: schedule.profile_id ?? "",
          when_home: schedule.when_home ?? "run",
          enabled: schedule.enabled !== false,
        }
      : this._emptyScheduleDraft();
  };

  proto.closeScheduleEditor = function () {
    const s = this._ensureSchedulesState();
    s.editorOpen = false;
    s.scheduleDraft = null;
  };

  proto.updateScheduleDraft = function (field, value) {
    const s = this._ensureSchedulesState();
    s.scheduleDraft = { ...this.scheduleDraft(), [field]: value };
  };

  proto.toggleScheduleDraftDay = function (day) {
    const draft = this.scheduleDraft();
    const d = Number(day);
    const days = draft.days.includes(d)
      ? draft.days.filter((x) => x !== d)
      : [...draft.days, d].sort((a, b) => a - b);
    this.updateScheduleDraft("days", days);
  };

  // ---- presence draft ------------------------------------------------------

  proto.presenceSettings = function () {
    const s = this._ensureSchedulesState();
    return s.presenceDraft ?? s.overview?.presence ?? {};
  };

  proto.isPresenceDirty = function () {
    return Boolean(this._ensureSchedulesState().presenceDraftDirty);
  };

  proto.updatePresenceDraft = function (field, value) {
    const s = this._ensureSchedulesState();
    s.presenceDraft = { ...this.presenceSettings(), [field]: value };
    s.presenceDraftDirty = true;
  };

  proto.togglePresencePerson = function (entityId) {
    const persons = this.presenceSettings().persons ?? [];
    this.updatePresenceDraft(
      "persons",
      persons.includes(entityId) ? persons.filter((p) => p !== entityId) : [...persons, entityId]
    );
  };

  /** Set one room's occupancy sources from a comma-separated entity-id string. */
  proto.setQuietRule = function (roomId, text) {
    const rules = { ...(this.presenceSettings().quiet_rules ?? {}) };
    const ids = String(text ?? "")
      .split(",")
      .map((x) => x.trim().toLowerCase())
      .filter(Boolean);
    if (ids.length) rules[String(roomId)] = ids;
    else delete rules[String(roomId)];
    this.updatePresenceDraft("quiet_rules", rules);
  };

  proto.clearPresenceDraft = function () {
    const s = this._ensureSchedulesState();
    s.presenceDraft = null;
    s.presenceDraftDirty = false;
  };

  /** person.* and device_tracker.* entities Home Assistant currently knows about. */
  proto.presenceCandidates = function () {
    const states = this.hass?.states ?? {};
    return Object.keys(states)
      .filter((id) => PERSON_DOMAINS.some((d) => id.startsWith(d)))
      .sort((a, b) => a.localeCompare(b));
  };
}
