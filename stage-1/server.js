'use strict';
// Pocketful stage 1. Single process, in-memory state. Every handler is
// synchronous once the body has been read, so each request is one atomic step.
const http = require('http');
const crypto = require('crypto');

const MAX_AMOUNT = 1000000000;
const MAX_EXACT = 9007199254740992; // 2^53
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];
const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

class ApiError extends Error {
  constructor(status, code, message) { super(message || code); this.status = status; this.code = code; }
}
const E = (status, code, msg) => new ApiError(status, code, msg);
const bad = (msg) => E(422, 'validation_failed', msg);
const malformed = (msg) => E(400, 'malformed_request', msg);

// ---------------------------------------------------------------- helpers
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const nowStr = () => new Date().toISOString().slice(0, 19) + '+00:00';
const tsOf = (s) => { const t = Date.parse(s); return Number.isNaN(t) ? 0 : t; };
const validAmount = (v) => typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= MAX_AMOUNT;

function cpLen(s) {
  if (s.length > 400) return s.length; // > 200 code points for sure
  let n = 0;
  for (const _ of s) n++; // eslint-disable-line no-unused-vars
  return n;
}

function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (isObj(v)) return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  return JSON.stringify(v);
}

const SCRYPT = { N: 1024, r: 8, p: 1 };
function hashPw(pw) {
  const salt = crypto.randomBytes(16);
  return { s: salt.toString('hex'), h: crypto.scryptSync(pw, salt, 32, SCRYPT).toString('hex') };
}
function checkPw(pw, rec) {
  const h = crypto.scryptSync(pw, Buffer.from(rec.s, 'hex'), 32, SCRYPT);
  const want = Buffer.from(rec.h, 'hex');
  return want.length === h.length && crypto.timingSafeEqual(h, want);
}

// ---------------------------------------------------------------- state
let S = emptyState();

function emptyState() {
  return {
    currency: 'EUR', minorUnits: 2,
    users: new Map(), handles: new Map(), emails: new Map(), tokens: new Map(),
    payments: new Map(), requests: new Map(), usedIds: { sp: new Set(), st: new Set() },
    idem: new Map(), operators: new Set(),
    seq: 0, ctr: { u: 0, p: 0, rq: 0, sp: 0, st: 0 },
  };
}

function newId(prefix, exists) {
  for (;;) {
    S.ctr[prefix]++;
    const id = prefix + '_' + S.ctr[prefix];
    if (!exists(id)) return id;
  }
}

// ---------------------------------------------------------------- fixture / import
class Invalid extends Error {}
const need = (c, m) => { if (!c) throw new Invalid(m || 'invalid'); };
const str = (v, m) => { need(typeof v === 'string', m); return v; };
const intv = (v, m, min = 0) => { need(typeof v === 'number' && Number.isInteger(v) && v >= min && v <= MAX_EXACT, m); return v; };

function addUser(st, u) {
  need(!st.users.has(u.id), 'duplicate user id');
  need(!st.emails.has(u.email), 'duplicate email');
  need(!st.handles.has(u.handle), 'duplicate handle');
  st.users.set(u.id, u);
  st.emails.set(u.email, u);
  st.handles.set(u.handle, u);
}

function addPayment(st, p) {
  need(!st.payments.has(p.id), 'duplicate payment id');
  need(st.users.has(p.from) && st.users.has(p.to), 'unknown user in payment');
  need(p.from !== p.to, 'self payment');
  need(p.visibility === 'public' || p.visibility === 'private', 'visibility');
  need(typeof p.note === 'string', 'note');
  p.ts = tsOf(p.created_at);
  st.payments.set(p.id, p);
}

function addRequest(st, r) {
  need(!st.requests.has(r.id), 'duplicate request id');
  need(st.users.has(r.requester) && st.users.has(r.payer), 'unknown user in request');
  need(r.requester !== r.payer, 'self request');
  need(STATUSES.includes(r.status), 'status');
  need(typeof r.note === 'string', 'note');
  need(r.payment_id === null || typeof r.payment_id === 'string', 'payment_id');
  r.ts = tsOf(r.created_at);
  st.requests.set(r.id, r);
}

function buildFromFixture(f) {
  need(isObj(f), 'fixture must be an object');
  const st = emptyState();
  st.currency = str(f.currency, 'currency');
  need(f.currency.length > 0, 'currency');
  need([0, 2, 3].includes(f.minor_units), 'minor_units');
  st.minorUnits = f.minor_units;
  need(Array.isArray(f.users), 'users');
  const payments = f.payments === undefined ? [] : f.payments;
  const requests = f.requests === undefined ? [] : f.requests;
  need(Array.isArray(payments) && Array.isArray(requests), 'payments/requests');
  const ops = f.settlement_operator_ids === undefined ? [] : f.settlement_operator_ids;
  need(Array.isArray(ops), 'settlement_operator_ids');
  const created = nowStr();
  for (const u of f.users) {
    need(isObj(u), 'user');
    need(typeof u.handle === 'string' && HANDLE_RE.test(u.handle), 'handle');
    need(typeof u.password === 'string', 'password');
    const rec = {
      id: str(u.id, 'user id'), email: str(u.email, 'email'),
      display_name: u.display_name === undefined ? u.handle : str(u.display_name, 'display_name'),
      handle: u.handle, balance: intv(u.balance, 'balance'), pw: hashPw(u.password),
    };
    addUser(st, rec);
  }
  for (const p of payments) {
    need(isObj(p), 'payment');
    addPayment(st, fixPay(st, p, intv(p.amount, 'amount'), created));
  }
  for (const r of requests) {
    need(isObj(r), 'request');
    const rec = {
      id: r.id === undefined ? null : str(r.id), requester: str(r.requester_id), payer: str(r.payer_id),
      amount: intv(r.amount, 'amount'), note: r.note === undefined ? '' : r.note,
      status: r.status === undefined ? 'pending' : r.status,
      payment_id: r.payment_id == null ? null : r.payment_id,
      created_at: r.created_at === undefined ? created : str(r.created_at), seq: ++st.seq,
    };
    if (rec.id === null) { st.ctr.rq++; rec.id = 'rq_' + st.ctr.rq; while (st.requests.has(rec.id)) { st.ctr.rq++; rec.id = 'rq_' + st.ctr.rq; } }
    addRequest(st, rec);
  }
  for (const id of ops) {
    need(typeof id === 'string' && st.users.has(id), 'unknown operator');
    st.operators.add(id);
  }
  return st;
}

function fixPay(st, p, amount, created) {
  const rec = {
    id: p.id === undefined ? null : str(p.id, 'payment id'),
    from: str(p.from_user_id), to: str(p.to_user_id), amount,
    note: p.note === undefined ? '' : p.note,
    visibility: p.visibility === undefined ? 'public' : p.visibility,
    request_id: p.request_id == null ? null : str(p.request_id),
    settlement_id: p.settlement_id == null ? null : str(p.settlement_id),
    created_at: p.created_at === undefined ? created : str(p.created_at),
    seq: ++st.seq,
  };
  if (rec.id === null) { do { st.ctr.p++; rec.id = 'p_' + st.ctr.p; } while (st.payments.has(rec.id)); }
  return rec;
}

function exportState() {
  const strip = (r) => { const c = Object.assign({}, r); delete c.ts; return c; };
  return {
    currency: S.currency, minor_units: S.minorUnits,
    users: [...S.users.values()],
    tokens: [...S.tokens].map(([token, user_id]) => ({ token, user_id })),
    payments: [...S.payments.values()].map(strip),
    requests: [...S.requests.values()].map(strip),
    operators: [...S.operators],
    idempotency: [...S.idem].map(([k, v]) => ({ k, canon: v.canon, text: v.text })),
    used_ids: { sp: [...S.usedIds.sp], st: [...S.usedIds.st] },
    seq: S.seq, counters: S.ctr,
  };
}

function buildFromState(x) {
  need(isObj(x), 'state');
  const st = emptyState();
  st.currency = str(x.currency);
  need([0, 2, 3].includes(x.minor_units), 'minor_units');
  st.minorUnits = x.minor_units;
  for (const k of ['users', 'tokens', 'payments', 'requests', 'operators', 'idempotency']) need(Array.isArray(x[k]), k);
  need(isObj(x.counters) && isObj(x.used_ids), 'counters');
  for (const k of ['u', 'p', 'rq', 'sp', 'st']) st.ctr[k] = intv(x.counters[k], 'counter');
  st.seq = intv(x.seq, 'seq');
  need(Array.isArray(x.used_ids.sp) && Array.isArray(x.used_ids.st), 'used_ids');
  for (const id of x.used_ids.sp) st.usedIds.sp.add(str(id));
  for (const id of x.used_ids.st) st.usedIds.st.add(str(id));
  for (const u of x.users) {
    need(isObj(u) && isObj(u.pw), 'user');
    need(typeof u.handle === 'string' && HANDLE_RE.test(u.handle), 'handle');
    addUser(st, {
      id: str(u.id), email: str(u.email), display_name: str(u.display_name), handle: u.handle,
      balance: intv(u.balance, 'balance'),
      pw: { s: str(u.pw.s), h: str(u.pw.h) },
    });
  }
  for (const t of x.tokens) {
    need(isObj(t) && typeof t.token === 'string' && st.users.has(t.user_id), 'token');
    st.tokens.set(t.token, t.user_id);
  }
  for (const p of x.payments) {
    need(isObj(p), 'payment');
    addPayment(st, {
      id: str(p.id), from: str(p.from), to: str(p.to), amount: intv(p.amount, 'amount'),
      note: p.note, visibility: p.visibility,
      request_id: p.request_id === null ? null : str(p.request_id),
      settlement_id: p.settlement_id === null ? null : str(p.settlement_id),
      created_at: str(p.created_at), seq: intv(p.seq),
    });
  }
  for (const r of x.requests) {
    need(isObj(r), 'request');
    addRequest(st, {
      id: str(r.id), requester: str(r.requester), payer: str(r.payer), amount: intv(r.amount, 'amount'),
      note: r.note, status: r.status, payment_id: r.payment_id,
      created_at: str(r.created_at), seq: intv(r.seq),
    });
  }
  for (const id of x.operators) { need(typeof id === 'string' && st.users.has(id), 'operator'); st.operators.add(id); }
  for (const i of x.idempotency) {
    need(isObj(i) && typeof i.k === 'string' && typeof i.canon === 'string' && typeof i.text === 'string', 'idempotency');
    st.idem.set(i.k, { canon: i.canon, text: i.text });
  }
  return st;
}

// ---------------------------------------------------------------- views
function paymentView(p) {
  const f = S.users.get(p.from), t = S.users.get(p.to);
  return {
    payment_id: p.id, from_user_id: p.from, from_handle: f.handle, to_user_id: p.to, to_handle: t.handle,
    amount: p.amount, currency: S.currency, note: p.note, visibility: p.visibility,
    request_id: p.request_id, settlement_id: p.settlement_id, created_at: p.created_at,
  };
}
function requestView(r) {
  return {
    request_id: r.id, requester_id: r.requester, requester_handle: S.users.get(r.requester).handle,
    payer_id: r.payer, payer_handle: S.users.get(r.payer).handle, amount: r.amount, currency: S.currency,
    note: r.note, status: r.status, payment_id: r.payment_id, created_at: r.created_at,
  };
}
const newestFirst = (a, b) => (b.ts - a.ts) || (b.seq - a.seq);

// ---------------------------------------------------------------- field rules
function optNote(body) {
  if (!hasOwn(body, 'note')) return '';
  const n = body.note;
  if (typeof n !== 'string' || cpLen(n) > 200) throw bad('note');
  return n;
}
function optVisibility(body) {
  if (!hasOwn(body, 'visibility')) return 'public';
  const v = body.visibility;
  if (v !== 'public' && v !== 'private') throw bad('visibility');
  return v;
}
function handleField(body, name) {
  if (!hasOwn(body, name)) throw bad(name + ' is required');
  if (typeof body[name] !== 'string') throw malformed(name + ' must be a string');
  return body[name];
}
function userByHandle(h) {
  const u = S.handles.get(h);
  if (!u) throw E(404, 'not_found', 'no such handle');
  return u;
}

function movePayment(from, to, amount, note, visibility, requestId, settlementId, createdAt) {
  from.balance -= amount;
  to.balance += amount;
  const id = newId('p', (i) => S.payments.has(i));
  const rec = {
    id, from: from.id, to: to.id, amount, note, visibility, request_id: requestId,
    settlement_id: settlementId, created_at: createdAt, seq: ++S.seq, ts: tsOf(createdAt),
  };
  S.payments.set(id, rec);
  return rec;
}
function guardCredit(to, amount) {
  if (to.balance + amount > MAX_EXACT) throw bad('balance out of range');
}

// ---------------------------------------------------------------- endpoints
function doPayment(user, body) {
  const to = handleField(body, 'to_handle');
  if (!hasOwn(body, 'amount') || !validAmount(body.amount)) throw bad('amount');
  const note = optNote(body);
  const vis = optVisibility(body);
  const target = userByHandle(to);
  if (target.id === user.id) throw E(422, 'self_payment', 'cannot pay yourself');
  if (user.balance < body.amount) throw E(409, 'insufficient_funds', 'insufficient funds');
  guardCredit(target, body.amount);
  return paymentView(movePayment(user, target, body.amount, note, vis, null, null, nowStr()));
}

function doRequest(user, body) {
  const ph = handleField(body, 'payer_handle');
  if (!hasOwn(body, 'amount') || !validAmount(body.amount)) throw bad('amount');
  const note = optNote(body);
  const payer = userByHandle(ph);
  if (payer.id === user.id) throw E(422, 'self_request', 'cannot request from yourself');
  return requestView(createRequest(user, payer, body.amount, note));
}
function createRequest(requester, payer, amount, note) {
  const id = newId('rq', (i) => S.requests.has(i));
  const created = nowStr();
  const r = { id, requester: requester.id, payer: payer.id, amount, note, status: 'pending', payment_id: null,
    created_at: created, seq: ++S.seq, ts: tsOf(created) };
  S.requests.set(id, r);
  return r;
}

function findRequest(id) {
  const r = S.requests.get(id);
  if (!r) throw E(404, 'not_found', 'no such request');
  return r;
}

function doPay(user, id, body) {
  const vis = optVisibility(body);
  const r = findRequest(id);
  if (r.payer !== user.id) throw E(403, 'forbidden', 'only the payer may pay');
  if (r.status !== 'pending') throw E(409, 'request_not_pending', 'request is not pending');
  if (user.balance < r.amount) throw E(409, 'insufficient_funds', 'insufficient funds');
  const to = S.users.get(r.requester);
  guardCredit(to, r.amount);
  const p = movePayment(user, to, r.amount, r.note, vis, r.id, null, nowStr());
  r.status = 'paid';
  r.payment_id = p.id;
  return paymentView(p);
}

function doTransition(user, id, kind) {
  const r = findRequest(id);
  const target = kind === 'decline' ? 'declined' : 'cancelled';
  const actor = kind === 'decline' ? r.payer : r.requester;
  if (actor !== user.id) throw E(403, 'forbidden', 'not permitted');
  if (r.status === target) return requestView(r);
  if (r.status !== 'pending') throw E(409, 'request_not_pending', 'request is not pending');
  r.status = target;
  return requestView(r);
}

function doSplit(user, body) {
  if (!hasOwn(body, 'participant_handles')) throw bad('participant_handles is required');
  const hs = body.participant_handles;
  if (!Array.isArray(hs)) throw malformed('participant_handles must be an array');
  for (const h of hs) if (typeof h !== 'string') throw malformed('handles must be strings');
  if (!hasOwn(body, 'amount') || !validAmount(body.amount)) throw bad('amount');
  const note = optNote(body);
  if (hs.length === 0 || new Set(hs).size !== hs.length) throw bad('participant_handles');
  const users = hs.map(userByHandle);
  const n = hs.length, base = Math.floor(body.amount / n), rem = body.amount - base * n;
  const shares = users.map((u, i) => ({ handle: u.handle, amount: base + (i < rem ? 1 : 0) }));
  const reqs = [];
  users.forEach((u, i) => { if (u.id !== user.id) reqs.push(requestView(createRequest(user, u, shares[i].amount, note))); });
  const id = newId('sp', (i) => S.usedIds.sp.has(i));
  S.usedIds.sp.add(id);
  return { split_id: id, amount: body.amount, currency: S.currency, note, shares, requests: reqs, created_at: nowStr() };
}

function doSettlement(user, body) {
  const ts = body.transfers;
  if (!Array.isArray(ts) || ts.length < 1 || ts.length > 32) throw bad('transfers');
  for (const t of ts) if (!isObj(t)) throw bad('transfer must be an object');
  const parsed = [];
  for (const t of ts) {
    const fh = handleField(t, 'from_handle');
    const th = handleField(t, 'to_handle');
    if (!hasOwn(t, 'amount') || !validAmount(t.amount)) throw bad('amount');
    const note = optNote(t);
    const vis = optVisibility(t);
    const from = userByHandle(fh), to = userByHandle(th);
    if (from.id === to.id) throw E(422, 'self_payment', 'self transfer');
    parsed.push({ from, to, amount: t.amount, note, vis });
  }
  const delta = new Map();
  for (const t of parsed) {
    delta.set(t.from, (delta.get(t.from) || 0) - t.amount);
    delta.set(t.to, (delta.get(t.to) || 0) + t.amount);
  }
  for (const [u, d] of delta) {
    if (u.balance + d < 0) throw E(409, 'insufficient_funds', 'settlement is not affordable');
    if (u.balance + d > MAX_EXACT) throw bad('balance out of range');
  }
  const id = newId('st', (i) => S.usedIds.st.has(i));
  S.usedIds.st.add(id);
  const at = nowStr();
  const payments = parsed.map((t) => paymentView(movePayment(t.from, t.to, t.amount, t.note, t.vis, null, id, at)));
  return { settlement_id: id, committed_at: at, payments };
}

function page(q) {
  const num = (name, def, min, max) => {
    const v = q.get(name);
    if (v === null) return def;
    if (!/^[0-9]+$/.test(v)) throw bad(name);
    const n = Number(v);
    if (n < min || n > max) throw bad(name);
    return n;
  };
  return { limit: num('limit', 50, 1, 200), offset: num('offset', 0, 0, Infinity) };
}
function paged(items, { limit, offset }) {
  return { slice: items.slice(offset, offset + limit), more: offset + limit < items.length };
}

function listRequests(user, q) {
  const dir = q.get('direction'), status = q.get('status');
  if (dir !== null && dir !== 'incoming' && dir !== 'outgoing') throw bad('direction');
  if (status !== null && !STATUSES.includes(status)) throw bad('status');
  const pg = page(q);
  const items = [];
  for (const r of S.requests.values()) {
    const inc = r.payer === user.id, out = r.requester === user.id;
    if (!inc && !out) continue;
    if (dir === 'incoming' && !inc) continue;
    if (dir === 'outgoing' && !out) continue;
    if (status !== null && r.status !== status) continue;
    items.push(r);
  }
  items.sort(newestFirst);
  const { slice, more } = paged(items, pg);
  return { requests: slice.map(requestView), has_more: more };
}

function listActivity(user, q) {
  const pg = page(q);
  const items = [];
  for (const p of S.payments.values()) {
    if (p.visibility === 'public' || p.from === user.id || p.to === user.id) items.push(p);
  }
  items.sort(newestFirst);
  const { slice, more } = paged(items, pg);
  return { payments: slice.map(paymentView), has_more: more };
}

// ---------------------------------------------------------------- auth endpoints
const EMAIL_OK = (e) => {
  const i = e.indexOf('@');
  return i > 0 && i === e.lastIndexOf('@') && i < e.length - 1 && !/\s/.test(e);
};
function session(user, status) {
  const token = crypto.randomBytes(24).toString('hex');
  S.tokens.set(token, user.id);
  return { status, body: { user_id: user.id, display_name: user.display_name, token } };
}
function signup(body) {
  const f = ['email', 'password', 'display_name'];
  for (const k of f) if (hasOwn(body, k) && typeof body[k] !== 'string') throw malformed(k + ' must be a string');
  for (const k of f) if (!hasOwn(body, k)) throw bad(k + ' is required');
  const { email, password } = body;
  if (!EMAIL_OK(email)) throw bad('email');
  if (cpLen(password) < 8) throw bad('password too short');
  if (S.emails.has(email)) throw E(409, 'email_taken', 'email already registered');
  const handle = email.slice(0, email.indexOf('@')).toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 20);
  if (S.handles.has(handle)) throw E(409, 'handle_taken', 'handle already taken');
  const id = newId('u', (i) => S.users.has(i));
  const user = { id, email, display_name: body.display_name, handle, balance: 0, pw: hashPw(password) };
  S.users.set(id, user); S.emails.set(email, user); S.handles.set(handle, user);
  return session(user, 201);
}
function login(body) {
  for (const k of ['email', 'password']) if (hasOwn(body, k) && typeof body[k] !== 'string') throw malformed(k + ' must be a string');
  for (const k of ['email', 'password']) if (!hasOwn(body, k)) throw bad(k + ' is required');
  const user = S.emails.get(body.email);
  if (!user || !checkPw(body.password, user.pw)) throw E(401, 'unauthenticated', 'invalid credentials');
  return session(user, 200);
}

// ---------------------------------------------------------------- dispatch
function authenticate(req) {
  const h = req.headers.authorization;
  const m = typeof h === 'string' ? /^Bearer +(\S+)$/i.exec(h) : null;
  const uid = m ? S.tokens.get(m[1]) : undefined;
  if (!uid) throw E(401, 'unauthenticated', 'missing or invalid token');
  return S.users.get(uid);
}

function parseBody(raw, allowEmpty) {
  if (raw.length === 0 || raw.trim() === '') {
    if (allowEmpty) return {};
    throw malformed('empty body');
  }
  let v;
  try { v = JSON.parse(raw); } catch (e) { throw malformed('unparseable body'); }
  if (!isObj(v)) throw malformed('body must be a JSON object');
  return v;
}

// Runs an idempotent write. Order per D1: key header, body parse, claimed key, fields.
function keyed(req, user, path, raw, allowEmpty, fn) {
  const key = req.headers['idempotency-key'];
  if (key === undefined || key === '') throw E(400, 'missing_idempotency_key', 'Idempotency-Key required');
  if (key.length > 255) throw bad('Idempotency-Key too long');
  const body = parseBody(raw, allowEmpty);
  const k = user.id + '\u0000' + path + '\u0000' + key;
  const c = canon(body);
  const prior = S.idem.get(k);
  if (prior) {
    if (prior.canon !== c) throw E(409, 'idempotency_key_reuse', 'key used with a different body');
    return { status: 200, text: prior.text };
  }
  const out = fn(body);
  const text = JSON.stringify(out);
  S.idem.set(k, { canon: c, text });
  return { status: 201, text };
}

function handle(req, url, raw) {
  const m = req.method, path = url.pathname, q = url.searchParams;
  if (m === 'GET' && path === '/health') return { status: 200, body: { status: 'ok' } };
  if (m === 'POST' && path === '/_test/reset') {
    const f = parseBody(raw, false);
    let st;
    try { st = buildFromFixture(f); } catch (e) { if (e instanceof Invalid) throw bad('invalid fixture: ' + e.message); throw e; }
    S = st;
    return { status: 204 };
  }
  if (m === 'GET' && path === '/_test/export') {
    return { status: 200, text: JSON.stringify({ track: 'pocketful', format_version: 1, state: exportState() }) };
  }
  if (m === 'POST' && path === '/_test/import') {
    const b = parseBody(raw, false);
    if (b.track !== 'pocketful' || b.format_version !== 1 || !isObj(b.state)) throw bad('invalid export');
    let st;
    try { st = buildFromState(b.state); } catch (e) { if (e instanceof Invalid) throw bad('invalid state: ' + e.message); throw e; }
    S = st;
    return { status: 204 };
  }
  if (m === 'POST' && path === '/auth/signup') return signup(parseBody(raw, false));
  if (m === 'POST' && path === '/auth/login') return login(parseBody(raw, false));

  if (m === 'GET' && path === '/me') {
    const u = authenticate(req);
    return { status: 200, body: { user_id: u.id, display_name: u.display_name, handle: u.handle, balance: u.balance,
      currency: S.currency, minor_units: S.minorUnits } };
  }
  if (m === 'GET' && path === '/activity') return { status: 200, body: listActivity(authenticate(req), q) };
  if (m === 'GET' && path === '/requests') return { status: 200, body: listRequests(authenticate(req), q) };

  if (m === 'POST' && path === '/payments') {
    const u = authenticate(req);
    return keyed(req, u, path, raw, false, (b) => doPayment(u, b));
  }
  if (m === 'POST' && path === '/requests') {
    const u = authenticate(req);
    return keyed(req, u, path, raw, false, (b) => doRequest(u, b));
  }
  if (m === 'POST' && path === '/splits') {
    const u = authenticate(req);
    return keyed(req, u, path, raw, false, (b) => doSplit(u, b));
  }
  if (m === 'POST' && path === '/settlements') {
    const u = authenticate(req);
    if (!S.operators.has(u.id)) throw E(403, 'forbidden', 'settlement operator required');
    return keyed(req, u, path, raw, false, (b) => doSettlement(u, b));
  }
  const rm = m === 'POST' ? /^\/requests\/([^/]+)\/(pay|decline|cancel)$/.exec(path) : null;
  if (rm) {
    const u = authenticate(req);
    let id;
    try { id = decodeURIComponent(rm[1]); } catch (e) { id = rm[1]; }
    if (rm[2] === 'pay') return keyed(req, u, path, raw, true, (b) => doPay(u, id, b));
    parseBody(raw, true);
    return { status: 200, body: doTransition(u, id, rm[2]) };
  }
  throw E(404, 'not_found', 'no such route');
}

const JSON_CT = 'application/json; charset=utf-8';
function send(res, status, text) {
  if (status === 204) { res.writeHead(204); res.end(); return; }
  const buf = Buffer.from(text, 'utf8');
  res.writeHead(status, { 'Content-Type': JSON_CT, 'Content-Length': buf.length });
  res.end(buf);
}
const errText = (code, message) => JSON.stringify({ error: { code, message } });

const decoder = new TextDecoder('utf-8', { fatal: true });
const server = http.createServer((req, res) => {
  const chunks = [];
  let size = 0, dead = false;
  req.on('data', (c) => {
    size += c.length;
    if (size > 64 * 1024 * 1024) { dead = true; send(res, 400, errText('malformed_request', 'body too large')); req.destroy(); return; }
    chunks.push(c);
  });
  req.on('error', () => {});
  req.on('end', () => {
    if (dead) return;
    try {
      let raw;
      try { raw = decoder.decode(Buffer.concat(chunks)); } catch (e) { raw = null; }
      const url = new URL(req.url, 'http://localhost');
      if (raw === null) {
        // Undecodable bodies are malformed; routes that take no body never look.
        raw = '\u0000not-utf8';
      }
      const out = handle(req, url, raw);
      if (out.text !== undefined) send(res, out.status, out.text);
      else send(res, out.status, out.body === undefined ? '' : JSON.stringify(out.body));
    } catch (e) {
      if (e instanceof ApiError) send(res, e.status, errText(e.code, e.message));
      else { console.error(e); send(res, 500, errText('internal_error', 'internal error')); }
    }
  });
});
server.keepAliveTimeout = 65000;
server.headersTimeout = 66000;
server.requestTimeout = 0;

const port = parseInt(process.env.PORT, 10) || 8080;
server.listen(port, '0.0.0.0', () => console.log('pocketful listening on ' + port));
