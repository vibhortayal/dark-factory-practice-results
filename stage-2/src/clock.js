'use strict';

let last = 0;

let frozen = null;

/**
 * Monotonic wall clock in epoch milliseconds. While a request's synchronous part runs the clock
 * is frozen (see `freeze`), so the expiry sweep, the handler's decisions and every timestamp it
 * writes use one and the same instant.
 */
function nowMs() {
  if (frozen !== null) return frozen;
  last = Math.max(last, Date.now());
  return last;
}

function freeze() {
  frozen = null;
  frozen = nowMs();
}

function unfreeze() {
  frozen = null;
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

module.exports = { freeze, unfreeze, nowMs, formatTimestamp, nowTimestamp, parseTimestamp };
