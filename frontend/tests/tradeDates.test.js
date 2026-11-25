import test from 'node:test';
import assert from 'node:assert/strict';
import { dateTimeIST, dateInRange } from '../src/utils/tradeDates.js';
test('naive server timestamps remain IST', () => {
  assert.equal(dateTimeIST('2026-11-25 14:55:23'), '25/11/2026 14:55:23');
  assert.equal(dateTimeIST('2026-11-25T14:55:23'), '25/11/2026 14:55:23');
});
test('offset timestamps convert across midnight to IST', () => {
  assert.equal(dateTimeIST('2026-11-24T20:00:00Z'), '25/11/2026 01:30:00');
  assert.equal(dateTimeIST('2026-11-25T14:55:23+05:30'), '25/11/2026 14:55:23');
  assert.ok(dateInRange('2026-11-24T20:00:00Z', '2026-11-25', '2026-11-25'));
});
test('inclusive dates and empty timestamps', () => {
  assert.ok(dateInRange('2026-11-25 23:59:59', '2026-11-24', '2026-11-25'));
  assert.ok(!dateInRange('2026-11-26 00:00:00', '2026-11-24', '2026-11-25'));
  assert.ok(!dateInRange('', '2026-11-25', '2026-11-25'));
  assert.ok(dateInRange('', '', ''));
  assert.equal(dateTimeIST('—'), '—');
});
