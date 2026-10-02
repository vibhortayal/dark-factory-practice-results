'use strict';

let last = 0;

/** Monotonic wall clock in epoch milliseconds. */
function nowMs() {
  last = Math.max(last, Date.now());
  return last;
}

/** RFC 3339 with millisecond precision and an explicit +00:00 offset. */
function formatTimestamp(ms) {
  return new Date(ms).toISOString().replace('Z', '+00:00');
}

const nowTimestamp = () => formatTimestamp(nowMs());

const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

/** Epoch milliseconds of an RFC 3339 string, or null when it is not one. */
function parseTimestamp(text) {
  if (typeof text !== 'string' || !RFC3339.test(text)) return null;
  const ms = Date.parse(text);
  return Number.isNaN(ms) ? null : ms;
}

module.exports = { nowMs, formatTimestamp, nowTimestamp, parseTimestamp };
