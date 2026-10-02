'use strict';

/** "Newest first by created_at": records carry their own times, so order by them, not by insertion. */

const { parseTimestamp } = require('./clock');

const cache = new WeakMap();
const timeOf = (record) => {
  let ms = cache.get(record);
  if (ms === undefined) {
    ms = parseTimestamp(record.created_at) ?? 0;
    cache.set(record, ms);
  }
  return ms;
};

/** A new array, newest first; ties keep the later-created record first (stable sort). */
function newestFirst(records) {
  return records.slice().reverse().sort((a, b) => timeOf(b) - timeOf(a));
}

module.exports = { newestFirst };
