'use strict';

let last = 0;
let floor = 0;

let frozen = null;

/**
 * Monotonic wall clock in epoch milliseconds. While a request's synchronous part runs the clock
 * is frozen (see `freeze`), so the expiry sweep, the handler's decisions and every timestamp it
 * writes use one and the same instant.
 */
function nowMs() {
  if (frozen !== null) return frozen;
  last = Math.max(last, Date.now(), floor);
  return last;
}

/** The clock never reports an instant before `ms` (after a reset or an import). */
function setFloor(ms) {
  floor = ms;
  last = Math.max(last, ms);
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

module.exports = { freeze, unfreeze, nowMs, setFloor, formatTimestamp, nowTimestamp };
