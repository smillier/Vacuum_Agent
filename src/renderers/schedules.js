// Schedules + presence panels — rooms sidebar, beside Run Profiles / Pause Timeout.
//
// Two asides: WHEN to clean (schedules) and WHO is home while it happens (presence).
// They reuse the Run Profiles panel's classes on purpose: the sidebar panels are a set
// that has to read as one surface, and a second class family would drift from it.
//
// Everything user-typed is rendered through escapeHtml; every string through this.t().

const DAY_COUNT = 7;
const LEAVE_DELAYS = [0, 5, 10, 30, 60];
const WHEN_HOME = ["run", "skip", "defer"];
const ARRIVE = ["none", "pause", "dock"];

export function applySchedulesRenderers(proto) {
  proto._scheduleLang = function (state) {
    return state.hass?.locale?.language || state.hass?.language || undefined;
  };

  /** Short weekday names, Monday first (index 0 = Monday, matching the backend). */
  proto._weekdayLabels = function (state) {
    const fmt = new Intl.DateTimeFormat(this._scheduleLang(state), { weekday: "short" });
    // 2024-01-01 was a Monday.
    return Array.from({ length: DAY_COUNT }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
  };

  proto._formatNextRun = function (state, iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(this._scheduleLang(state), {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  proto._profileName = function (state, profileId) {
    const profile = (state.savedRunProfiles?.() ?? []).find((p) => p.id === profileId);
    return profile?.name ?? "";
  };

  proto._profileOptions = function (state, selectedId, { allowNone = false } = {}) {
    const profiles = state.savedRunProfiles?.() ?? [];
    const none = allowNone || !selectedId
      ? `<option value="">${this.t("schedules.profile_none")}</option>`
      : "";
    return none + profiles.map((p) => `
      <option value="${this.escapeHtml(p.id)}" ${p.id === selectedId ? "selected" : ""}>${this.escapeHtml(p.name)}</option>
    `).join("");
  };

  proto.renderSchedulesPanel = function (state) {
    const schedules = state.schedulesList?.() ?? [];
    const editorOpen = Boolean(state.isScheduleEditorOpen?.());
    const draft = state.scheduleDraft?.() ?? {};
    const days = this._weekdayLabels(state);

    return `
      <aside class="evcc-run-profiles-panel" data-schedules-panel>
        <div class="evcc-run-profiles-panel-header">
          <div>
            <div class="evcc-run-profiles-title">${this.t("schedules.title")}</div>
            <div class="evcc-run-profiles-subtitle">${this.t("schedules.subtitle")}</div>
          </div>
          <button type="button" class="evcc-chip evcc-chip--save" data-action="open-new-schedule">
            ${this.t("schedules.add")}
          </button>
        </div>

        ${editorOpen ? `
          <div class="evcc-run-profiles-editor">
            <div class="evcc-run-profiles-editor-title">
              ${draft.schedule_id ? this.t("schedules.editor_title_edit") : this.t("schedules.editor_title_new")}
            </div>

            <label class="evcc-run-profiles-field">
              <span class="evcc-run-profiles-label">${this.t("schedules.name_label")}</span>
              <input type="text" class="evcc-run-profiles-input"
                value="${this.escapeHtml(draft.name ?? "")}"
                placeholder="${this.t("schedules.name_placeholder")}"
                data-schedule-field="name" />
            </label>

            <label class="evcc-run-profiles-field">
              <span class="evcc-run-profiles-label">${this.t("schedules.time_label")}</span>
              <input type="time" class="evcc-run-profiles-input"
                value="${this.escapeHtml(draft.time ?? "09:00")}"
                data-schedule-field="time" />
            </label>

            <div class="evcc-run-profiles-field">
              <span class="evcc-run-profiles-label">${this.t("schedules.days_label")}</span>
              <div class="evcc-chips">
                ${days.map((label, i) => `
                  <button type="button"
                    class="evcc-chip ${draft.days?.includes(i) ? "active" : ""}"
                    data-schedule-day="${i}">${this.escapeHtml(label)}</button>
                `).join("")}
              </div>
            </div>

            <label class="evcc-run-profiles-field">
              <span class="evcc-run-profiles-label">${this.t("schedules.profile_label")}</span>
              <select class="evcc-run-profiles-input" data-schedule-field="profile_id">
                ${this._profileOptions(state, draft.profile_id)}
              </select>
            </label>

            <div class="evcc-run-profiles-field">
              <span class="evcc-run-profiles-label">${this.t("schedules.when_home_label")}</span>
              <div class="evcc-chips">
                ${WHEN_HOME.map((value) => `
                  <button type="button"
                    class="evcc-chip ${draft.when_home === value ? "active" : ""}"
                    data-schedule-when-home="${value}">${this.t(`schedules.when_home_${value}`)}</button>
                `).join("")}
              </div>
              <div class="evcc-run-profiles-hint">${this.t(`schedules.when_home_${draft.when_home ?? "run"}_hint`)}</div>
            </div>

            <div class="evcc-run-profiles-editor-actions">
              <button type="button" class="evcc-chip evcc-chip--save" data-action="save-schedule">
                ${this.t("common.save")}
              </button>
              <button type="button" class="evcc-chip" data-action="cancel-schedule-editor">
                ${this.t("common.cancel")}
              </button>
            </div>
          </div>
        ` : ""}

        ${schedules.length ? `
          <div class="evcc-run-profiles-list">
            ${schedules.map((s) => this._renderScheduleRow(state, s, days)).join("")}
          </div>
        ` : `
          <div class="evcc-run-profiles-empty">${this.t("schedules.empty")}</div>
        `}
      </aside>
    `;
  };

  proto._renderScheduleRow = function (state, schedule, dayLabels) {
    const id = this.escapeHtml(schedule.id);
    const dayText = (schedule.days ?? []).map((d) => dayLabels[d] ?? "").join(" · ");
    const profileName = this._profileName(state, schedule.profile_id);
    const next = schedule.enabled ? this._formatNextRun(state, schedule.next_run) : "";
    const last = schedule.last_result;

    return `
      <div class="evcc-run-profiles-selected" data-schedule-row="${id}">
        <div class="evcc-run-profiles-selected-name">
          ${this.escapeHtml(schedule.name)}
          <span>${this.escapeHtml(schedule.time)}</span>
        </div>
        <div class="evcc-run-profiles-selected-meta">
          <span>${this.escapeHtml(dayText)}</span>
          <span>${profileName
            ? this.escapeHtml(profileName)
            : this.t("schedules.profile_missing")}</span>
          ${schedule.when_home && schedule.when_home !== "run"
            ? `<span>${this.t(`schedules.when_home_${schedule.when_home}`)}</span>` : ""}
        </div>
        ${next ? `<div class="evcc-run-profiles-hint">${this.t("schedules.next_run", { when: this.escapeHtml(next) })}</div>` : ""}
        ${schedule.deferred ? `<div class="evcc-run-profiles-hint">${this.t("schedules.deferred_today")}</div>` : ""}
        ${last && last.reason && !last.started
          ? `<div class="evcc-run-profiles-hint">${this.t("schedules.last_not_started", { reason: this.escapeHtml(last.reason) })}</div>` : ""}
        <div class="evcc-run-profiles-editor-actions">
          <button type="button" class="evcc-chip ${schedule.enabled ? "active" : ""}"
            data-action="toggle-schedule" data-schedule-id="${id}">
            ${schedule.enabled ? this.t("common.on") : this.t("common.off")}
          </button>
          <button type="button" class="evcc-chip" data-action="run-schedule" data-schedule-id="${id}">
            ${this.t("schedules.run_now")}
          </button>
          <button type="button" class="evcc-chip" data-action="edit-schedule" data-schedule-id="${id}">
            ${this.t("common.edit")}
          </button>
          <button type="button" class="evcc-chip" data-action="delete-schedule" data-schedule-id="${id}">
            ${this.t("common.delete")}
          </button>
        </div>
      </div>
    `;
  };

  proto.renderPresencePanel = function (state) {
    // Nothing to configure until the first overview arrives (and never on a failed fetch).
    if (!state.hasSchedulesOverview?.()) return "";

    const presence = state.presenceSettings?.() ?? {};
    const live = state.presenceState?.() ?? {};
    const people = presence.persons ?? [];
    const candidates = state.presenceCandidates?.() ?? [];
    const rooms = state.getRoomsForActiveMap?.() ?? [];
    const quiet = presence.quiet_rules ?? {};
    const dirty = Boolean(state.isPresenceDirty?.());

    return `
      <aside class="evcc-run-profiles-panel" data-presence-panel>
        <div class="evcc-run-profiles-panel-header">
          <div>
            <div class="evcc-run-profiles-title">${this.t("presence.title")}</div>
            <div class="evcc-run-profiles-subtitle">${this.t("presence.subtitle")}</div>
          </div>
        </div>

        <div class="evcc-run-profiles-field">
          <span class="evcc-run-profiles-label">${this.t("presence.people_label")}</span>
          ${candidates.length ? `
            <div class="evcc-chips">
              ${candidates.map((entityId) => {
                const home = live.persons?.[entityId];
                const name = state.hass?.states?.[entityId]?.attributes?.friendly_name ?? entityId;
                return `
                  <button type="button"
                    class="evcc-chip ${people.includes(entityId) ? "active" : ""}"
                    data-presence-person="${this.escapeHtml(entityId)}"
                    title="${this.escapeHtml(entityId)}${home ? ` — ${this.escapeHtml(home)}` : ""}"
                  >${this.escapeHtml(name)}</button>`;
              }).join("")}
            </div>
          ` : `<div class="evcc-run-profiles-empty">${this.t("presence.no_people")}</div>`}
          ${people.length ? `
            <div class="evcc-run-profiles-hint">${live.everyone_away
              ? this.t("presence.state_away")
              : this.t("presence.state_home")}${live.leave_pending ? ` · ${this.t("presence.leave_pending")}` : ""}</div>
          ` : ""}
        </div>

        <label class="evcc-run-profiles-toggle">
          <input type="checkbox" ${presence.leave_enabled ? "checked" : ""} data-presence-field="leave_enabled" />
          <span>${this.t("presence.leave_toggle")}</span>
        </label>

        ${presence.leave_enabled ? `
          <label class="evcc-run-profiles-field">
            <span class="evcc-run-profiles-label">${this.t("presence.leave_profile")}</span>
            <select class="evcc-run-profiles-input" data-presence-field="leave_profile_id">
              ${this._profileOptions(state, presence.leave_profile_id)}
            </select>
          </label>

          <div class="evcc-run-profiles-field">
            <span class="evcc-run-profiles-label">${this.t("presence.leave_delay")}</span>
            <div class="evcc-chips">
              ${LEAVE_DELAYS.map((minutes) => `
                <button type="button"
                  class="evcc-chip ${Number(presence.leave_delay_minutes ?? 10) === minutes ? "active" : ""}"
                  data-presence-delay="${minutes}">${this.t("pause_timeout.minutes_short", { minutes })}</button>
              `).join("")}
            </div>
          </div>

          <label class="evcc-run-profiles-field">
            <span class="evcc-run-profiles-label">${this.t("presence.min_interval")}</span>
            <input type="number" min="0" max="168" step="1" class="evcc-run-profiles-input"
              value="${this.escapeHtml(String(presence.leave_min_interval_hours ?? 12))}"
              data-presence-field="leave_min_interval_hours" />
          </label>

          <div class="evcc-run-profiles-field">
            <span class="evcc-run-profiles-label">${this.t("presence.window_label")}</span>
            <div class="evcc-chips">
              <input type="time" class="evcc-run-profiles-input"
                value="${this.escapeHtml(presence.leave_window_start ?? "")}"
                data-presence-field="leave_window_start" />
              <input type="time" class="evcc-run-profiles-input"
                value="${this.escapeHtml(presence.leave_window_end ?? "")}"
                data-presence-field="leave_window_end" />
            </div>
            <div class="evcc-run-profiles-hint">${this.t("presence.window_hint")}</div>
          </div>
        ` : ""}

        <div class="evcc-run-profiles-field">
          <span class="evcc-run-profiles-label">${this.t("presence.arrive_label")}</span>
          <div class="evcc-chips">
            ${ARRIVE.map((value) => `
              <button type="button"
                class="evcc-chip ${(presence.arrive_action ?? "none") === value ? "active" : ""}"
                data-presence-arrive="${value}">${this.t(`presence.arrive_${value}`)}</button>
            `).join("")}
          </div>
        </div>

        ${rooms.length ? `
          <div class="evcc-run-profiles-field">
            <span class="evcc-run-profiles-label">${this.t("presence.quiet_title")}</span>
            <div class="evcc-run-profiles-hint">${this.t("presence.quiet_hint")}</div>
            ${rooms.map((room) => `
              <label class="evcc-run-profiles-field">
                <span class="evcc-run-profiles-label">${this.escapeHtml(room.name)}${
                  (live.occupied_rooms ?? []).includes(String(room.id))
                    ? ` · ${this.t("presence.occupied_now")}` : ""}</span>
                <input type="text" class="evcc-run-profiles-input"
                  value="${this.escapeHtml((quiet[String(room.id)] ?? []).join(", "))}"
                  placeholder="binary_sensor.bedroom_occupancy"
                  data-quiet-room="${this.escapeHtml(String(room.id))}" />
              </label>
            `).join("")}
          </div>
        ` : ""}

        <div class="evcc-run-profiles-editor-actions">
          <button type="button" class="evcc-chip evcc-chip--save ${dirty ? "active" : ""}" data-action="save-presence">
            ${this.t("common.save")}
          </button>
          ${dirty ? `
            <button type="button" class="evcc-chip" data-action="discard-presence">
              ${this.t("common.cancel")}
            </button>` : ""}
        </div>
      </aside>
    `;
  };
}
