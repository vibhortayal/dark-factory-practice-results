'use strict';

/**
 * The whole service state lives in one object that is replaced wholesale by
 * reset and import. Handlers run synchronously on the single event loop, so a
 * handler that reads and writes the state without awaiting is atomic.
 */

function emptyState() {
  return {
    currency: 'EUR',
    minorUnits: 2,
    seededTotal: 0,
    users: new Map(), // id -> user
    byHandle: new Map(),
    byEmail: new Map(),
    tokens: new Map(), // token -> user id
    payments: [], // creation order, oldest first
    paymentsById: new Map(),
    requests: [],
    requestsById: new Map(),
    settlements: new Map(), // id -> {id, committed_at, payment_ids}
    operators: new Set(),
    idem: new Map(), // see idempotency.js
    authorizations: [], // creation order, oldest first
    authById: new Map(),
    openAuths: new Set(), // ids of authorizations whose status is 'open'
    nextExpiryMs: Infinity, // earliest expiry among open authorizations (lower bound)
    authTtlSeconds: 600,
    counters: { user: 0, payment: 0, request: 0, split: 0, settlement: 0, authorization: 0 },
  };
}

let current = emptyState();

const getState = () => current;
const setState = (s) => {
  current = s;
};

/** Next unused identifier `<prefix><n>`; skips ids a fixture or import already uses. */
function nextId(state, kind, prefix, taken) {
  for (;;) {
    state.counters[kind] += 1;
    const id = prefix + state.counters[kind];
    if (!taken || !taken.has(id)) return id;
  }
}

module.exports = { emptyState, getState, setState, nextId };
