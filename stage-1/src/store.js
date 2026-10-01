'use strict';
const crypto = require('crypto');
const { err, isObject, HANDLE_RE } = require('./util');

const SCRYPT = { N: 2048, r: 8, p: 1 };
const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];

function emptyState() {
  return {
    currency: 'EUR',
    minorUnits: 2,
    users: new Map(),        // id -> user
    emailIndex: new Map(),   // email -> user
    handleIndex: new Map(),  // handle -> user
    tokens: new Map(),       // token -> user id
    payments: [],            // insertion order
    paymentIndex: new Map(),
    requests: [],
    requestIndex: new Map(),
    splits: [],
    settlements: [],
    idem: new Map(),         // JSON [userId, path, key] -> record
    operators: new Set(),
    seq: 0,
    seededTotal: 0n,       // BigInt: the sum of seeded balances may exceed 2^53
    counters: { p: 0, rq: 0, sp: 0, st: 0, u: 0 },
  };
}

// The live state. Handlers run synchronously between awaits, so every state change is atomic.
const store = { s: emptyState() };

function nextId(s, prefix, taken) {
  let id;
  do { id = prefix + '_' + (++s.counters[prefix]); } while (taken(id));
  return id;
}

function hashPassword(password) {
  return new Promise((resolve, reject) => {
    const salt = crypto.randomBytes(16);
    crypto.scrypt(password, salt, 32, SCRYPT, (e, key) => {
      if (e) reject(e);
      else resolve({ salt: salt.toString('hex'), hash: key.toString('hex') });
    });
  });
}

function verifyPassword(password, stored) {
  return new Promise((resolve, reject) => {
    crypto.scrypt(password, Buffer.from(stored.salt, 'hex'), 32, SCRYPT, (e, key) => {
      if (e) return reject(e);
      const want = Buffer.from(stored.hash, 'hex');
      resolve(want.length === key.length && crypto.timingSafeEqual(want, key));
    });
  });
}

function isInt(v) {
  return typeof v === 'number' && Number.isSafeInteger(v);
}

function addUser(s, u) {
  s.users.set(u.id, u);
  s.emailIndex.set(u.email, u);
  s.handleIndex.set(u.handle, u);
}

function fixtureError(m) {
  return err.validation('fixture: ' + m);
}

// Builds a complete new state from a reset fixture. Throws 422 without touching the live state.
async function buildFromFixture(fx) {
  const s = emptyState();
  const currency = fx.currency === undefined ? 'EUR' : fx.currency;
  const minorUnits = fx.minor_units === undefined ? 2 : fx.minor_units;
  if (typeof currency !== 'string' || currency === '') throw fixtureError('currency must be a string');
  if (![0, 2, 3].includes(minorUnits)) throw fixtureError('minor_units must be 0, 2 or 3');
  s.currency = currency;
  s.minorUnits = minorUnits;

  const users = fx.users === undefined ? [] : fx.users;
  if (!Array.isArray(users)) throw fixtureError('users must be an array');
  const pending = [];
  for (const u of users) {
    if (!isObject(u)) throw fixtureError('user must be an object');
    for (const f of ['id', 'email', 'password', 'handle']) {
      if (typeof u[f] !== 'string' || u[f] === '') throw fixtureError('user ' + f + ' must be a non-empty string');
    }
    if (u.id.length > 64) throw fixtureError('user id too long');
    if (!HANDLE_RE.test(u.handle)) throw fixtureError('invalid handle ' + u.handle);
    const balance = u.balance === undefined ? 0 : u.balance;
    if (!isInt(balance) || balance < 0) throw fixtureError('balance must be a non-negative integer');
    if (u.display_name !== undefined && typeof u.display_name !== 'string') throw fixtureError('display_name must be a string');
    if (s.users.has(u.id) || s.emailIndex.has(u.email) || s.handleIndex.has(u.handle)) {
      throw fixtureError('duplicate user id, email or handle');
    }
    const user = { id: u.id, email: u.email, display_name: u.display_name === undefined ? u.handle : u.display_name,
      handle: u.handle, balance, password: null };
    addUser(s, user);
    pending.push([user, u.password]);
    s.seededTotal += BigInt(balance);
  }
  await Promise.all(pending.map(async ([user, pw]) => { user.password = await hashPassword(pw); }));

  const now = Date.now();
  const payments = fx.payments === undefined ? [] : fx.payments;
  const requests = fx.requests === undefined ? [] : fx.requests;
  if (!Array.isArray(payments) || !Array.isArray(requests)) throw fixtureError('payments and requests must be arrays');

  const ts = (v) => {
    if (typeof v === 'string') { const t = Date.parse(v); if (Number.isFinite(t)) return t; }
    return now;
  };
  for (const p of payments) {
    if (!isObject(p)) throw fixtureError('payment must be an object');
    if (typeof p.id !== 'string' || p.id === '' || p.id.length > 64) throw fixtureError('payment id');
    if (!s.users.has(p.from_user_id) || !s.users.has(p.to_user_id)) throw fixtureError('payment references unknown user');
    if (!isInt(p.amount) || p.amount < 0) throw fixtureError('payment amount');
    const visibility = p.visibility === undefined ? 'public' : p.visibility;
    if (visibility !== 'public' && visibility !== 'private') throw fixtureError('payment visibility');
    const note = p.note === undefined || p.note === null ? '' : p.note;
    if (typeof note !== 'string') throw fixtureError('payment note');
    if (s.paymentIndex.has(p.id)) throw fixtureError('duplicate payment id');
    const rec = { id: p.id, from: p.from_user_id, to: p.to_user_id, amount: p.amount, note, visibility,
      request_id: typeof p.request_id === 'string' ? p.request_id : null,
      settlement_id: null, ts: ts(p.created_at), seq: s.seq++ };
    s.payments.push(rec);
    s.paymentIndex.set(rec.id, rec);
  }
  for (const r of requests) {
    if (!isObject(r)) throw fixtureError('request must be an object');
    if (typeof r.id !== 'string' || r.id === '' || r.id.length > 64) throw fixtureError('request id');
    if (!s.users.has(r.requester_id) || !s.users.has(r.payer_id)) throw fixtureError('request references unknown user');
    if (r.requester_id === r.payer_id) throw fixtureError('request to self');
    if (!isInt(r.amount) || r.amount < 0) throw fixtureError('request amount');
    const status = r.status === undefined ? 'pending' : r.status;
    if (!STATUSES.includes(status)) throw fixtureError('request status');
    const note = r.note === undefined || r.note === null ? '' : r.note;
    if (typeof note !== 'string') throw fixtureError('request note');
    if (s.requestIndex.has(r.id)) throw fixtureError('duplicate request id');
    const rec = { id: r.id, requester: r.requester_id, payer: r.payer_id, amount: r.amount, note, status,
      payment_id: typeof r.payment_id === 'string' ? r.payment_id : null, ts: ts(r.created_at), seq: s.seq++ };
    s.requests.push(rec);
    s.requestIndex.set(rec.id, rec);
  }
  const ops = fx.settlement_operator_ids === undefined ? [] : fx.settlement_operator_ids;
  if (!Array.isArray(ops) || ops.some((o) => typeof o !== 'string')) throw fixtureError('settlement_operator_ids must be an array of strings');
  for (const o of ops) if (s.users.has(o)) s.operators.add(o);
  return s;
}

// ---- export / import ----

function serialize(s) {
  return {
    currency: s.currency,
    minor_units: s.minorUnits,
    seq: s.seq,
    seeded_total: s.seededTotal.toString(),
    counters: s.counters,
    users: [...s.users.values()],
    tokens: [...s.tokens.entries()],
    payments: s.payments,
    requests: s.requests,
    splits: s.splits,
    settlements: s.settlements,
    idempotency: [...s.idem.values()],
    operators: [...s.operators],
  };
}

function bad(m) {
  return err.validation('state: ' + m);
}

function str(v, what, nonEmpty = true) {
  if (typeof v !== 'string' || (nonEmpty && v === '')) throw bad(what + ' must be a string');
  return v;
}

function nint(v, what) {
  if (!isInt(v) || v < 0) throw bad(what + ' must be a non-negative integer');
  return v;
}

function arr(v, what) {
  if (!Array.isArray(v)) throw bad(what + ' must be an array');
  return v;
}

function hex(v, what) {
  if (typeof v !== 'string' || !/^[0-9a-f]+$/.test(v)) throw bad(what + ' must be hex');
  return v;
}

function nullableStr(v, what) {
  if (v === null) return null;
  return str(v, what);
}

// Validates an exported state and builds a live state from it. Throws 422 on anything invalid.
function deserialize(st) {
  if (!isObject(st)) throw bad('must be an object');
  const s = emptyState();
  s.currency = str(st.currency, 'currency');
  if (![0, 2, 3].includes(st.minor_units)) throw bad('minor_units');
  s.minorUnits = st.minor_units;
  s.seq = nint(st.seq, 'seq');
  if (typeof st.seeded_total !== 'string' || !/^[0-9]+$/.test(st.seeded_total)) throw bad('seeded_total');
  s.seededTotal = BigInt(st.seeded_total);
  if (!isObject(st.counters)) throw bad('counters');
  for (const k of Object.keys(s.counters)) s.counters[k] = nint(st.counters[k], 'counter ' + k);

  let total = 0n;
  for (const u of arr(st.users, 'users')) {
    if (!isObject(u)) throw bad('user');
    const user = { id: str(u.id, 'user id'), email: str(u.email, 'email'), display_name: str(u.display_name, 'display_name', false),
      handle: str(u.handle, 'handle'), balance: nint(u.balance, 'balance'),
      password: isObject(u.password) ? { salt: hex(u.password.salt, 'salt'), hash: hex(u.password.hash, 'hash') } : null };
    if (!user.password) throw bad('password');
    if (!HANDLE_RE.test(user.handle)) throw bad('handle');
    if (s.users.has(user.id) || s.emailIndex.has(user.email) || s.handleIndex.has(user.handle)) throw bad('duplicate user');
    addUser(s, user);
    total += BigInt(user.balance);
  }
  if (total !== s.seededTotal) throw bad('balances do not sum to seeded_total');

  for (const t of arr(st.tokens, 'tokens')) {
    if (!Array.isArray(t) || t.length !== 2) throw bad('token entry');
    str(t[0], 'token');
    if (!s.users.has(str(t[1], 'token user')) || s.tokens.has(t[0])) throw bad('token');
    s.tokens.set(t[0], t[1]);
  }
  for (const p of arr(st.payments, 'payments')) {
    if (!isObject(p)) throw bad('payment');
    const rec = { id: str(p.id, 'payment id'), from: str(p.from, 'from'), to: str(p.to, 'to'), amount: nint(p.amount, 'amount'),
      note: str(p.note, 'note', false), visibility: p.visibility, request_id: nullableStr(p.request_id, 'request_id'),
      settlement_id: nullableStr(p.settlement_id, 'settlement_id'), ts: nint(p.ts, 'ts'), seq: nint(p.seq, 'seq') };
    if (rec.visibility !== 'public' && rec.visibility !== 'private') throw bad('visibility');
    if (!s.users.has(rec.from) || !s.users.has(rec.to) || s.paymentIndex.has(rec.id)) throw bad('payment reference');
    s.payments.push(rec);
    s.paymentIndex.set(rec.id, rec);
  }
  for (const r of arr(st.requests, 'requests')) {
    if (!isObject(r)) throw bad('request');
    const rec = { id: str(r.id, 'request id'), requester: str(r.requester, 'requester'), payer: str(r.payer, 'payer'),
      amount: nint(r.amount, 'amount'), note: str(r.note, 'note', false), status: r.status,
      payment_id: nullableStr(r.payment_id, 'payment_id'), ts: nint(r.ts, 'ts'), seq: nint(r.seq, 'seq') };
    if (!STATUSES.includes(rec.status)) throw bad('status');
    if (!s.users.has(rec.requester) || !s.users.has(rec.payer) || s.requestIndex.has(rec.id)) throw bad('request reference');
    s.requests.push(rec);
    s.requestIndex.set(rec.id, rec);
  }
  for (const sp of arr(st.splits, 'splits')) {
    if (!isObject(sp)) throw bad('split');
    s.splits.push({ id: str(sp.id, 'split id'), requester: str(sp.requester, 'requester'), amount: nint(sp.amount, 'amount'),
      note: str(sp.note, 'note', false), shares: arr(sp.shares, 'shares').map((x) => ({ handle: str(isObject(x) ? x.handle : undefined, 'share handle'), amount: nint(isObject(x) ? x.amount : undefined, 'share') })),
      request_ids: arr(sp.request_ids, 'request_ids').map((x) => str(x, 'request id')), ts: nint(sp.ts, 'ts') });
  }
  for (const m of arr(st.settlements, 'settlements')) {
    if (!isObject(m)) throw bad('settlement');
    s.settlements.push({ id: str(m.id, 'settlement id'), operator: str(m.operator, 'operator'), ts: nint(m.ts, 'ts'),
      payment_ids: arr(m.payment_ids, 'payment_ids').map((x) => str(x, 'payment id')) });
  }
  for (const rec of arr(st.idempotency, 'idempotency')) {
    if (!isObject(rec)) throw bad('idempotency record');
    const r = { user_id: str(rec.user_id, 'user_id'), method: str(rec.method, 'method'), path: str(rec.path, 'path'),
      key: str(rec.key, 'key'), body: str(rec.body, 'body', false), response: str(rec.response, 'response', false) };
    try { JSON.parse(r.response); } catch (e) { throw bad('idempotency response'); }
    s.idem.set(JSON.stringify([r.user_id, r.path, r.key]), r);
  }
  for (const o of arr(st.operators, 'operators')) {
    if (!s.users.has(str(o, 'operator'))) throw bad('operator');
    s.operators.add(o);
  }
  return s;
}

module.exports = { store, emptyState, nextId, hashPassword, verifyPassword, buildFromFixture, serialize, deserialize };
