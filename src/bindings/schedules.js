/**
 * ============================================================
 * BINDINGS: SCHEDULES + PRESENCE
 * ============================================================
 *
 * Wires the Schedules and Presence sidebar panels. Text / time / select inputs mutate the
 * card-side draft WITHOUT re-rendering (so a hass push mid-typing cannot wipe them);
 * chips and checkboxes change what is drawn, so they re-render.
 * ============================================================
 */

export function applySchedulesBindings(proto) {
  proto._bindSchedules = function () {
    const card = this.card;
    const state = () => card._state;
    const vacuum = () => state().vacuumEntityId?.();

    const refresh = async () => {
      await card.refreshSchedules?.({ force: true });
      card._scheduleRender();
    };

    // ---- schedules ----------------------------------------------------------

    card._on(card.$("[data-action='open-new-schedule']"), "click", () => {
      state().openScheduleEditor?.(null);
      card._scheduleRender();
    });

    card._on(card.$("[data-action='cancel-schedule-editor']"), "click", () => {
      state().closeScheduleEditor?.();
      card._scheduleRender();
    });

    card._onAll("[data-schedule-field]", "input", (e) => {
      state().updateScheduleDraft?.(e.currentTarget.dataset.scheduleField, e.currentTarget.value);
    });
    card._onAll("[data-schedule-field]", "change", (e) => {
      state().updateScheduleDraft?.(e.currentTarget.dataset.scheduleField, e.currentTarget.value);
    });

    card._onAll("[data-schedule-day]", "click", (e) => {
      state().toggleScheduleDraftDay?.(e.currentTarget.dataset.scheduleDay);
      card._scheduleRender();
    });

    card._onAll("[data-schedule-when-home]", "click", (e) => {
      state().updateScheduleDraft?.("when_home", e.currentTarget.dataset.scheduleWhenHome);
      card._scheduleRender();
    });

    card._on(card.$("[data-action='save-schedule']"), "click", async () => {
      const draft = state().scheduleDraft?.() ?? {};
      if (!draft.days?.length) {
        card.showToast(this.t("bind_schedules.pick_days"), { kind: "error" });
        return;
      }
      if (!draft.profile_id) {
        card.showToast(this.t("bind_schedules.pick_profile"), { kind: "error" });
        return;
      }
      const payload = {
        vacuum_entity_id: vacuum(),
        name: String(draft.name ?? "").trim() || undefined,
        time: draft.time,
        days: draft.days,
        profile_id: draft.profile_id,
        when_home: draft.when_home,
        enabled: draft.enabled !== false,
      };
      if (draft.schedule_id) payload.schedule_id = draft.schedule_id;

      const result = await card._actions.saveSchedule(payload);
      if (!result?.saved) {
        card.showToast(this.t("bind_schedules.could_not_save"), { kind: "error" });
        return;
      }
      state().closeScheduleEditor?.();
      card.showToast(this.t("bind_schedules.saved"), { kind: "success" });
      await refresh();
    });

    card._onAll("[data-action='edit-schedule']", "click", (e) => {
      const id = e.currentTarget.dataset.scheduleId;
      const schedule = (state().schedulesList?.() ?? []).find((s) => s.id === id);
      if (!schedule) return;
      state().openScheduleEditor?.(schedule);
      card._scheduleRender();
    });

    card._onAll("[data-action='toggle-schedule']", "click", async (e) => {
      const id = e.currentTarget.dataset.scheduleId;
      const s = (state().schedulesList?.() ?? []).find((x) => x.id === id);
      if (!s) return;
      const result = await card._actions.saveSchedule({
        vacuum_entity_id: vacuum(),
        schedule_id: s.id,
        name: s.name,
        time: s.time,
        days: s.days,
        profile_id: s.profile_id,
        map_id: s.map_id || undefined,
        when_home: s.when_home,
        enabled: !s.enabled,
      });
      if (!result?.saved) {
        card.showToast(this.t("bind_schedules.could_not_save"), { kind: "error" });
        return;
      }
      await refresh();
    });

    card._onAll("[data-action='run-schedule']", "click", async (e) => {
      const result = await card._actions.runScheduleNow({
        vacuum_entity_id: vacuum(),
        schedule_id: e.currentTarget.dataset.scheduleId,
      });
      if (result?.started) {
        card.showToast(this.t("bind_schedules.started"), { kind: "success" });
      } else {
        card.showToast(
          this.t("bind_schedules.not_started", { reason: this.esc(result?.reason ?? "error") }),
          { kind: "error" }
        );
      }
      await refresh();
    });

    card._onAll("[data-action='delete-schedule']", "click", async (e) => {
      const result = await card._actions.deleteSchedule({
        vacuum_entity_id: vacuum(),
        schedule_id: e.currentTarget.dataset.scheduleId,
      });
      if (!result?.deleted) {
        card.showToast(this.t("bind_schedules.could_not_delete"), { kind: "error" });
        return;
      }
      card.showToast(this.t("bind_schedules.deleted"), { kind: "success" });
      await refresh();
    });

    // ---- presence -----------------------------------------------------------

    card._onAll("[data-presence-person]", "click", (e) => {
      state().togglePresencePerson?.(e.currentTarget.dataset.presencePerson);
      card._scheduleRender();
    });

    card._onAll("[data-presence-field]", "input", (e) => {
      const el = e.currentTarget;
      const field = el.dataset.presenceField;
      if (el.type === "checkbox") return; // handled on change
      const value = el.type === "number" ? Number(el.value) : el.value;
      state().updatePresenceDraft?.(field, value);
    });
    card._onAll("[data-presence-field]", "change", (e) => {
      const el = e.currentTarget;
      const field = el.dataset.presenceField;
      if (el.type === "checkbox") {
        state().updatePresenceDraft?.(field, el.checked);
        card._scheduleRender();
      } else {
        state().updatePresenceDraft?.(field, el.type === "number" ? Number(el.value) : el.value);
      }
    });

    card._onAll("[data-presence-delay]", "click", (e) => {
      state().updatePresenceDraft?.("leave_delay_minutes", Number(e.currentTarget.dataset.presenceDelay));
      card._scheduleRender();
    });

    card._onAll("[data-presence-arrive]", "click", (e) => {
      state().updatePresenceDraft?.("arrive_action", e.currentTarget.dataset.presenceArrive);
      card._scheduleRender();
    });

    card._onAll("[data-quiet-room]", "input", (e) => {
      state().setQuietRule?.(e.currentTarget.dataset.quietRoom, e.currentTarget.value);
    });

    card._on(card.$("[data-action='discard-presence']"), "click", () => {
      state().clearPresenceDraft?.();
      card._scheduleRender();
    });

    card._on(card.$("[data-action='save-presence']"), "click", async () => {
      const p = state().presenceSettings?.() ?? {};
      const result = await card._actions.setPresenceSettings({
        vacuum_entity_id: vacuum(),
        persons: p.persons ?? [],
        leave_enabled: Boolean(p.leave_enabled),
        leave_profile_id: p.leave_profile_id ?? "",
        leave_delay_minutes: Number(p.leave_delay_minutes ?? 10),
        leave_min_interval_hours: Number(p.leave_min_interval_hours ?? 12),
        leave_window_start: p.leave_window_start ?? "",
        leave_window_end: p.leave_window_end ?? "",
        arrive_action: p.arrive_action ?? "none",
        quiet_rules: p.quiet_rules ?? {},
      });
      if (!result?.saved) {
        card.showToast(this.t("bind_schedules.presence_not_saved"), { kind: "error" });
        return;
      }
      state().clearPresenceDraft?.();
      card.showToast(this.t("bind_schedules.presence_saved"), { kind: "success" });
      await refresh();
    });
  };
}
