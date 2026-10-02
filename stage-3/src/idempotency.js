'use strict';

/**
 * Idempotency records live in state.idem, keyed by user, method, path and key.
 * Only successful (201) responses are recorded, so a key whose request failed
 * stays unclaimed.
 */

const { jsonEqual } = require('./json');
const { conflict } = require('./errors');

const recordKey = (userId, method, path, key) => JSON.stringify([userId, method, path, key]);

/** Returns the replay result {status:200, body}, null for a fresh key, or throws 409. */
function lookup(state, userId, method, path, key, body) {
  const record = state.idem.get(recordKey(userId, method, path, key));
  if (!record) return null;
  if (!jsonEqual(record.body, body)) {
    throw conflict('idempotency_key_reuse', 'idempotency key was used with a different request');
  }
  return { status: 200, body: record.response };
}

function store(state, userId, method, path, key, body, response) {
  state.idem.set(recordKey(userId, method, path, key), {
    user_id: userId, method, path, key, body, response: JSON.parse(JSON.stringify(response)),
  });
}

module.exports = { lookup, store };
