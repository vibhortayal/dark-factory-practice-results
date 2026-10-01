// POST /_test/reset: validate the whole fixture first, build a complete new state,
// and only then swap it in. Any error leaves the live state untouched.
import { emptyState, addUser, insertOrdered, sweep } from './state.js';
import { invalid } from './errors.js';
import { isObject, has } from './json.js';
import { hashPassword } from './passwords.js';
import { parseStamp, parseInstant, nowStamp, stampAt } from './time.js';
import { parseInstantNs, msToNs } from './instants.js';
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

const MAX_BALANCE = 2 ** 53; // spec: no balance outside +-2^53
function money(v, what, max = MAX_BALANCE) {
  if (typeof v !== 'number' || !Number.isInteger(v)) throw bad(`${what} must be an integer`);
  if (v < 0) throw bad(`${what} must not be negative`);
  if (v > max) throw bad(`${what} is too large`);
  return v === 0 ? 0 : v;
}

const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];

function checkAuthorization(a, userIds) {
  if (!isObject(a)) throw bad('authorization must be an object');
  if (!id64(a.id)) throw bad('authorization id must be a string of 1 to 64 characters');
  if (!userIds.has(a.from_user_id) || !userIds.has(a.to_user_id)) throw bad('authorization references an unknown user');
  if (a.from_user_id === a.to_user_id) throw bad('authorization must be between two different users');
  const amount = money(a.amount, 'authorization amount', MAX_AMOUNT);
  if (amount < 1) throw bad('authorization amount must be at least 1');
  if (!AUTH_STATUSES.includes(a.status)) throw bad('authorization status is invalid');
  if (has(a, 'note') && !str(a.note)) throw bad('authorization note must be a string');
  if (has(a, 'visibility') && a.visibility !== 'public' && a.visibility !== 'private') throw bad('authorization visibility is invalid');
  let exp = null;
  if (has(a, 'expires_at') && a.expires_at !== null) {
    exp = parseInstant(a.expires_at);
    if (exp === null) throw bad('authorization expires_at must be an RFC 3339 timestamp');
  } else if (a.status === 'open') throw bad('an open authorization needs expires_at');
  let captured = a.status === 'captured' ? amount : 0;
  if (has(a, 'captured_amount') && a.captured_amount !== null) captured = money(a.captured_amount, 'captured_amount', amount);
  let paymentIds = null;
  if (has(a, 'payment_ids') && a.payment_ids !== null) {
    if (!Array.isArray(a.payment_ids) || !a.payment_ids.every(id64)) throw bad('authorization payment_ids is invalid');
    paymentIds = a.payment_ids;
  }
  if (has(a, 'payment_id') && a.payment_id !== null && !id64(a.payment_id)) throw bad('authorization payment_id is invalid');
  const paymentId = has(a, 'payment_id') ? a.payment_id : null;
  if (paymentIds === null) paymentIds = paymentId === null ? [] : [paymentId];
  if (a.status === 'open' && captured >= amount) throw bad('an open authorization must have an uncaptured remainder');
  return { raw: a, id: a.id, from_user_id: a.from_user_id, to_user_id: a.to_user_id, amount, captured, status: a.status, exp, paymentId: paymentId ?? (paymentIds.length ? paymentIds[paymentIds.length - 1] : null), paymentIds };
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
  const users = fx.users.map((u) => {
    if (!isObject(u)) throw bad('user must be an object');
    if (!id64(u.id)) throw bad('user id must be a string of 1 to 64 characters');
    if (!str(u.email) || u.email === '') throw bad('user email must be a string');
    if (!str(u.password)) throw bad('user password must be a string');
    if (!str(u.handle) || !HANDLE_RE.test(u.handle)) throw bad('user handle is invalid');
    if (has(u, 'display_name') && !str(u.display_name)) throw bad('display_name must be a string');
    const balance = has(u, 'balance') ? money(u.balance, 'balance') : 0;
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
  const authorizations = optArray(fx, 'authorizations').map((a) => checkAuthorization(a, ids));
  if (new Set(authorizations.map((a) => a.id)).size !== authorizations.length) throw bad('duplicate authorization id');
  const held = new Map();
  const now = Date.now();
  for (const a of authorizations) {
    if (a.status === 'open' && a.exp > now) held.set(a.from_user_id, (held.get(a.from_user_id) || 0) + a.amount - a.captured);
  }
  for (const u of users) if ((held.get(u.id) || 0) > u.balance) throw bad('open holds exceed the balance');
  let ttl = 600;
  if (has(fx, 'authorization_ttl_seconds')) {
    ttl = fx.authorization_ttl_seconds;
    if (typeof ttl !== 'number' || !Number.isInteger(ttl) || ttl < 1) throw bad('authorization_ttl_seconds must be a positive integer');
  }
  const operators = optArray(fx, 'settlement_operator_ids');
  for (const o of operators) if (!ids.has(o)) throw bad('settlement operator is not a user');
  if (new Set(payments.map((p) => p.id)).size !== payments.length) throw bad('duplicate payment id');
  if (new Set(requests.map((r) => r.id)).size !== requests.length) throw bad('duplicate request id');
  const payIds = new Set(payments.map((p) => p.id)), reqIds = new Set(requests.map((r) => r.id));
  for (const p of payments) if (p.request_id != null && !reqIds.has(p.request_id)) throw bad('payment references an unknown request');
  for (const r of requests) if (r.payment_id != null && !payIds.has(r.payment_id)) throw bad('request references an unknown payment');
  return { fx, users, payments, requests, operators, authorizations, ttl };
}

export async function buildState(raw) {
  const v = validateFixture(raw);
  const reset = nowStamp();
  // Stamps and amounts are checked before any hashing so errors stay cheap.
  const resetNs = msToNs(reset.ms);
  const payRecs = v.payments.map((p) => {
    // A seeded created_at is the payment's original effective and recorded instant: exact, with an offset, never in the future.
    let ns = resetNs;
    let stamp = reset;
    if (has(p, 'created_at') && p.created_at !== null) {
      ns = parseInstantNs(p.created_at);
      if (ns === null) throw bad('payment created_at must be an RFC 3339 instant with an offset');
      if (ns > resetNs + 999999n) throw bad('payment created_at must not be in the future'); // end of the current millisecond
      stamp = { text: p.created_at, ms: Number(ns / 1000000n) };
    }
    return { p, stamp, ns, amount: money(p.amount, 'payment amount', MAX_AMOUNT) };
  });
  const reqRecs = v.requests.map((r) => ({ r, stamp: stampOf(r, reset), amount: money(r.amount, 'request amount', MAX_AMOUNT) }));
  const authRecs = v.authorizations.map((a) => ({ a, stamp: stampOf(a.raw, nowStamp()) }));
  const hashes = await Promise.all(v.users.map((u) => hashPassword(u.password, SEED_COST)));

  const s = emptyState();
  s.currency = v.fx.currency;
  s.minorUnits = v.fx.minor_units;
  v.users.forEach((u, i) => addUser(s, {
    id: u.id, email: u.email, display_name: u.display_name, handle: u.handle, balance: u.balance, opening: u.balance, password_hash: hashes[i],
  }));
  s.lastMs = reset.ms;
  s.floorMs = reset.ms + 1; // records created after the reset are strictly later than reset-time records
  for (const { p, stamp, ns, amount } of payRecs) {
    const from = s.users.get(p.from_user_id), to = s.users.get(p.to_user_id);
    const rec = {
      payment_id: p.id, from_user_id: from.id, from_handle: from.handle, to_user_id: to.id, to_handle: to.handle,
      amount, currency: s.currency, note: has(p, 'note') ? p.note : '', visibility: has(p, 'visibility') ? p.visibility : 'public',
      request_id: has(p, 'request_id') ? p.request_id : null, settlement_id: null,
      authorization_id: has(p, 'authorization_id') && str(p.authorization_id) ? p.authorization_id : null,
      created_at: stamp.text, ts: ns, seq: ++s.seq,
    };
    rec.revisions = [{ revision: 1, amount, effective_at: stamp.text, eff: ns, recorded_at: stamp.text, rec: ns, reason: '', kseq: ++s.kseq }];
    // Opening balance: the seeded ending balance minus the net effect of the original seeded payments.
    from.opening += amount;
    to.opening -= amount;
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
  s.authTtl = v.ttl;
  for (const { a, stamp } of authRecs) {
    const from = s.users.get(a.from_user_id), to = s.users.get(a.to_user_id);
    const expText = a.exp === null ? stampAt(stamp.ms + v.ttl * 1000) : null;
    const rec = {
      authorization_id: a.id, from_user_id: from.id, from_handle: from.handle, to_user_id: to.id, to_handle: to.handle,
      amount: a.amount, captured_amount: a.captured, currency: s.currency,
      note: has(a.raw, 'note') ? a.raw.note : '', visibility: has(a.raw, 'visibility') ? a.raw.visibility : 'public',
      status: a.status, expires_at: expText ? expText.text : a.raw.expires_at,
      payment_id: a.paymentId, payment_ids: [...a.paymentIds],
      created_at: stamp.text, ts: stamp.ms, seq: ++s.seq, voided_at: null,
      closed_at: null, voidNs: null, voidKseq: null, kseq: ++s.kseq,
      createdNs: parseInstantNs(stamp.text) ?? msToNs(stamp.ms),
      expNs: parseInstantNs(expText ? expText.text : a.raw.expires_at) ?? msToNs(a.exp),
      seededClosed: a.status !== 'open',
    };
    const resolvable = rec.payment_ids.map((id) => s.paymentById.get(id)).filter(Boolean);
    rec.initialCaptured = Math.max(0, rec.captured_amount - resolvable.reduce((sum, p) => sum + p.revisions[0].amount, 0));
    if (rec.status === 'captured' || rec.status === 'voided') rec.closed_at = has(a.raw, 'closed_at') && str(a.raw.closed_at) ? a.raw.closed_at : reset.text;
    else if (rec.status === 'expired') rec.closed_at = has(a.raw, 'closed_at') && str(a.raw.closed_at) ? a.raw.closed_at : rec.expires_at;
    s.authById.set(rec.authorization_id, rec);
    insertOrdered(s.authorizations, rec);
    if (rec.status === 'open') s.openAuths.add(rec);
  }
  sweep(s);
  for (const o of v.operators) s.operators.add(o);
  return s;
}
