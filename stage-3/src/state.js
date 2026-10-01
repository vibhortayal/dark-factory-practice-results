// In-memory service state. One instance is live at a time (store.s); reset/import
// build a complete replacement and swap it in one synchronous step.
import { stampAt } from './time.js';
import { msToNs } from './instants.js';

export const STATE_SCHEMA_VERSION = 3;

export function emptyState() {
  return {
    currency: 'EUR',
    minorUnits: 2,
    users: new Map(), // id -> {id,email,display_name,handle,balance,password_hash}
    byHandle: new Map(),
    byEmail: new Map(),
    tokens: new Map(), // token -> user id
    payments: [], // ascending by (ts, seq)
    paymentById: new Map(),
    requests: [],
    requestById: new Map(),
    splits: [], // {id, user_id, amount, note, shares, request_ids, created_at}
    settlements: [], // {id, operator_id, committed_at, payment_ids}
    authTtl: 600, // authorization_ttl_seconds
    authorizations: [], // ascending by (ts, seq); see publicAuthorization
    authById: new Map(),
    openAuths: new Set(), // authorizations whose status is 'open' (the only ones that hold funds)
    operators: new Set(),
    idem: new Map(), // "user\0method\0path\0key" -> {user_id,method,path,key,body,status,response}
    seq: 0,
    kseq: 0, // knowledge position: bumped by every revision and authorization event
    lastMs: 0, // latest stamp issued; stamps strictly increase so no two records share an instant
    snapshots: new Map(), // statement snapshot token -> { user_id, from, to, known_at, kseq, ... }
    counters: { u: 0, p: 0, rq: 0, sp: 0, st: 0, a: 0 },
  };
}

export const store = { s: emptyState() };

export function addUser(s, u) {
  s.users.set(u.id, u);
  s.byHandle.set(u.handle, u);
  s.byEmail.set(u.email, u);
}

const before = (a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.seq - b.seq);

// Keeps a list ordered by (ts, seq) ascending; the tail is the newest.
export function insertOrdered(list, rec) {
  list.push(rec);
  const n = list.length;
  if (n > 1 && before(list[n - 2], rec) > 0) list.sort(before);
}

// Payment ids are fixed-width so that plain string order is also creation order.
export function newId(s, kind, prefix, exists) {
  let id;
  do id = `${prefix}_${kind === 'p' ? String(++s.counters[kind]).padStart(10, '0') : ++s.counters[kind]}`;
  while (exists(id));
  return id;
}

// The service clock never runs backwards and never issues the same millisecond twice.
export const clockMs = (s) => Math.max(Date.now(), s.lastMs);
export function tickStamp(s) {
  s.lastMs = Math.max(Date.now(), s.lastMs + 1);
  return stampAt(s.lastMs);
}

export const publicPayment = (p) => ({
  payment_id: p.payment_id,
  from_user_id: p.from_user_id,
  from_handle: p.from_handle,
  to_user_id: p.to_user_id,
  to_handle: p.to_handle,
  amount: p.amount,
  currency: p.currency,
  note: p.note,
  visibility: p.visibility,
  request_id: p.request_id,
  settlement_id: p.settlement_id,
  authorization_id: p.authorization_id,
  created_at: p.created_at,
});

export const publicRequest = (r) => ({
  request_id: r.request_id,
  requester_id: r.requester_id,
  requester_handle: r.requester_handle,
  payer_id: r.payer_id,
  payer_handle: r.payer_handle,
  amount: r.amount,
  currency: r.currency,
  note: r.note,
  status: r.status,
  payment_id: r.payment_id,
  created_at: r.created_at,
});

export const publicAuthorization = (a) => ({
  authorization_id: a.authorization_id,
  from_user_id: a.from_user_id,
  from_handle: a.from_handle,
  to_user_id: a.to_user_id,
  to_handle: a.to_handle,
  amount: a.amount,
  captured_amount: a.captured_amount,
  remaining_amount: a.status === 'open' ? a.amount - a.captured_amount : 0,
  currency: a.currency,
  note: a.note,
  visibility: a.visibility,
  status: a.status,
  expires_at: a.expires_at,
  payment_id: a.payment_id,
  payment_ids: [...a.payment_ids],
  created_at: a.created_at,
  closed_at: a.closed_at,
});

// Expiry is derived from the clock, never from a timer: every request calls this first, so an
// authorization whose expires_at is at or before now is 'expired' and holds nothing.
export function sweep(s, nowMs = clockMs(s)) {
  const nowNs = msToNs(nowMs);
  for (const a of s.openAuths) {
    if (a.expNs <= nowNs) {
      a.status = 'expired';
      a.closed_at = a.expires_at;
      s.openAuths.delete(a);
    }
  }
}

// Sum of the remaining amounts of the user's open (unexpired) outgoing authorizations.
export function heldOf(s, userId) {
  let held = 0;
  for (const a of s.openAuths) if (a.from_user_id === userId) held += a.amount - a.captured_amount;
  return held;
}
export const availableOf = (s, user) => user.balance - heldOf(s, user.id);
