// In-memory service state. One instance is live at a time (store.s); reset/import
// build a complete replacement and swap it in one synchronous step.
export const STATE_SCHEMA_VERSION = 1;

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
    operators: new Set(),
    idem: new Map(), // "user\0method\0path\0key" -> {user_id,method,path,key,body,status,response}
    seq: 0,
    counters: { u: 0, p: 0, rq: 0, sp: 0, st: 0 },
  };
}

export const store = { s: emptyState() };

export function addUser(s, u) {
  s.users.set(u.id, u);
  s.byHandle.set(u.handle, u);
  s.byEmail.set(u.email, u);
}

const before = (a, b) => a.ts - b.ts || a.seq - b.seq;

// Keeps a list ordered by (ts, seq) ascending; the tail is the newest.
export function insertOrdered(list, rec) {
  list.push(rec);
  const n = list.length;
  if (n > 1 && before(list[n - 2], rec) > 0) list.sort(before);
}

export function newId(s, kind, prefix, exists) {
  let id;
  do id = `${prefix}_${++s.counters[kind]}`;
  while (exists(id));
  return id;
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
