'use strict';

/** "Newest first by created_at": records carry their own times, so order by them, not by insertion. */

const I = require('./instant');

const timeOf = (record) => I.parseCached(record.created_at) || I.MIN;

/** A new array, newest first; ties keep the later-created record first (stable sort). */
function newestFirst(records) {
  return records.slice().reverse().sort((a, b) => I.compare(timeOf(b), timeOf(a)));
}

module.exports = { newestFirst };
