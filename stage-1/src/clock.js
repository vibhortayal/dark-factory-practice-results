'use strict';

let last = 0;

/** Monotonic wall clock, whole seconds, RFC 3339 with an explicit +00:00 offset. */
function nowTimestamp() {
  last = Math.max(last, Math.floor(Date.now() / 1000) * 1000);
  return new Date(last).toISOString().replace(/\.\d+Z$/, '+00:00');
}

module.exports = { nowTimestamp };
