'use strict';
// Pocketful stage 1: payments and settlements. Single process, all state in memory.
// Every state transition is a synchronous function (no await between the check and the
// commit), so under Node's single event loop each one is atomic by construction.
// Password hashing is the only asynchronous work and happens outside those transitions.

const http = require('http');
const crypto = require('crypto');

const MAX_AMOUNT = 1000000000;
const MAX_SAFE = 9007199254740992; // 2^53
const MAX_BODY = 16 * 1024 * 1024;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const SCRYPT_N = 2048; // ~4 ms per hash: keeps resets of large fixtures well inside the 10 s limit
const MAX_SEQ = 1e15; // id counters beyond this are rejected on import so ++ always advances

class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}
const E = (status, code, message) => new ApiError(status, code, message);
const invalid = (m) => E(422, 'validation_failed', m || 'validation failed');
const malformed = (m) => E(400, 'malformed_request', m || 'malformed request');

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const cpLen = (s) => { let n = 0; for (const _ of s) n++; return n; }; // eslint-disable-line no-unused-vars

// ---------------------------------------------------------------- state

function emptyState() {
  return {
    currency: 'EUR',
    minor_units: 2,
    users: new Map(),
    byEmail: new Map(),
    byHandle: new Map(),
    tokens: new Map(),
    payments: [],
    requests: [],
    splits: [],
    settlements: [],
    m: { p: new Map(), rq: new Map(), sp: new Map(), st: new Map() },
    operators: new Set(),
    idem: new Map(),
    seq: { p: 0, rq: 0, sp: 0, st: 0, u: 0 },
  };
}
let S = emptyState();

let lastMs = 0;
function nowIso() {
  let ms = Date.now();
  if (ms < lastMs) ms = lastMs;
  lastMs = ms;
  return new Date(ms).toISOString().replace('Z', '+00:00');
}

function newId(prefix) {
  const exists = prefix === 'u' ? (id) => S.users.has(id) : (id) => S.m[prefix].has(id);
  // The counter strictly increases and is bounded (import rejects counters above MAX_SEQ), so a free
  // id is found after at most (existing ids + 1) steps; the loop cannot stall.
  for (let i = 0; i < 100000000; i++) {
    const n = ++S.seq[prefix];
    if (!(n <= 2 * MAX_SEQ)) throw new Error('id counter exhausted');
    const id = prefix + '_' + n;
    if (!exists(id)) return id;
  }
  throw new Error('no free id');
}

// ---------------------------------------------------------------- passwords
// Scheme "scrypt-hmac": K = scrypt(password, salt_reset) (N=2048, r=8, p=1, 32 bytes);
// stored = HMAC-SHA256(K, salt_user) with a random per-user 16-byte salt_user. salt_reset is random
// per signup and per reset call, so users sharing a password inside one reset share one scrypt run
// (reset stays fast for big fixtures) while every stored value still differs per user and is derived
// through a real password-hashing function. Plaintext is never stored.

function scryptKey(pw, salt) {
  return new Promise((resolve, reject) => {
    try {
      crypto.scrypt(pw, salt, 32, { N: SCRYPT_N, r: 8, p: 1 }, (err, key) => (err ? reject(err) : resolve(key)));
    } catch (e) { reject(e); }
  });
}
async function hashPw(pw, cache) {
  let entry = cache && cache.get(pw);
  if (!entry) {
    const salt = crypto.randomBytes(16);
    entry = { salt, key: scryptKey(pw, salt) };
    if (cache) cache.set(pw, entry);
  }
  const key = await entry.key;
  const us = crypto.randomBytes(16);
  const mac = crypto.createHmac('sha256', key).update(us).digest();
  return `scrypt-hmac$${SCRYPT_N}$${entry.salt.toString('hex')}$${us.toString('hex')}$${mac.toString('hex')}`;
}
const HASH_RE = new RegExp(`^scrypt-hmac\\$${SCRYPT_N}\\$([0-9a-f]{32})\\$([0-9a-f]{32})\\$([0-9a-f]{64})$`);
async function verifyPw(pw, stored) {
  try {
    const m = HASH_RE.exec(stored);
    if (!m) return false;
    const key = await scryptKey(pw, Buffer.from(m[1], 'hex'));
    const mac = crypto.createHmac('sha256', key).update(Buffer.from(m[2], 'hex')).digest();
    return crypto.timingSafeEqual(mac, Buffer.from(m[3], 'hex'));
  } catch (e) {
    return false;
  }
}

// ---------------------------------------------------------------- views

const paymentView = (p) => {
  const f = S.users.get(p.from_user_id), t = S.users.get(p.to_user_id);
  return {
    payment_id: p.id,
    from_user_id: p.from_user_id,
    from_handle: f.handle,
    to_user_id: p.to_user_id,
    to_handle: t.handle,
    amount: p.amount,
    currency: S.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.request_id,
    settlement_id: p.settlement_id,
    created_at: p.created_at,
  };
};
const requestView = (r) => ({
  request_id: r.id,
  requester_id: r.requester_id,
  requester_handle: S.users.get(r.requester_id).handle,
  payer_id: r.payer_id,
  payer_handle: S.users.get(r.payer_id).handle,
  amount: r.amount,
  currency: S.currency,
  note: r.note,
  status: r.status,
  payment_id: r.payment_id,
  created_at: r.created_at,
});

// ---------------------------------------------------------------- field validation

function checkAmount(v) {
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 1 || v > MAX_AMOUNT) {
    throw invalid('amount must be an integer from 1 to 1000000000');
  }
  return v;
}
function checkNoteType(o) {
  if (!has(o, 'note')) return '';
  if (typeof o.note !== 'string') throw invalid('note must be a string');
  return o.note;
}
function checkNoteLen(note) {
  if (cpLen(note) > 200) throw invalid('note longer than 200 characters');
}
function checkVisibility(o) {
  if (!has(o, 'visibility')) return 'public';
  if (o.visibility !== 'public' && o.visibility !== 'private') throw invalid('visibility must be public or private');
  return o.visibility;
}
function checkHandleFormat(h) {
  if (!HANDLE_RE.test(h)) throw invalid('malformed handle');
}
function userByHandle(h) {
  const u = S.byHandle.get(h);
  if (!u) throw E(404, 'not_found', 'no such user');
  return u;
}

// ---------------------------------------------------------------- state transitions

function movePayment(from, to, amount, note, visibility, requestId, settlementId, ts) {
  from.balance -= amount;
  to.balance += amount;
  const p = {
    id: newId('p'),
    from_user_id: from.id,
    to_user_id: to.id,
    amount,
    note,
    visibility,
    request_id: requestId,
    settlement_id: settlementId,
    created_at: ts,
  };
  S.payments.push(p);
  S.m.p.set(p.id, p);
  return p;
}

function createRequest(requester, payer, amount, note, ts) {
  const r = {
    id: newId('rq'),
    requester_id: requester.id,
    payer_id: payer.id,
    amount,
    note,
    status: 'pending',
    payment_id: null,
    created_at: ts,
  };
  S.requests.push(r);
  S.m.rq.set(r.id, r);
  return r;
}

// ---------------------------------------------------------------- http helpers

const CT = 'application/json; charset=utf-8';
function send(res, status, obj) {
  if (status === 204) {
    res.writeHead(204);
    res.end();
    return;
  }
  const body = typeof obj === 'string' ? obj : JSON.stringify(obj);
  res.writeHead(status, { 'Content-Type': CT, 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}
const sendError = (res, e) => send(res, e.status, { error: { code: e.code, message: e.message } });

function parseBody(buf, { optional } = {}) {
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buf);
  } catch (e) {
    throw malformed('body is not valid UTF-8');
  }
  if (optional && text.trim() === '') return {};
  let v;
  try {
    v = JSON.parse(text);
  } catch (e) {
    throw malformed('body is not valid JSON');
  }
  if (!isObj(v)) throw malformed('body must be a JSON object');
  return v;
}

function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (v !== null && typeof v === 'object') {
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  }
  return JSON.stringify(v);
}

function readKey(headers) {
  const raw = headers['idempotency-key'];
  if (raw === undefined || raw === '') throw E(400, 'missing_idempotency_key', 'Idempotency-Key header required');
  const key = Buffer.from(raw, 'latin1').toString('utf8');
  if (key === '') throw E(400, 'missing_idempotency_key', 'Idempotency-Key header required');
  if (cpLen(key) > 255) throw invalid('Idempotency-Key longer than 255 characters');
  return key;
}

// Runs `handler(body)` once per (user, method, path, key). Synchronous start to finish.
function idempotent(ctx, handler, bodyOpts) {
  const key = readKey(ctx.headers);
  const body = parseBody(ctx.body, bodyOpts);
  const scope = JSON.stringify([ctx.user.id, ctx.method, ctx.path, key]);
  let c;
  try { c = canon(body); } catch (e) { throw malformed('body too deeply nested'); }
  const rec = S.idem.get(scope);
  if (rec) {
    if (rec.canon === c) return { status: 200, body: rec.response };
    throw E(409, 'idempotency_key_reuse', 'Idempotency-Key was used with a different request body');
  }
  const response = handler(body);
  S.idem.set(scope, { canon: c, response });
  return { status: 201, body: response };
}

// ---------------------------------------------------------------- handlers

function hMe(ctx) {
  const u = ctx.user;
  return { status: 200, body: {
    user_id: u.id, display_name: u.display_name, handle: u.handle,
    balance: u.balance, currency: S.currency, minor_units: S.minor_units,
  } };
}

function emailForm(e) {
  const i = e.indexOf('@');
  if (i < 1 || i !== e.lastIndexOf('@') || i === e.length - 1) return false;
  return !/\s/.test(e);
}
function deriveHandle(email) {
  const local = email.slice(0, email.indexOf('@')).toLowerCase();
  return Array.from(local).map((c) => (/[a-z0-9_]/.test(c) ? c : '_')).slice(0, 20).join('');
}

function authBody(ctx, fields) {
  const o = parseBody(ctx.body);
  for (const f of fields) if (!has(o, f)) throw invalid(`${f} is required`);
  for (const f of fields) if (typeof o[f] !== 'string') throw malformed(`${f} must be a string`);
  return o;
}

async function hSignup(ctx) {
  const o = authBody(ctx, ['email', 'password', 'display_name']);
  if (!emailForm(o.email)) throw invalid('email must be of the form local@domain');
  if (cpLen(o.password) < 8) throw invalid('password must be at least 8 characters');
  const handle = deriveHandle(o.email);
  const conflict = () => {
    if (S.byEmail.has(o.email)) throw E(409, 'email_taken', 'email already registered');
    if (S.byHandle.has(handle)) throw E(409, 'handle_taken', 'handle already taken');
  };
  conflict();
  const pw = await hashPw(o.password);
  conflict();
  const user = { id: newId('u'), email: o.email, pw, display_name: o.display_name, handle, balance: 0 };
  S.users.set(user.id, user);
  S.byEmail.set(user.email, user);
  S.byHandle.set(handle, user);
  const token = crypto.randomBytes(24).toString('hex');
  S.tokens.set(token, user.id);
  return { status: 201, body: { user_id: user.id, display_name: user.display_name, token } };
}

async function hLogin(ctx) {
  const o = authBody(ctx, ['email', 'password']);
  const bad = E(401, 'unauthenticated', 'invalid credentials');
  let user;
  // A reset/import may land while the hash is being checked; verify again against the new state.
  for (let attempt = 0; ; attempt++) {
    const st = S;
    user = st.byEmail.get(o.email);
    if (!user) throw bad;
    const ok = await verifyPw(o.password, user.pw);
    if (S === st) {
      if (!ok) throw bad;
      break;
    }
    if (attempt >= 2) throw bad;
  }
  const token = crypto.randomBytes(24).toString('hex');
  S.tokens.set(token, user.id);
  return { status: 200, body: { user_id: user.id, display_name: user.display_name, token } };
}

function hPayment(ctx) {
  return idempotent(ctx, (o) => {
    if (!has(o, 'to_handle')) throw invalid('to_handle is required');
    if (!has(o, 'amount')) throw invalid('amount is required');
    const amount = checkAmount(o.amount);
    const note = checkNoteType(o);
    const vis = checkVisibility(o);
    if (typeof o.to_handle !== 'string') throw malformed('to_handle must be a string');
    checkHandleFormat(o.to_handle);
    checkNoteLen(note);
    const to = userByHandle(o.to_handle);
    const from = ctx.user;
    if (to === from) throw E(422, 'self_payment', 'cannot pay yourself');
    if (from.balance < amount) throw E(409, 'insufficient_funds', 'insufficient funds');
    return paymentView(movePayment(from, to, amount, note, vis, null, null, nowIso()));
  });
}

function hRequestCreate(ctx) {
  return idempotent(ctx, (o) => {
    if (!has(o, 'payer_handle')) throw invalid('payer_handle is required');
    if (!has(o, 'amount')) throw invalid('amount is required');
    const amount = checkAmount(o.amount);
    const note = checkNoteType(o);
    if (typeof o.payer_handle !== 'string') throw malformed('payer_handle must be a string');
    checkHandleFormat(o.payer_handle);
    checkNoteLen(note);
    const payer = userByHandle(o.payer_handle);
    if (payer === ctx.user) throw E(422, 'self_request', 'cannot request money from yourself');
    return requestView(createRequest(ctx.user, payer, amount, note, nowIso()));
  });
}

function hPay(ctx) {
  return idempotent(ctx, (o) => {
    const vis = checkVisibility(o);
    const r = S.m.rq.get(ctx.params.id);
    if (!r) throw E(404, 'not_found', 'no such request');
    if (r.payer_id !== ctx.user.id) throw E(403, 'forbidden', 'only the payer may pay this request');
    if (r.status !== 'pending') throw E(409, 'request_not_pending', 'request is not pending');
    const payer = ctx.user;
    if (payer.balance < r.amount) throw E(409, 'insufficient_funds', 'insufficient funds');
    const requester = S.users.get(r.requester_id);
    const p = movePayment(payer, requester, r.amount, r.note, vis, r.id, null, nowIso());
    r.status = 'paid';
    r.payment_id = p.id;
    return paymentView(p);
  }, { optional: true });
}

function transition(ctx, who, target) {
  const r = S.m.rq.get(ctx.params.id);
  if (!r) throw E(404, 'not_found', 'no such request');
  if (r[who] !== ctx.user.id) throw E(403, 'forbidden', `only the ${who === 'payer_id' ? 'payer' : 'requester'} may do this`);
  if (r.status === 'pending') r.status = target;
  else if (r.status !== target) throw E(409, 'request_not_pending', 'request is not pending');
  return { status: 200, body: requestView(r) };
}
const hDecline = (ctx) => transition(ctx, 'payer_id', 'declined');
const hCancel = (ctx) => transition(ctx, 'requester_id', 'cancelled');

function parseIntParam(q, name, def, min, max) {
  if (!q.has(name)) return def;
  const s = q.get(name);
  if (!/^[0-9]+$/.test(s)) throw invalid(`${name} must be a plain decimal integer`);
  const n = Number(s);
  if (n < min || n > max) throw invalid(`${name} out of range`);
  return n;
}
function page(items, q) {
  const limit = parseIntParam(q, 'limit', 50, 1, 200);
  const offset = parseIntParam(q, 'offset', 0, 0, Infinity);
  return { items, limit, offset };
}
function paginate(all, limit, offset) {
  // `all` is oldest-first; the API lists newest-first.
  const total = all.length;
  const out = [];
  for (let i = total - 1 - offset; i >= 0 && out.length < limit; i--) out.push(all[i]);
  return { out, has_more: offset + out.length < total };
}

function hRequestList(ctx) {
  const q = ctx.query;
  const limit = parseIntParam(q, 'limit', 50, 1, 200);
  const offset = parseIntParam(q, 'offset', 0, 0, Infinity);
  const dir = q.has('direction') ? q.get('direction') : null;
  const status = q.has('status') ? q.get('status') : null;
  if (dir !== null && dir !== 'incoming' && dir !== 'outgoing') throw invalid('unknown direction');
  if (status !== null && !['pending', 'paid', 'declined', 'cancelled'].includes(status)) throw invalid('unknown status');
  const uid = ctx.user.id;
  const mine = S.requests.filter((r) => {
    const inc = r.payer_id === uid, outg = r.requester_id === uid;
    if (dir === 'incoming' ? !inc : dir === 'outgoing' ? !outg : !(inc || outg)) return false;
    return status === null || r.status === status;
  });
  const { out, has_more } = paginate(mine, limit, offset);
  return { status: 200, body: { requests: out.map(requestView), has_more } };
}

function hActivity(ctx) {
  const { limit, offset } = page(null, ctx.query);
  const uid = ctx.user.id;
  const vis = S.payments.filter((p) => p.visibility === 'public' || p.from_user_id === uid || p.to_user_id === uid);
  const { out, has_more } = paginate(vis, limit, offset);
  return { status: 200, body: { payments: out.map(paymentView), has_more } };
}

function hSplit(ctx) {
  return idempotent(ctx, (o) => {
    if (!has(o, 'participant_handles')) throw invalid('participant_handles is required');
    if (!has(o, 'amount')) throw invalid('amount is required');
    const amount = checkAmount(o.amount);
    const note = checkNoteType(o);
    const hs = o.participant_handles;
    if (!Array.isArray(hs)) throw malformed('participant_handles must be an array');
    for (const h of hs) if (typeof h !== 'string') throw malformed('participant_handles must hold strings');
    if (hs.length === 0) throw invalid('participant_handles must not be empty');
    checkNoteLen(note);
    for (const h of hs) checkHandleFormat(h);
    if (new Set(hs).size !== hs.length) throw invalid('duplicate participant handle');
    const users = hs.map(userByHandle);
    const n = users.length;
    const base = Math.floor(amount / n), rem = amount % n;
    const ts = nowIso();
    const shares = users.map((u, i) => ({ handle: u.handle, amount: base + (i < rem ? 1 : 0) }));
    const reqs = [];
    users.forEach((u, i) => {
      if (u !== ctx.user) reqs.push(createRequest(ctx.user, u, shares[i].amount, note, ts));
    });
    const sp = {
      id: newId('sp'), requester_id: ctx.user.id, amount, note,
      shares, request_ids: reqs.map((r) => r.id), created_at: ts,
    };
    S.splits.push(sp);
    S.m.sp.set(sp.id, sp);
    return {
      split_id: sp.id, amount, currency: S.currency, note,
      shares: shares.map((s) => ({ ...s })), requests: reqs.map(requestView), created_at: ts,
    };
  });
}

function hSettlement(ctx) {
  if (!S.operators.has(ctx.user.id)) throw E(403, 'forbidden', 'settlement operator required');
  return idempotent(ctx, (o) => {
    const ts = o.transfers;
    if (!Array.isArray(ts) || ts.length < 1 || ts.length > 32 || !ts.every(isObj)) {
      throw invalid('transfers must be an array of 1 to 32 objects');
    }
    const entries = [];
    for (const t of ts) {
      if (!has(t, 'from_handle') || typeof t.from_handle !== 'string') throw invalid('from_handle must be a string');
      if (!has(t, 'to_handle') || typeof t.to_handle !== 'string') throw invalid('to_handle must be a string');
      if (!has(t, 'amount')) throw invalid('amount is required');
      const amount = checkAmount(t.amount);
      const note = checkNoteType(t);
      const vis = checkVisibility(t);
      checkHandleFormat(t.from_handle);
      checkHandleFormat(t.to_handle);
      checkNoteLen(note);
      const from = userByHandle(t.from_handle);
      const to = userByHandle(t.to_handle);
      if (from === to) throw E(422, 'self_payment', 'self-transfer');
      entries.push({ from, to, amount, note, vis });
    }
    const net = new Map();
    for (const e of entries) {
      net.set(e.from, (net.get(e.from) || 0) - e.amount);
      net.set(e.to, (net.get(e.to) || 0) + e.amount);
    }
    for (const [u, d] of net) if (u.balance + d < 0) throw E(409, 'insufficient_funds', 'insufficient funds');
    const committed = nowIso();
    const id = newId('st');
    const payments = entries.map((e) => movePayment(e.from, e.to, e.amount, e.note, e.vis, null, id, committed));
    const st = { id, committed_at: committed, payment_ids: payments.map((p) => p.id) };
    S.settlements.push(st);
    S.m.st.set(id, st);
    return { settlement_id: id, committed_at: committed, payments: payments.map(paymentView) };
  });
}

// ---------------------------------------------------------------- reset / export / import

function serialize() {
  return {
    currency: S.currency,
    minor_units: S.minor_units,
    users: [...S.users.values()].map((u) => ({ ...u })),
    tokens: [...S.tokens].map(([t, u]) => [t, u]),
    payments: S.payments.map((p) => ({ ...p })),
    requests: S.requests.map((r) => ({ ...r })),
    splits: S.splits,
    settlements: S.settlements,
    operators: [...S.operators],
    idem: [...S.idem].map(([scope, v]) => ({ scope, canon: v.canon, response: v.response })),
    seq: { ...S.seq },
  };
}

const TS_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$/;
const isStr = (v) => typeof v === 'string';
const isId = (v) => isStr(v) && v.length >= 1 && v.length <= 64;
const isInt = (v, min = 0) => typeof v === 'number' && Number.isInteger(v) && v >= min && v <= MAX_SAFE;
const need = (c, m) => { if (!c) throw invalid(m); };

function checkUserPayload(u, i, seen) {
  need(isObj(u), `users[${i}] must be an object`);
  need(isId(u.id) && !seen.ids.has(u.id), `users[${i}].id invalid or duplicate`);
  need(isStr(u.email) && u.email !== '' && !seen.emails.has(u.email), `users[${i}].email invalid or duplicate`);
  need(isStr(u.display_name), `users[${i}].display_name must be a string`);
  need(isStr(u.handle) && HANDLE_RE.test(u.handle) && !seen.handles.has(u.handle), `users[${i}].handle invalid or duplicate`);
  need(isInt(u.balance, 0), `users[${i}].balance must be a non-negative integer`);
  seen.ids.add(u.id); seen.emails.add(u.email); seen.handles.add(u.handle);
}

function checkMoneyRows(rows, kind, users, st, extra) {
  need(Array.isArray(rows), `${kind} must be an array`);
  const ids = new Set();
  rows.forEach((r, i) => {
    need(isObj(r), `${kind}[${i}] must be an object`);
    need(isId(r.id) && !ids.has(r.id), `${kind}[${i}].id invalid or duplicate`);
    ids.add(r.id);
    need(isInt(r.amount, 0), `${kind}[${i}].amount must be a non-negative integer`);
    if (has(r, 'note') && r.note !== undefined) need(isStr(r.note), `${kind}[${i}].note must be a string`);
    extra(r, i);
  });
  return ids;
}

function buildState(fixture, hashes) {
  const st = emptyState();
  st.currency = fixture.currency;
  st.minor_units = fixture.minor_units;
  fixture.users.forEach((u, i) => {
    const user = { id: u.id, email: u.email, pw: hashes[i], display_name: u.display_name, handle: u.handle, balance: u.balance + 0 };
    st.users.set(user.id, user);
    st.byEmail.set(user.email, user);
    st.byHandle.set(user.handle, user);
  });
  return st;
}

function validateFixture(f) {
  need(isStr(f.currency) && f.currency !== '', 'currency must be a non-empty string');
  need(f.minor_units === 0 || f.minor_units === 2 || f.minor_units === 3, 'minor_units must be 0, 2 or 3');
  need(Array.isArray(f.users), 'users must be an array');
  const seen = { ids: new Set(), emails: new Set(), handles: new Set() };
  f.users.forEach((u, i) => {
    checkUserPayload(u, i, seen);
    need(isStr(u.password), `users[${i}].password must be a string`);
  });
  const payments = has(f, 'payments') ? f.payments : [];
  const requests = has(f, 'requests') ? f.requests : [];
  const ops = has(f, 'settlement_operator_ids') ? f.settlement_operator_ids : [];
  const known = (id) => seen.ids.has(id);
  checkMoneyRows(payments, 'payments', null, null, (p, i) => {
    need(isStr(p.from_user_id) && known(p.from_user_id), `payments[${i}].from_user_id unknown`);
    need(isStr(p.to_user_id) && known(p.to_user_id), `payments[${i}].to_user_id unknown`);
    if (has(p, 'visibility')) need(p.visibility === 'public' || p.visibility === 'private', `payments[${i}].visibility invalid`);
  });
  checkMoneyRows(requests, 'requests', null, null, (r, i) => {
    need(isStr(r.requester_id) && known(r.requester_id), `requests[${i}].requester_id unknown`);
    need(isStr(r.payer_id) && known(r.payer_id), `requests[${i}].payer_id unknown`);
    need(['pending', 'paid', 'declined', 'cancelled'].includes(r.status), `requests[${i}].status invalid`);
    if (has(r, 'payment_id') && r.payment_id !== null) need(isId(r.payment_id), `requests[${i}].payment_id invalid`);
  });
  need(Array.isArray(ops) && ops.every(isStr), 'settlement_operator_ids must be an array of strings');
  return { payments, requests, ops };
}

async function doReset(f) {
  const { payments, requests, ops } = validateFixture(f);
  const cache = new Map();
  const hashes = await Promise.all(f.users.map((u) => hashPw(u.password, cache)));
  const st = buildState(f, hashes);
  const ts = nowIso();
  const keep = S;
  S = st; // newId needs S to be the new state
  try {
    for (const p of payments) {
      const rec = {
        id: p.id, from_user_id: p.from_user_id, to_user_id: p.to_user_id, amount: p.amount,
        note: has(p, 'note') ? p.note : '', visibility: has(p, 'visibility') ? p.visibility : 'public',
        request_id: null, settlement_id: null, created_at: ts,
      };
      st.payments.push(rec);
      st.m.p.set(rec.id, rec);
    }
    for (const r of requests) {
      const rec = {
        id: r.id, requester_id: r.requester_id, payer_id: r.payer_id, amount: r.amount,
        note: has(r, 'note') ? r.note : '', status: r.status,
        payment_id: has(r, 'payment_id') ? r.payment_id : null, created_at: ts,
      };
      st.requests.push(rec);
      st.m.rq.set(rec.id, rec);
    }
    for (const id of ops) if (st.users.has(id)) st.operators.add(id);
  } catch (e) {
    S = keep;
    throw e;
  }
}

function doImport(env) {
  need(isObj(env), 'body must be an object');
  need(env.track === 'pocketful', 'track must be "pocketful"');
  need(env.format_version === 1, 'format_version must be 1');
  const s = env.state;
  need(isObj(s), 'state must be an object');
  need(isStr(s.currency) && s.currency !== '', 'state.currency invalid');
  need(s.minor_units === 0 || s.minor_units === 2 || s.minor_units === 3, 'state.minor_units invalid');
  need(Array.isArray(s.users), 'state.users must be an array');
  const seen = { ids: new Set(), emails: new Set(), handles: new Set() };
  s.users.forEach((u, i) => {
    checkUserPayload(u, i, seen);
    need(isStr(u.pw) && HASH_RE.test(u.pw), `users[${i}].pw invalid`);
  });
  const known = (id) => seen.ids.has(id);
  const tokSeen = new Set();
  need(Array.isArray(s.tokens) && s.tokens.every((t) => {
    if (!Array.isArray(t) || t.length !== 2 || !isStr(t[0]) || t[0] === '' || !known(t[1]) || tokSeen.has(t[0])) return false;
    tokSeen.add(t[0]);
    return true;
  }), 'state.tokens invalid');
  const iso = (v) => isStr(v) && TS_RE.test(v);
  checkMoneyRows(s.payments, 'payments', null, null, (p, i) => {
    need(isStr(p.from_user_id) && known(p.from_user_id) && isStr(p.to_user_id) && known(p.to_user_id), `payments[${i}] user unknown`);
    need(isStr(p.note), `payments[${i}].note invalid`);
    need(p.visibility === 'public' || p.visibility === 'private', `payments[${i}].visibility invalid`);
    need(p.request_id === null || isId(p.request_id), `payments[${i}].request_id invalid`);
    need(p.settlement_id === null || isId(p.settlement_id), `payments[${i}].settlement_id invalid`);
    need(iso(p.created_at), `payments[${i}].created_at invalid`);
  });
  checkMoneyRows(s.requests, 'requests', null, null, (r, i) => {
    need(isStr(r.requester_id) && known(r.requester_id) && isStr(r.payer_id) && known(r.payer_id), `requests[${i}] user unknown`);
    need(isStr(r.note), `requests[${i}].note invalid`);
    need(['pending', 'paid', 'declined', 'cancelled'].includes(r.status), `requests[${i}].status invalid`);
    need(r.payment_id === null || isId(r.payment_id), `requests[${i}].payment_id invalid`);
    need(iso(r.created_at), `requests[${i}].created_at invalid`);
  });
  need(Array.isArray(s.splits), 'state.splits must be an array');
  const spIds = new Set();
  s.splits.forEach((sp, i) => {
    need(isObj(sp) && isId(sp.id) && !spIds.has(sp.id), `splits[${i}] invalid`);
    spIds.add(sp.id);
    need(isStr(sp.requester_id) && known(sp.requester_id) && isInt(sp.amount, 0) && isStr(sp.note) && iso(sp.created_at), `splits[${i}] fields invalid`);
    need(Array.isArray(sp.shares) && sp.shares.every((x) => isObj(x) && isStr(x.handle) && isInt(x.amount, 0)), `splits[${i}].shares invalid`);
    need(Array.isArray(sp.request_ids) && sp.request_ids.every(isId), `splits[${i}].request_ids invalid`);
  });
  need(Array.isArray(s.settlements), 'state.settlements must be an array');
  const stIds = new Set();
  s.settlements.forEach((x, i) => {
    need(isObj(x) && isId(x.id) && !stIds.has(x.id) && iso(x.committed_at), `settlements[${i}] invalid`);
    stIds.add(x.id);
    need(Array.isArray(x.payment_ids) && x.payment_ids.every(isId), `settlements[${i}].payment_ids invalid`);
  });
  need(Array.isArray(s.operators) && s.operators.every((id) => isStr(id) && known(id)), 'state.operators invalid');
  const scopes = new Set();
  need(Array.isArray(s.idem) && s.idem.every((r) => {
    if (!isObj(r) || !isStr(r.scope) || !isStr(r.canon) || !isObj(r.response) || scopes.has(r.scope)) return false;
    scopes.add(r.scope);
    let sc;
    try { sc = JSON.parse(r.scope); } catch (e) { return false; }
    return Array.isArray(sc) && sc.length === 4 && sc.every(isStr) && known(sc[0]);
  }), 'state.idem invalid');
  need(isObj(s.seq) && ['p', 'rq', 'sp', 'st', 'u'].every((k) => isInt(s.seq[k], 0) && s.seq[k] <= MAX_SEQ), 'state.seq invalid');

  const st = emptyState();
  st.currency = s.currency;
  st.minor_units = s.minor_units;
  for (const u of s.users) {
    const user = { id: u.id, email: u.email, pw: u.pw, display_name: u.display_name, handle: u.handle, balance: u.balance };
    st.users.set(user.id, user);
    st.byEmail.set(user.email, user);
    st.byHandle.set(user.handle, user);
  }
  for (const [t, uid] of s.tokens) st.tokens.set(t, uid);
  for (const p of s.payments) {
    const rec = { id: p.id, from_user_id: p.from_user_id, to_user_id: p.to_user_id, amount: p.amount, note: p.note,
      visibility: p.visibility, request_id: p.request_id, settlement_id: p.settlement_id, created_at: p.created_at };
    st.payments.push(rec);
    st.m.p.set(rec.id, rec);
  }
  for (const r of s.requests) {
    const rec = { id: r.id, requester_id: r.requester_id, payer_id: r.payer_id, amount: r.amount, note: r.note,
      status: r.status, payment_id: r.payment_id, created_at: r.created_at };
    st.requests.push(rec);
    st.m.rq.set(rec.id, rec);
  }
  for (const sp of s.splits) { st.splits.push(sp); st.m.sp.set(sp.id, sp); }
  for (const x of s.settlements) { st.settlements.push(x); st.m.st.set(x.id, x); }
  for (const id of s.operators) st.operators.add(id);
  for (const r of s.idem) st.idem.set(r.scope, { canon: r.canon, response: r.response });
  st.seq = { p: s.seq.p, rq: s.seq.rq, sp: s.seq.sp, st: s.seq.st, u: s.seq.u };
  S = st;
}

// ---------------------------------------------------------------- routing

const ROUTES = [
  ['GET', /^\/health$/, false, () => ({ status: 200, body: { status: 'ok' } })],
  ['POST', /^\/_test\/reset$/, false, async (ctx) => { await doReset(parseBody(ctx.body)); return { status: 204 }; }],
  ['GET', /^\/_test\/export$/, false, () => ({
    status: 200,
    body: '{"track":"pocketful","format_version":1,"state":' + JSON.stringify(serialize()) + '}',
  })],
  ['POST', /^\/_test\/import$/, false, (ctx) => { doImport(parseBody(ctx.body)); return { status: 204 }; }],
  ['POST', /^\/auth\/signup$/, false, hSignup],
  ['POST', /^\/auth\/login$/, false, hLogin],
  ['GET', /^\/me$/, true, hMe],
  ['POST', /^\/payments$/, true, hPayment],
  ['POST', /^\/requests$/, true, hRequestCreate],
  ['GET', /^\/requests$/, true, hRequestList],
  ['POST', /^\/requests\/([^/]+)\/pay$/, true, hPay],
  ['POST', /^\/requests\/([^/]+)\/decline$/, true, hDecline],
  ['POST', /^\/requests\/([^/]+)\/cancel$/, true, hCancel],
  ['POST', /^\/splits$/, true, hSplit],
  ['GET', /^\/activity$/, true, hActivity],
  ['POST', /^\/settlements$/, true, hSettlement],
];

function authenticate(headers) {
  const h = headers.authorization;
  const m = typeof h === 'string' ? /^Bearer +(\S+)$/i.exec(h) : null;
  const uid = m ? S.tokens.get(m[1]) : undefined;
  const user = uid === undefined ? undefined : S.users.get(uid);
  if (!user) throw E(401, 'unauthenticated', 'missing or invalid bearer token');
  return user;
}

async function dispatch(req, body) {
  const url = req.url || '';
  const qi = url.indexOf('?');
  const path = qi < 0 ? url : url.slice(0, qi);
  const query = new URLSearchParams(qi < 0 ? '' : url.slice(qi + 1));
  let allowed = false;
  for (const [method, re, auth, handler] of ROUTES) {
    const m = re.exec(path);
    if (!m) continue;
    allowed = true;
    if (method !== req.method) continue;
    let dpath = path;
    try { dpath = decodeURIComponent(path); } catch (e) { /* keep raw */ }
    const ctx = { method, path: dpath, query, headers: req.headers, body, params: {}, user: null };
    if (m[1] !== undefined) {
      try { ctx.params.id = decodeURIComponent(m[1]); } catch (e) { ctx.params.id = '\0'; }
    }
    if (auth) ctx.user = authenticate(req.headers);
    return handler(ctx);
  }
  if (allowed) throw E(405, 'method_not_allowed', 'method not allowed');
  throw E(404, 'not_found', 'no such route');
}

function onRequest(req, res) {
  const chunks = [];
  let size = 0;
  let aborted = false;
  req.on('data', (c) => {
    if (aborted) return;
    size += c.length;
    if (size > MAX_BODY) {
      aborted = true;
      res.setHeader('Connection', 'close');
      sendError(res, E(413, 'payload_too_large', 'request body too large'));
      return;
    }
    chunks.push(c);
  });
  req.on('error', () => { aborted = true; });
  req.on('end', async () => {
    if (aborted) return;
    try {
      const r = await dispatch(req, Buffer.concat(chunks));
      send(res, r.status, r.body);
    } catch (e) {
      if (e instanceof ApiError) return sendError(res, e);
      console.error(e);
      sendError(res, E(500, 'internal_error', 'internal error'));
    }
  });
}

function createServer() {
  const server = http.createServer({ maxHeaderSize: 262144 }, onRequest);
  server.keepAliveTimeout = 65000;
  server.headersTimeout = 70000;
  server.on('clientError', (err, socket) => {
    if (!socket.writable) { socket.destroy(); return; }
    const b = JSON.stringify({ error: { code: 'malformed_request', message: 'bad request' } });
    socket.end(`HTTP/1.1 400 Bad Request\r\nContent-Type: ${CT}\r\nContent-Length: ${Buffer.byteLength(b)}\r\nConnection: close\r\n\r\n${b}`);
  });
  return server;
}

module.exports = { createServer };

if (require.main === module) {
  process.on('uncaughtException', (e) => console.error('uncaught', e));
  process.on('unhandledRejection', (e) => console.error('unhandled', e));
  const port = Number(process.env.PORT) || 8080;
  createServer().listen(port, '0.0.0.0', () => console.log(`pocketful listening on ${port}`));
}
