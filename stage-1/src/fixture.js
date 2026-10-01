// POST /_test/reset: validate the whole fixture first, build a complete new state,
// and only then swap it in. Any error leaves the live state untouched.
import { emptyState, addUser, insertOrdered } from './state.js';
import { invalid } from './errors.js';
import { isObject, has } from './json.js';
import { hashPassword } from './passwords.js';
import { parseStamp, nowStamp } from './time.js';
import { HANDLE_RE, MAX_AMOUNT } from './validate.js';

const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];
const SEED_COST = 2048;

const str = (v) => typeof v === 'string';
const id64 = (v) => str(v) && v.length >= 1 && v.length <= 64;
const optArray = (fx, k) => {
  if (!has(fx, k) || fx[k] === null) return [];
  if (!Array.isArray(fx[k])) throw bad(`${k} must be an array`);
  return fx[k];
};

function bad(m) { return invalid(`fixture: ${m}`); }

function money(v, what, max = Number.MAX_SAFE_INTEGER) {
  if (typeof v !== 'number' || !Number.isInteger(v)) throw bad(`${what} must be an integer`);
  if (v < 0) throw bad(`${what} must not be negative`);
  if (v > max) throw bad(`${what} is too large`);
  return v === 0 ? 0 : v;
}

function stampOf(rec, reset) {
  if (!has(rec, 'created_at') || rec.created_at === null) return reset;
  const ms = parseStamp(rec.created_at);
  if (ms === null) throw bad('created_at must be an RFC 3339 timestamp');
  return { text: rec.created_at, ms };
}

export function validateFixture(fx) {
  if (!isObject(fx)) throw bad('body must be a JSON object');
  if (!str(fx.currency) || fx.currency === '') throw bad('currency must be a non-empty string');
  if (![0, 2, 3].includes(fx.minor_units)) throw bad('minor_units must be 0, 2 or 3');
  if (!Array.isArray(fx.users)) throw bad('users must be an array');
  const ids = new Set(), handles = new Set(), emails = new Set();
  let total = 0;
  const users = fx.users.map((u) => {
    if (!isObject(u)) throw bad('user must be an object');
    if (!id64(u.id)) throw bad('user id must be a string of 1 to 64 characters');
    if (!str(u.email) || u.email === '') throw bad('user email must be a string');
    if (!str(u.password)) throw bad('user password must be a string');
    if (!str(u.handle) || !HANDLE_RE.test(u.handle)) throw bad('user handle is invalid');
    if (has(u, 'display_name') && !str(u.display_name)) throw bad('display_name must be a string');
    const balance = has(u, 'balance') ? money(u.balance, 'balance') : 0;
    total += balance;
    if (total > Number.MAX_SAFE_INTEGER) throw bad('total balance is too large');
    if (ids.has(u.id)) throw bad('duplicate user id');
    if (handles.has(u.handle)) throw bad('duplicate handle');
    if (emails.has(u.email)) throw bad('duplicate email');
    ids.add(u.id); handles.add(u.handle); emails.add(u.email);
    return { id: u.id, email: u.email, password: u.password, handle: u.handle, display_name: has(u, 'display_name') ? u.display_name : u.handle, balance };
  });
  const payments = optArray(fx, 'payments').map((p) => {
    if (!isObject(p)) throw bad('payment must be an object');
    if (!id64(p.id)) throw bad('payment id must be a string of 1 to 64 characters');
    if (!ids.has(p.from_user_id) || !ids.has(p.to_user_id)) throw bad('payment references an unknown user');
    if (has(p, 'note') && !str(p.note)) throw bad('payment note must be a string');
    if (has(p, 'visibility') && p.visibility !== 'public' && p.visibility !== 'private') throw bad('payment visibility is invalid');
    if (has(p, 'request_id') && p.request_id !== null && !id64(p.request_id)) throw bad('payment request_id is invalid');
    return p;
  });
  const requests = optArray(fx, 'requests').map((r) => {
    if (!isObject(r)) throw bad('request must be an object');
    if (!id64(r.id)) throw bad('request id must be a string of 1 to 64 characters');
    if (!ids.has(r.requester_id) || !ids.has(r.payer_id)) throw bad('request references an unknown user');
    if (!STATUSES.includes(r.status)) throw bad('request status is invalid');
    if (has(r, 'note') && !str(r.note)) throw bad('request note must be a string');
    if (has(r, 'payment_id') && r.payment_id !== null && !id64(r.payment_id)) throw bad('request payment_id is invalid');
    return r;
  });
  const operators = optArray(fx, 'settlement_operator_ids');
  for (const o of operators) if (!ids.has(o)) throw bad('settlement operator is not a user');
  if (new Set(payments.map((p) => p.id)).size !== payments.length) throw bad('duplicate payment id');
  if (new Set(requests.map((r) => r.id)).size !== requests.length) throw bad('duplicate request id');
  const payIds = new Set(payments.map((p) => p.id)), reqIds = new Set(requests.map((r) => r.id));
  for (const p of payments) if (p.request_id != null && !reqIds.has(p.request_id)) throw bad('payment references an unknown request');
  for (const r of requests) if (r.payment_id != null && !payIds.has(r.payment_id)) throw bad('request references an unknown payment');
  return { fx, users, payments, requests, operators };
}

export async function buildState(raw) {
  const v = validateFixture(raw);
  const reset = nowStamp();
  // Stamps and amounts are checked before any hashing so errors stay cheap.
  const payRecs = v.payments.map((p) => ({ p, stamp: stampOf(p, reset), amount: money(p.amount, 'payment amount', MAX_AMOUNT) }));
  const reqRecs = v.requests.map((r) => ({ r, stamp: stampOf(r, reset), amount: money(r.amount, 'request amount', MAX_AMOUNT) }));
  const hashes = await Promise.all(v.users.map((u) => hashPassword(u.password, SEED_COST)));

  const s = emptyState();
  s.currency = v.fx.currency;
  s.minorUnits = v.fx.minor_units;
  v.users.forEach((u, i) => addUser(s, {
    id: u.id, email: u.email, display_name: u.display_name, handle: u.handle, balance: u.balance, password_hash: hashes[i],
  }));
  for (const { p, stamp, amount } of payRecs) {
    const from = s.users.get(p.from_user_id), to = s.users.get(p.to_user_id);
    const rec = {
      payment_id: p.id, from_user_id: from.id, from_handle: from.handle, to_user_id: to.id, to_handle: to.handle,
      amount, currency: s.currency, note: has(p, 'note') ? p.note : '', visibility: has(p, 'visibility') ? p.visibility : 'public',
      request_id: has(p, 'request_id') ? p.request_id : null, settlement_id: null,
      created_at: stamp.text, ts: stamp.ms, seq: ++s.seq,
    };
    s.paymentById.set(rec.payment_id, rec);
    insertOrdered(s.payments, rec);
  }
  for (const { r, stamp, amount } of reqRecs) {
    const a = s.users.get(r.requester_id), b = s.users.get(r.payer_id);
    const rec = {
      request_id: r.id, requester_id: a.id, requester_handle: a.handle, payer_id: b.id, payer_handle: b.handle,
      amount, currency: s.currency, note: has(r, 'note') ? r.note : '', status: r.status,
      payment_id: has(r, 'payment_id') ? r.payment_id : null, created_at: stamp.text, ts: stamp.ms, seq: ++s.seq,
    };
    s.requestById.set(rec.request_id, rec);
    insertOrdered(s.requests, rec);
  }
  for (const o of v.operators) s.operators.add(o);
  return s;
}
