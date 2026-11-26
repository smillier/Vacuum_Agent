// Unit tests for the card-side schedules + presence state.
// Run: node --test src/state/schedules.test.mjs
//
//   [SCH-1] a new schedule opens on a sane default (weekdays, 09:00, "run anyway").
//   [SCH-2] editing opens a COPY of the schedule — mutating the draft never touches the overview.
//   [SCH-3] toggling a day keeps the list sorted and de-duplicated.
//   [SCH-4] a background overview refresh keeps an in-progress presence draft; after a save
//           (draft cleared) the new overview becomes the baseline.
//   [SCH-5] togglePresencePerson adds then removes.
//   [SCH-6] setQuietRule parses a comma list, lower-cases it, and an empty string removes the rule.
//   [SCH-7] presenceCandidates lists only person.* / device_tracker.*, sorted.
import { test } from "node:test";
import assert from "node:assert/strict";
import { applySchedulesState } from "./schedules.js";

function makeCard(hass) {
  const proto = {};
  applySchedulesState(proto);
  const card = Object.create(proto);
  card.hass = hass;
  return card;
}

test("[SCH-1] new schedule draft defaults", () => {
  const c = makeCard();
  c.openScheduleEditor(null);
  assert.equal(c.isScheduleEditorOpen(), true);
  assert.deepEqual(c.scheduleDraft().days, [0, 1, 2, 3, 4]);
  assert.equal(c.scheduleDraft().time, "09:00");
  assert.equal(c.scheduleDraft().when_home, "run");
  assert.equal(c.scheduleDraft().schedule_id, "");
});

test("[SCH-2] editing copies, never aliases", () => {
  const c = makeCard();
  const stored = { id: "s1", name: "N", time: "07:30", days: [0, 2], profile_id: "p", when_home: "defer", enabled: false };
  c.setSchedulesOverview({ schedules: [stored], presence: {} });
  c.openScheduleEditor(stored);
  c.toggleScheduleDraftDay(4);
  assert.deepEqual(c.scheduleDraft().days, [0, 2, 4]);
  assert.deepEqual(stored.days, [0, 2]);
  assert.equal(c.scheduleDraft().enabled, false);
  c.closeScheduleEditor();
  assert.equal(c.isScheduleEditorOpen(), false);
});

test("[SCH-3] day toggle stays sorted and unique", () => {
  const c = makeCard();
  c.openScheduleEditor(null);
  c.toggleScheduleDraftDay("6");
  c.toggleScheduleDraftDay(5);
  assert.deepEqual(c.scheduleDraft().days, [0, 1, 2, 3, 4, 5, 6]);
  c.toggleScheduleDraftDay(0);
  c.toggleScheduleDraftDay(0);
  assert.deepEqual(c.scheduleDraft().days, [0, 1, 2, 3, 4, 5, 6]);
});

test("[SCH-4] refresh keeps a dirty presence draft; a cleared draft takes the new baseline", () => {
  const c = makeCard();
  c.setSchedulesOverview({ schedules: [], presence: { arrive_action: "none" } });
  c.updatePresenceDraft("arrive_action", "pause");
  c.setSchedulesOverview({ schedules: [], presence: { arrive_action: "none" } });
  assert.equal(c.presenceSettings().arrive_action, "pause");
  assert.equal(c.isPresenceDirty(), true);

  c.clearPresenceDraft();
  c.setSchedulesOverview({ schedules: [], presence: { arrive_action: "dock" } });
  assert.equal(c.presenceSettings().arrive_action, "dock");
  assert.equal(c.isPresenceDirty(), false);
});

test("[SCH-5] person toggle", () => {
  const c = makeCard();
  c.setSchedulesOverview({ schedules: [], presence: { persons: [] } });
  c.togglePresencePerson("person.me");
  assert.deepEqual(c.presenceSettings().persons, ["person.me"]);
  c.togglePresencePerson("person.me");
  assert.deepEqual(c.presenceSettings().persons, []);
});

test("[SCH-6] quiet rule parsing", () => {
  const c = makeCard();
  c.setSchedulesOverview({ schedules: [], presence: {} });
  c.setQuietRule(3, " Binary_Sensor.Bed , binary_sensor.bed2,, ");
  assert.deepEqual(c.presenceSettings().quiet_rules, { 3: ["binary_sensor.bed", "binary_sensor.bed2"] });
  c.setQuietRule(3, "   ");
  assert.deepEqual(c.presenceSettings().quiet_rules, {});
});

test("[SCH-7] presence candidates", () => {
  const c = makeCard({ states: { "person.b": {}, "light.x": {}, "device_tracker.a": {}, "person.a": {} } });
  assert.deepEqual(c.presenceCandidates(), ["device_tracker.a", "person.a", "person.b"]);
  assert.deepEqual(makeCard().presenceCandidates(), []);
});
