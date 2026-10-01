// GET /_test/export and POST /_test/import.
// state.schema_version is this module's own version so later stages can read it.
import { emptyState, addUser, insertOrdered, sweep, STATE_SCHEMA_VERSION } from './state.js';
import { invalid } from './errors.js';
import { isObject, has } from './json.js';
import { parseStamp, parseInstant } from './time.js';
import { HANDLE_RE } from './validate.js';
import { validHashFormat } from './passwords.js';

const PAYMENT_KEYS = ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'created_at'];
const AUTH_KEYS = ['authorization_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'captured_amount', 'currency', 'note', 'visibility', 'status', 'expires_at', 'payment_id', 'payment_ids', 'created_at', 'voided_at'];
const REQUEST_KEYS = ['request_id', 'requester_id', 'requester_handle', 'payer_id', 'payer_handle', 'amount', 'currency', 'note', 'status', 'payment_id', 'created_at'];
const pick = (o, keys) => Object.fromEntries(keys.map((k) => [k, o[k]]));

export const idemId = (userId, method, path, key) => `${userId}\0${method}\0${path}\0${key}`;

// Runs synchronously, so the result is a consistent point-in-time copy.
export function exportState(s) {
  sweep(s);
  return {
    track: 'pocketful',
    format_version: 1,
    state: {
      schema_version: STATE_SCHEMA_VERSION,
      currency: s.currency,
      minor_units: s.minorUnits,
      authorization_ttl_seconds: s.authTtl,
      users: [...s.users.values()].map((u) => pick(u, ['id', 'email', 'display_name', 'handle', 'balance', 'password_hash'])),
      tokens: [...s.tokens].map(([token, user_id]) => ({ token, user_id })),
      payments: s.payments.map((p) => pick(p, PAYMENT_KEYS)),
      requests: s.requests.map((r) => pick(r, REQUEST_KEYS)),
      splits: s.splits.map((x) => ({ ...x, shares: x.shares.map((h) => ({ ...h })), request_ids: [...x.request_ids] })),
      settlements: s.settlements.map((x) => ({ ...x, payment_ids: [...x.payment_ids] })),
      authorizations: s.authorizations.map((a) => ({ ...pick(a, AUTH_KEYS), payment_ids: [...a.payment_ids] })),
      settlement_operator_ids: [...s.operators],
      idempotency: [...s.idem.values()].map((e) => ({ ...e })),
      counters: { ...s.counters },
    },
  };
}

const bad = (m) => invalid(`import: ${m}`);
const str = (v) => typeof v === 'string';
const id64 = (v) => str(v) && v.length >= 1 && v.length <= 64;
const int = (v) => typeof v === 'number' && Number.isSafeInteger(v);
const arr = (st, k) => {
  if (!Array.isArray(st[k])) throw bad(`${k} must be an array`);
  return st[k];
};
const obj = (v, what) => {
  if (!isObject(v)) throw bad(`${what} must be an object`);
  return v;
};

// Validates the whole export envelope and returns a fresh state; never touches live state.
export function importState(doc) {
  if (!isObject(doc)) throw bad('body must be a JSON object');
  if (doc.track !== 'pocketful') throw bad('track must be "pocketful"');
  if (doc.format_version !== 1) throw bad('format_version must be 1');
  const st = obj(doc.state, 'state');
  // Stage-1 exports (schema 1) have no authorizations and a default lifetime; stage-2 exports are schema 2.
  if (st.schema_version !== 1 && st.schema_version !== 2) throw bad('unsupported state schema_version');
  const v1 = st.schema_version === 1;
  if (!str(st.currency) || st.currency === '') throw bad('currency is invalid');
  if (![0, 2, 3].includes(st.minor_units)) throw bad('minor_units is invalid');
  const s = emptyState();
  s.currency = st.currency;
  s.minorUnits = st.minor_units;
  if (!v1) {
    const ttl = st.authorization_ttl_seconds;
    if (typeof ttl !== 'number' || !Number.isInteger(ttl) || ttl < 1) throw bad('authorization_ttl_seconds is invalid');
    s.authTtl = ttl;
  }

  for (const raw of arr(st, 'users')) {
    const u = obj(raw, 'user');
    if (!id64(u.id) || !str(u.email) || !str(u.display_name) || !str(u.handle) || !HANDLE_RE.test(u.handle)) throw bad('user is invalid');
    if (typeof u.balance !== 'number' || !Number.isInteger(u.balance) || u.balance < 0 || u.balance > 2 ** 53) throw bad('user balance is invalid');
    if (!validHashFormat(u.password_hash)) throw bad('user password_hash is invalid');
    if (s.users.has(u.id) || s.byHandle.has(u.handle) || s.byEmail.has(u.email)) throw bad('duplicate user');
    addUser(s, pick(u, ['id', 'email', 'display_name', 'handle', 'balance', 'password_hash']));
  }
  for (const raw of arr(st, 'tokens')) {
    const t = obj(raw, 'token');
    if (!str(t.token) || t.token === '' || !s.users.has(t.user_id)) throw bad('token is invalid');
    s.tokens.set(t.token, t.user_id);
  }
  const common = (r, user1, user2, h1, h2) => {
    const a = s.users.get(r[user1]), b = s.users.get(r[user2]);
    if (!a || !b || a.handle !== r[h1] || b.handle !== r[h2]) throw bad('record references an unknown user');
    if (!int(r.amount) || r.amount < 0) throw bad('record amount is invalid');
    if (r.currency !== s.currency || !str(r.note)) throw bad('record is invalid');
    const ms = parseStamp(r.created_at);
    if (ms === null) throw bad('record created_at is invalid');
    return ms;
  };
  for (const raw of arr(st, 'payments')) {
    const p = obj(raw, 'payment');
    const ms = common(p, 'from_user_id', 'to_user_id', 'from_handle', 'to_handle');
    if (!id64(p.payment_id) || s.paymentById.has(p.payment_id)) throw bad('payment id is invalid');
    if (p.visibility !== 'public' && p.visibility !== 'private') throw bad('payment visibility is invalid');
    if (p.request_id !== null && !id64(p.request_id)) throw bad('payment request_id is invalid');
    if (p.settlement_id !== null && !id64(p.settlement_id)) throw bad('payment settlement_id is invalid');
    if (v1) p.authorization_id = null;
    else if (p.authorization_id !== null && !id64(p.authorization_id)) throw bad('payment authorization_id is invalid');
    const rec = { ...pick(p, PAYMENT_KEYS), ts: ms, seq: ++s.seq };
    s.paymentById.set(rec.payment_id, rec);
    insertOrdered(s.payments, rec);
  }
  for (const raw of arr(st, 'requests')) {
    const r = obj(raw, 'request');
    const ms = common(r, 'requester_id', 'payer_id', 'requester_handle', 'payer_handle');
    if (!id64(r.request_id) || s.requestById.has(r.request_id)) throw bad('request id is invalid');
    if (!['pending', 'paid', 'declined', 'cancelled'].includes(r.status)) throw bad('request status is invalid');
    if (r.payment_id !== null && !s.paymentById.has(r.payment_id)) throw bad('request references an unknown payment');
    const rec = { ...pick(r, REQUEST_KEYS), ts: ms, seq: ++s.seq };
    s.requestById.set(rec.request_id, rec);
    insertOrdered(s.requests, rec);
  }
  for (const p of s.payments) {
    if (p.request_id !== null && !s.requestById.has(p.request_id)) throw bad('payment references an unknown request');
  }
  for (const raw of arr(st, 'splits')) {
    const x = obj(raw, 'split');
    if (!id64(x.id) || !s.users.has(x.user_id) || !int(x.amount) || !str(x.note) || !str(x.created_at)) throw bad('split is invalid');
    if (!Array.isArray(x.shares) || !x.shares.every((h) => isObject(h) && str(h.handle) && int(h.amount))) throw bad('split shares are invalid');
    if (!Array.isArray(x.request_ids) || !x.request_ids.every((q) => s.requestById.has(q))) throw bad('split requests are invalid');
    s.splits.push({ id: x.id, user_id: x.user_id, amount: x.amount, note: x.note, shares: x.shares.map((h) => ({ handle: h.handle, amount: h.amount })), request_ids: [...x.request_ids], created_at: x.created_at });
  }
  if (!v1) {
    for (const raw of arr(st, 'authorizations')) {
      const a = obj(raw, 'authorization');
      const from = s.users.get(a.from_user_id), to = s.users.get(a.to_user_id);
      if (!id64(a.authorization_id) || s.authById.has(a.authorization_id)) throw bad('authorization id is invalid');
      if (!from || !to || from.handle !== a.from_handle || to.handle !== a.to_handle) throw bad('authorization references an unknown user');
      if (!int(a.amount) || a.amount < 1 || !int(a.captured_amount) || a.captured_amount < 0 || a.captured_amount > a.amount) throw bad('authorization amounts are invalid');
      if (a.currency !== s.currency || !str(a.note) || (a.visibility !== 'public' && a.visibility !== 'private')) throw bad('authorization is invalid');
      if (!['open', 'captured', 'voided', 'expired'].includes(a.status)) throw bad('authorization status is invalid');
      const exp = parseInstant(a.expires_at);
      const created = parseStamp(a.created_at);
      if (exp === null || created === null) throw bad('authorization timestamps are invalid');
      if (a.payment_id !== null && !id64(a.payment_id)) throw bad('authorization payment_id is invalid');
      if (!Array.isArray(a.payment_ids) || !a.payment_ids.every(id64)) throw bad('authorization payment_ids is invalid');
      if (a.voided_at !== undefined && a.voided_at !== null && parseInstant(a.voided_at) === null) throw bad('authorization voided_at is invalid');
      const rec = { ...pick(a, AUTH_KEYS), voided_at: a.voided_at ?? null, payment_ids: [...a.payment_ids], ts: created, seq: ++s.seq, exp };
      s.authById.set(rec.authorization_id, rec);
      insertOrdered(s.authorizations, rec);
      if (rec.status === 'open') s.openAuths.add(rec);
    }
    const held = new Map();
    for (const a of s.openAuths) held.set(a.from_user_id, (held.get(a.from_user_id) || 0) + a.amount - a.captured_amount);
    for (const [uid, h] of held) if (h > s.users.get(uid).balance) throw bad('open holds exceed a balance');
  }
  for (const raw of arr(st, 'settlements')) {
    const x = obj(raw, 'settlement');
    if (!id64(x.id) || !s.users.has(x.operator_id) || !str(x.committed_at)) throw bad('settlement is invalid');
    if (!Array.isArray(x.payment_ids) || !x.payment_ids.every((q) => s.paymentById.has(q))) throw bad('settlement payments are invalid');
    s.settlements.push({ id: x.id, operator_id: x.operator_id, committed_at: x.committed_at, payment_ids: [...x.payment_ids] });
  }
  for (const o of arr(st, 'settlement_operator_ids')) {
    if (!s.users.has(o)) throw bad('operator is not a user');
    s.operators.add(o);
  }
  for (const raw of arr(st, 'idempotency')) {
    const e = obj(raw, 'idempotency record');
    if (!s.users.has(e.user_id) || !str(e.method) || !str(e.path) || !str(e.key) || !str(e.body) || !str(e.response)) throw bad('idempotency record is invalid');
    if (e.status !== 201) throw bad('idempotency record is invalid');
    try { JSON.parse(e.response); JSON.parse(e.body); } catch { throw bad('idempotency record is invalid'); }
    s.idem.set(idemId(e.user_id, e.method, e.path, e.key), { user_id: e.user_id, method: e.method, path: e.path, key: e.key, body: e.body, status: 201, response: e.response });
  }
  const c = has(st, 'counters') ? obj(st.counters, 'counters') : {};
  for (const k of Object.keys(s.counters)) {
    if (has(c, k)) {
      if (!int(c[k]) || c[k] < 0) throw bad('counters are invalid');
      s.counters[k] = c[k];
    }
  }
  sweep(s);
  return s;
}
