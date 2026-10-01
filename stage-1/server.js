'use strict';
// Pocketful stage 1: payments and settlements. Single process, in-memory state,
// no runtime dependencies. All state mutation happens synchronously inside one
// event-loop turn, which is what makes every money movement atomic.

const http = require('http');
const crypto = require('crypto');

// ---------------------------------------------------------------- constants
const MAX_AMOUNT = 1000000000;
const MAX_BALANCE = 2 ** 53;
const MAX_NOTE = 200;
const BODY_LIMIT = 1 << 20; // 1 MiB for ordinary endpoints
const CONTROL_BODY_LIMIT = 256 << 20; // reset / import
const MAX_DEPTH = 100;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const SCRYPT = { N: 4096, r: 8, p: 1 };
const DAYS_STATUSES = new Set(['pending', 'paid', 'declined', 'cancelled']);

class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}
const bad = (m) => new ApiError(400, 'malformed_request', m || 'malformed request');
const invalid = (m) => new ApiError(422, 'validation_failed', m || 'validation failed');
const notFound = (m) => new ApiError(404, 'not_found', m || 'not found');
const forbidden = (m) => new ApiError(403, 'forbidden', m || 'forbidden');

// -------------------------------------------------------------------- state
function emptyState() {
  return {
    currency: 'EUR',
    minorUnits: 2,
    users: new Map(), // id -> user
    byEmail: new Map(),
    byHandle: new Map(),
    tokens: new Map(), // token -> user id
    payments: [], // creation order
    paymentById: new Map(),
    requests: [], // creation order
    requestById: new Map(),
    splits: new Map(), // id -> response object
    settlements: new Map(), // id -> response object
    operators: new Set(),
    idem: new Map(), // composite -> record
    counters: { u: 0, p: 0, rq: 0, sp: 0, st: 0 },
  };
}
let S = emptyState();

function genId(prefix, taken) {
  for (;;) {
    const id = prefix + '_' + ++S.counters[prefix];
    if (!taken(id)) return id;
  }
}
const newUserId = () => genId('u', (i) => S.users.has(i));
const newPaymentId = () => genId('p', (i) => S.paymentById.has(i));
const newRequestId = () => genId('rq', (i) => S.requestById.has(i));
const newSplitId = () => genId('sp', (i) => S.splits.has(i));
const newSettlementId = () => genId('st', (i) => S.settlements.has(i));

function nowStamp() {
  return new Date().toISOString().replace(/\.\d+Z$/, '+00:00');
}

// ---------------------------------------------------------------- passwords
function hashPassword(pw) {
  return new Promise((resolve, reject) => {
    const salt = crypto.randomBytes(16);
    crypto.scrypt(pw, salt, 32, { ...SCRYPT, maxmem: 64 << 20 }, (err, key) => {
      if (err) return reject(err);
      resolve(`scrypt$${SCRYPT.N}$${SCRYPT.r}$${SCRYPT.p}$${salt.toString('hex')}$${key.toString('hex')}`);
    });
  });
}
const HASH_RE = /^scrypt\$(\d+)\$(\d+)\$(\d+)\$([0-9a-f]+)\$([0-9a-f]+)$/;
function verifyPassword(pw, stored) {
  return new Promise((resolve) => {
    const m = HASH_RE.exec(stored);
    if (!m) return resolve(false);
    const expect = Buffer.from(m[5], 'hex');
    crypto.scrypt(pw, Buffer.from(m[4], 'hex'), expect.length,
      { N: +m[1], r: +m[2], p: +m[3], maxmem: 64 << 20 }, (err, key) => {
        resolve(!err && key.length === expect.length && crypto.timingSafeEqual(key, expect));
      });
  });
}

// ---------------------------------------------------------------- utilities
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function codePointLength(s) {
  if (s.length > 2 * MAX_NOTE + 2) return s.length / 2 | 0; // certainly too long
  let n = 0;
  for (const _ of s) n++; // eslint-disable-line no-unused-vars
  return n;
}

function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== 'object') return false;
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
    return true;
  }
  if (Array.isArray(b)) return false;
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  for (const k of ka) if (!has(b, k) || !deepEqual(a[k], b[k])) return false;
  return true;
}

function jsonDepthOk(v) {
  const stack = [[v, 1]];
  while (stack.length) {
    const [x, d] = stack.pop();
    if (x !== null && typeof x === 'object') {
      if (d > MAX_DEPTH) return false;
      for (const c of Array.isArray(x) ? x : Object.values(x)) stack.push([c, d + 1]);
    }
  }
  return true;
}

function parseObject(body) {
  if (body.tooLarge) throw new ApiError(413, 'validation_failed', 'request body too large');
  if (body.buf.length === 0) throw bad('empty body');
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(body.buf);
  } catch (e) {
    throw bad('body is not valid UTF-8');
  }
  let v;
  try {
    v = JSON.parse(text);
  } catch (e) {
    throw bad('body is not valid JSON');
  }
  if (!isObj(v)) throw bad('body must be a JSON object');
  if (!jsonDepthOk(v)) throw bad('body is nested too deeply');
  return v;
}

// ---------------------------------------------------------- field validation
function vAmount(v) {
  if (v === undefined) throw invalid('amount is required');
  if (typeof v !== 'number' || !Number.isInteger(v)) throw invalid('amount must be an integer');
  if (v < 1 || v > MAX_AMOUNT) throw invalid('amount out of range');
  return v;
}
function vNote(v) {
  if (v === undefined) return '';
  if (typeof v !== 'string') throw invalid('note must be a string');
  if (codePointLength(v) > MAX_NOTE) throw invalid('note too long');
  return v;
}
function vVisibility(v) {
  if (v === undefined) return 'public';
  if (v !== 'public' && v !== 'private') throw invalid('visibility must be public or private');
  return v;
}
function vHandle(v, name) {
  if (v === undefined) throw invalid(name + ' is required');
  if (typeof v !== 'string') throw bad(name + ' must be a string');
  return v;
}
function userByHandle(h) {
  const u = S.byHandle.get(h);
  if (!u) throw notFound('no user with that handle');
  return u;
}

// --------------------------------------------------------- object builders
function paymentView(p) {
  return p;
}
function addPayment(from, to, amount, note, visibility, requestId, settlementId, createdAt) {
  const p = {
    payment_id: newPaymentId(),
    from_user_id: from.id,
    from_handle: from.handle,
    to_user_id: to.id,
    to_handle: to.handle,
    amount,
    currency: S.currency,
    note,
    visibility,
    request_id: requestId,
    settlement_id: settlementId,
    created_at: createdAt,
  };
  S.payments.push(p);
  S.paymentById.set(p.payment_id, p);
  return p;
}
function addRequest(requester, payer, amount, note, createdAt) {
  const r = {
    request_id: newRequestId(),
    requester_id: requester.id,
    requester_handle: requester.handle,
    payer_id: payer.id,
    payer_handle: payer.handle,
    amount,
    currency: S.currency,
    note,
    status: 'pending',
    payment_id: null,
    created_at: createdAt,
  };
  S.requests.push(r);
  S.requestById.set(r.request_id, r);
  return r;
}
function move(from, to, amount) {
  const a = BigInt(amount);
  from.balance -= a;
  to.balance += a;
}

// ------------------------------------------------------------- idempotency
function readKey(req) {
  const raw = req.headers['idempotency-key'];
  if (raw === undefined || raw === '') throw new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key header required');
  if (raw.length > 4 * 255) throw invalid('Idempotency-Key too long');
  let key = Buffer.from(raw, 'latin1').toString('utf8');
  if (key.includes('�')) key = raw;
  let n = 0;
  for (const _ of key) n++; // eslint-disable-line no-unused-vars
  if (n > 255) throw invalid('Idempotency-Key too long');
  return key;
}

// Runs `work(body)` under the five-step idempotent contract. `work` must
// validate fully before it mutates anything and returns the 201 response object.
function idempotent(ctx, work) {
  const key = readKey(ctx.req);
  const body = parseObject(ctx.body);
  const composite = ctx.user.id + '\n' + ctx.req.method + ' ' + ctx.path + '\n' + key;
  const rec = S.idem.get(composite);
  if (rec) {
    if (deepEqual(rec.body, body)) return { status: 200, json: rec.response };
    throw new ApiError(409, 'idempotency_key_reuse', 'Idempotency-Key was used with a different request');
  }
  const out = work(body);
  const json = JSON.stringify(out);
  S.idem.set(composite, {
    user_id: ctx.user.id, method: ctx.req.method, path: ctx.path, key, body, status: 201, response: json,
  });
  return { status: 201, json };
}

// ---------------------------------------------------------------- handlers
function me(ctx) {
  const u = ctx.user;
  return {
    status: 200,
    obj: {
      user_id: u.id, display_name: u.displayName, handle: u.handle,
      balance: Number(u.balance), currency: S.currency, minor_units: S.minorUnits,
    },
  };
}

function createPayment(ctx) {
  return idempotent(ctx, (b) => {
    const amount = vAmount(b.amount);
    const note = vNote(b.note);
    const vis = vVisibility(b.visibility);
    const h = vHandle(b.to_handle, 'to_handle');
    const to = userByHandle(h);
    const from = ctx.user;
    if (to.id === from.id) throw new ApiError(422, 'self_payment', 'cannot pay yourself');
    if (from.balance < BigInt(amount)) throw new ApiError(409, 'insufficient_funds', 'insufficient funds');
    move(from, to, amount);
    return paymentView(addPayment(from, to, amount, note, vis, null, null, nowStamp()));
  });
}

function createRequest(ctx) {
  return idempotent(ctx, (b) => {
    const amount = vAmount(b.amount);
    const note = vNote(b.note);
    const h = vHandle(b.payer_handle, 'payer_handle');
    const payer = userByHandle(h);
    if (payer.id === ctx.user.id) throw new ApiError(422, 'self_request', 'cannot request money from yourself');
    return { ...addRequest(ctx.user, payer, amount, note, nowStamp()) };
  });
}

function payRequest(ctx) {
  return idempotent(ctx, (b) => {
    const vis = vVisibility(b.visibility);
    const rq = S.requestById.get(ctx.params.id);
    if (!rq) throw notFound('no such request');
    if (rq.payer_id !== ctx.user.id) throw forbidden('only the payer may pay a request');
    if (rq.status !== 'pending') throw new ApiError(409, 'request_not_pending', 'request is not pending');
    const payer = ctx.user;
    if (payer.balance < BigInt(rq.amount)) throw new ApiError(409, 'insufficient_funds', 'insufficient funds');
    const requester = S.users.get(rq.requester_id);
    move(payer, requester, rq.amount);
    const p = addPayment(payer, requester, rq.amount, rq.note, vis, rq.request_id, null, nowStamp());
    rq.status = 'paid';
    rq.payment_id = p.payment_id;
    return paymentView(p);
  });
}

function decideRequest(kind) {
  const target = kind === 'decline' ? 'declined' : 'cancelled';
  const other = kind === 'decline' ? 'cancelled' : 'declined';
  return (ctx) => {
    const rq = S.requestById.get(ctx.params.id);
    if (!rq) throw notFound('no such request');
    const owner = kind === 'decline' ? rq.payer_id : rq.requester_id;
    if (owner !== ctx.user.id) throw forbidden('not permitted for this request');
    if (rq.status === 'pending') rq.status = target;
    else if (rq.status !== target) throw new ApiError(409, 'request_not_pending', 'request is ' + (rq.status === other ? other : rq.status));
    return { status: 200, obj: { ...rq } };
  };
}

function createSplit(ctx) {
  return idempotent(ctx, (b) => {
    const amount = vAmount(b.amount);
    const note = vNote(b.note);
    const ph = b.participant_handles;
    if (ph === undefined) throw invalid('participant_handles is required');
    if (!Array.isArray(ph)) throw bad('participant_handles must be an array');
    for (const h of ph) if (typeof h !== 'string') throw bad('participant_handles must contain strings');
    if (ph.length === 0) throw invalid('participant_handles must not be empty');
    if (new Set(ph).size !== ph.length) throw invalid('duplicate participant handle');
    const users = ph.map(userByHandle);
    const n = users.length;
    const base = Math.floor(amount / n);
    const rem = amount - base * n;
    const createdAt = nowStamp();
    const shares = users.map((u, i) => ({ handle: u.handle, amount: base + (i < rem ? 1 : 0) }));
    const requests = [];
    users.forEach((u, i) => {
      if (u.id !== ctx.user.id) requests.push({ ...addRequest(ctx.user, u, shares[i].amount, note, createdAt) });
    });
    const out = {
      split_id: newSplitId(), amount, currency: S.currency, note, shares, requests, created_at: createdAt,
    };
    S.splits.set(out.split_id, out);
    return out;
  });
}

function createSettlement(ctx) {
  if (!S.operators.has(ctx.user.id)) throw forbidden('settlement operator required');
  return idempotent(ctx, (b) => {
    const t = b.transfers;
    if (!Array.isArray(t) || t.length < 1 || t.length > 32) throw invalid('transfers must be an array of 1 to 32 objects');
    for (const e of t) if (!isObj(e)) throw invalid('each transfer must be an object');
    const entries = t.map((e) => {
      const amount = vAmount(e.amount);
      const note = vNote(e.note);
      const vis = vVisibility(e.visibility);
      const fh = vHandle(e.from_handle, 'from_handle');
      const th = vHandle(e.to_handle, 'to_handle');
      const from = userByHandle(fh);
      const to = userByHandle(th);
      if (from.id === to.id) throw new ApiError(422, 'self_payment', 'cannot transfer to the same wallet');
      return { from, to, amount, note, vis };
    });
    const delta = new Map();
    for (const e of entries) {
      const a = BigInt(e.amount);
      delta.set(e.from, (delta.get(e.from) || 0n) - a);
      delta.set(e.to, (delta.get(e.to) || 0n) + a);
    }
    for (const [u, d] of delta) {
      if (u.balance + d < 0n) throw new ApiError(409, 'insufficient_funds', 'settlement is not affordable');
    }
    const sid = newSettlementId();
    const committedAt = nowStamp();
    for (const [u, d] of delta) u.balance += d;
    const payments = entries.map((e) => ({
      ...addPayment(e.from, e.to, e.amount, e.note, e.vis, null, sid, committedAt),
    }));
    const out = { settlement_id: sid, committed_at: committedAt, payments };
    S.settlements.set(sid, out);
    return out;
  });
}

// ------------------------------------------------------------------- lists
const PLAIN_INT = /^[0-9]+$/;
function pageParams(q) {
  let limit = 50;
  let offset = 0;
  if (q.has('limit')) {
    const s = q.get('limit');
    if (!PLAIN_INT.test(s)) throw invalid('limit must be an integer');
    limit = s.length > 6 ? Infinity : Number(s);
    if (!(limit >= 1 && limit <= 200)) throw invalid('limit out of range');
  }
  if (q.has('offset')) {
    const s = q.get('offset');
    if (!PLAIN_INT.test(s)) throw invalid('offset must be a non-negative integer');
    offset = Number(s);
  }
  return { limit, offset };
}

// Newest first = reverse creation order. Collect `limit` matches after `offset`.
function page(list, match, limit, offset) {
  const out = [];
  let skipped = 0;
  let more = false;
  for (let i = list.length - 1; i >= 0; i--) {
    const it = list[i];
    if (!match(it)) continue;
    if (skipped < offset) { skipped++; continue; }
    if (out.length === limit) { more = true; break; }
    out.push(it);
  }
  return { items: out, more };
}

function activity(ctx) {
  const { limit, offset } = pageParams(ctx.query);
  const uid = ctx.user.id;
  const { items, more } = page(S.payments,
    (p) => p.visibility === 'public' || p.from_user_id === uid || p.to_user_id === uid, limit, offset);
  return { status: 200, obj: { payments: items, has_more: more } };
}

function listRequests(ctx) {
  const q = ctx.query;
  const { limit, offset } = pageParams(q);
  let dir = null;
  let status = null;
  if (q.has('direction')) {
    dir = q.get('direction');
    if (dir !== 'incoming' && dir !== 'outgoing') throw invalid('unknown direction');
  }
  if (q.has('status')) {
    status = q.get('status');
    if (!DAYS_STATUSES.has(status)) throw invalid('unknown status');
  }
  const uid = ctx.user.id;
  const { items, more } = page(S.requests, (r) => {
    if (status && r.status !== status) return false;
    if (dir === 'incoming') return r.payer_id === uid;
    if (dir === 'outgoing') return r.requester_id === uid;
    return r.payer_id === uid || r.requester_id === uid;
  }, limit, offset);
  return { status: 200, obj: { requests: items, has_more: more } };
}

// -------------------------------------------------------------------- auth
function deriveHandle(email) {
  const local = email.slice(0, email.indexOf('@')).toLowerCase();
  return Array.from(local, (c) => (/^[a-z0-9_]$/.test(c) ? c : '_')).join('').slice(0, 20);
}
function validEmail(e) {
  const i = e.indexOf('@');
  return i > 0 && i < e.length - 1 && e.indexOf('@', i + 1) === -1;
}

async function signup(ctx) {
  const b = parseObject(ctx.body);
  for (const f of ['email', 'password', 'display_name']) {
    if (b[f] === undefined) throw invalid(f + ' is required');
  }
  for (const f of ['email', 'password', 'display_name']) {
    if (typeof b[f] !== 'string') throw bad(f + ' must be a string');
  }
  if (!validEmail(b.email)) throw invalid('email must be of the form local@domain');
  if (b.password.length < 16 && Array.from(b.password).length < 8) throw invalid('password must be at least 8 characters');
  if (b.display_name === '') throw invalid('display_name must not be empty');
  const handle = deriveHandle(b.email);
  const check = () => {
    if (S.byEmail.has(b.email)) throw new ApiError(409, 'email_taken', 'email already registered');
    if (S.byHandle.has(handle)) throw new ApiError(409, 'handle_taken', 'handle already taken');
  };
  check();
  const hash = await hashPassword(b.password);
  check(); // state may have changed while hashing
  const user = { id: newUserId(), email: b.email, hash, displayName: b.display_name, handle, balance: 0n };
  S.users.set(user.id, user);
  S.byEmail.set(user.email, user);
  S.byHandle.set(user.handle, user);
  const token = issueToken(user);
  return { status: 201, obj: { user_id: user.id, display_name: user.displayName, token } };
}

function issueToken(user) {
  const t = crypto.randomBytes(24).toString('hex');
  S.tokens.set(t, user.id);
  return t;
}

async function login(ctx) {
  const b = parseObject(ctx.body);
  for (const f of ['email', 'password']) if (b[f] === undefined) throw invalid(f + ' is required');
  for (const f of ['email', 'password']) if (typeof b[f] !== 'string') throw bad(f + ' must be a string');
  const user = S.byEmail.get(b.email);
  const fail = new ApiError(401, 'unauthenticated', 'invalid credentials');
  if (!user) throw fail;
  const hash = user.hash;
  if (!(await verifyPassword(b.password, hash))) throw fail;
  if (S.users.get(user.id) !== user) throw fail; // state replaced meanwhile
  return { status: 200, obj: { user_id: user.id, display_name: user.displayName, token: issueToken(user) } };
}

function authenticate(req) {
  const h = req.headers.authorization;
  const m = typeof h === 'string' ? /^Bearer +(\S+)$/i.exec(h.trim()) : null;
  const uid = m ? S.tokens.get(m[1]) : undefined;
  const user = uid === undefined ? undefined : S.users.get(uid);
  if (!user) throw new ApiError(401, 'unauthenticated', 'missing or invalid bearer token');
  return user;
}

// ----------------------------------------------------- reset / export / import
const isId = (v) => typeof v === 'string' && v.length >= 1 && v.length <= 64;
function intField(v, what, min) {
  if (typeof v !== 'number' || !Number.isInteger(v)) throw invalid(what + ' must be an integer');
  if (v < min) throw invalid(what + ' out of range');
  if (v > MAX_BALANCE) throw invalid(what + ' out of range');
  return v;
}

// Validate a fixture and return a plan (sync); hashing happens afterwards.
function planFixture(f) {
  if (typeof f.currency !== 'string' || f.currency === '') throw invalid('currency is required');
  if (![0, 2, 3].includes(f.minor_units)) throw invalid('minor_units must be 0, 2 or 3');
  if (!Array.isArray(f.users)) throw invalid('users must be an array');
  const optArr = (k) => {
    if (f[k] === undefined || f[k] === null) return [];
    if (!Array.isArray(f[k])) throw invalid(k + ' must be an array');
    return f[k];
  };
  const payments = optArr('payments');
  const requests = optArr('requests');
  const operators = optArr('settlement_operator_ids');
  for (const o of operators) if (typeof o !== 'string') throw invalid('settlement_operator_ids must be strings');
  const ids = new Set();
  const emails = new Set();
  const handles = new Set();
  const users = f.users.map((u) => {
    if (!isObj(u)) throw invalid('user must be an object');
    if (!isId(u.id)) throw invalid('user id invalid');
    if (typeof u.email !== 'string' || !validEmail(u.email)) throw invalid('user email invalid');
    if (typeof u.password !== 'string') throw invalid('user password invalid');
    if (u.display_name !== undefined && typeof u.display_name !== 'string') throw invalid('display_name invalid');
    const handle = u.handle === undefined ? deriveHandle(u.email) : u.handle;
    if (typeof handle !== 'string' || !HANDLE_RE.test(handle)) throw invalid('user handle invalid');
    const balance = intField(u.balance === undefined ? 0 : u.balance, 'balance', 0);
    if (ids.has(u.id) || emails.has(u.email) || handles.has(handle)) throw invalid('duplicate user id, email or handle');
    ids.add(u.id); emails.add(u.email); handles.add(handle);
    return { id: u.id, email: u.email, password: u.password, displayName: u.display_name === undefined ? handle : u.display_name, handle, balance };
  });
  const pids = new Set();
  const pays = payments.map((p) => {
    if (!isObj(p)) throw invalid('payment must be an object');
    if (!isId(p.id) || pids.has(p.id)) throw invalid('payment id invalid or duplicate');
    pids.add(p.id);
    if (!ids.has(p.from_user_id) || !ids.has(p.to_user_id)) throw invalid('payment references an unknown user');
    const amount = intField(p.amount, 'payment amount', 0);
    if (p.note !== undefined && typeof p.note !== 'string') throw invalid('payment note invalid');
    const vis = p.visibility === undefined ? 'public' : p.visibility;
    if (vis !== 'public' && vis !== 'private') throw invalid('payment visibility invalid');
    return { id: p.id, from: p.from_user_id, to: p.to_user_id, amount, note: p.note === undefined ? '' : p.note, vis,
      requestId: isId(p.request_id) ? p.request_id : null };
  });
  const rids = new Set();
  const reqs = requests.map((r) => {
    if (!isObj(r)) throw invalid('request must be an object');
    if (!isId(r.id) || rids.has(r.id)) throw invalid('request id invalid or duplicate');
    rids.add(r.id);
    if (!ids.has(r.requester_id) || !ids.has(r.payer_id)) throw invalid('request references an unknown user');
    const amount = intField(r.amount, 'request amount', 0);
    if (r.note !== undefined && typeof r.note !== 'string') throw invalid('request note invalid');
    const status = r.status === undefined ? 'pending' : r.status;
    if (!DAYS_STATUSES.has(status)) throw invalid('request status invalid');
    return { id: r.id, requester: r.requester_id, payer: r.payer_id, amount, note: r.note === undefined ? '' : r.note, status,
      paymentId: isId(r.payment_id) ? r.payment_id : null };
  });
  return { currency: f.currency, minorUnits: f.minor_units, users, pays, reqs, operators };
}

async function applyFixture(plan) {
  const hashes = await Promise.all(plan.users.map((u) => hashPassword(u.password)));
  const n = emptyState();
  n.currency = plan.currency;
  n.minorUnits = plan.minorUnits;
  plan.users.forEach((u, i) => {
    const user = { id: u.id, email: u.email, hash: hashes[i], displayName: u.displayName, handle: u.handle, balance: BigInt(u.balance) };
    n.users.set(user.id, user);
    n.byEmail.set(user.email, user);
    n.byHandle.set(user.handle, user);
  });
  const old = S;
  S = n;
  const at = nowStamp();
  for (const p of plan.pays) {
    const pay = addPayment(n.users.get(p.from), n.users.get(p.to), p.amount, p.note, p.vis, null, null, at);
    n.paymentById.delete(pay.payment_id);
    pay.payment_id = p.id;
    pay.request_id = p.requestId;
    n.paymentById.set(p.id, pay);
  }
  for (const r of plan.reqs) {
    const rq = addRequest(n.users.get(r.requester), n.users.get(r.payer), r.amount, r.note, at);
    n.requestById.delete(rq.request_id);
    rq.request_id = r.id;
    rq.status = r.status;
    rq.payment_id = r.paymentId;
    n.requestById.set(r.id, rq);
  }
  for (const o of plan.operators) n.operators.add(o);
  n.counters = { u: 0, p: 0, rq: 0, sp: 0, st: 0 };
  void old;
}

function exportState() {
  const s = S;
  return {
    track: 'pocketful',
    format_version: 1,
    state: {
      currency: s.currency,
      minor_units: s.minorUnits,
      users: [...s.users.values()].map((u) => ({
        id: u.id, email: u.email, password_hash: u.hash, display_name: u.displayName, handle: u.handle, balance: u.balance.toString(),
      })),
      tokens: [...s.tokens].map(([token, user_id]) => ({ token, user_id })),
      payments: s.payments,
      requests: s.requests,
      splits: [...s.splits.values()],
      settlements: [...s.settlements.values()],
      operators: [...s.operators],
      idempotency: [...s.idem.values()].map((r) => ({
        user_id: r.user_id, method: r.method, path: r.path, key: r.key, body: r.body, status: r.status, response: JSON.parse(r.response),
      })),
      counters: s.counters,
    },
  };
}

function buildImported(st) {
  const V = (c, m) => { if (!c) throw invalid('invalid state: ' + m); };
  V(isObj(st), 'state must be an object');
  V(typeof st.currency === 'string' && st.currency !== '', 'currency');
  V([0, 2, 3].includes(st.minor_units), 'minor_units');
  for (const k of ['users', 'tokens', 'payments', 'requests', 'splits', 'settlements', 'operators', 'idempotency']) {
    V(Array.isArray(st[k]), k);
  }
  V(isObj(st.counters), 'counters');
  const n = emptyState();
  n.currency = st.currency;
  n.minorUnits = st.minor_units;
  for (const k of Object.keys(n.counters)) {
    const c = st.counters[k];
    V(Number.isSafeInteger(c) && c >= 0, 'counters.' + k);
    n.counters[k] = c;
  }
  for (const u of st.users) {
    V(isObj(u) && isId(u.id) && typeof u.email === 'string' && typeof u.display_name === 'string', 'user');
    V(typeof u.handle === 'string' && HANDLE_RE.test(u.handle), 'user handle');
    V(typeof u.password_hash === 'string' && HASH_RE.test(u.password_hash), 'password_hash');
    V(typeof u.balance === 'string' && /^(0|[1-9][0-9]*)$/.test(u.balance), 'balance');
    V(!n.users.has(u.id) && !n.byEmail.has(u.email) && !n.byHandle.has(u.handle), 'duplicate user');
    const user = { id: u.id, email: u.email, hash: u.password_hash, displayName: u.display_name, handle: u.handle, balance: BigInt(u.balance) };
    n.users.set(user.id, user);
    n.byEmail.set(user.email, user);
    n.byHandle.set(user.handle, user);
  }
  for (const t of st.tokens) {
    V(isObj(t) && typeof t.token === 'string' && n.users.has(t.user_id), 'token');
    n.tokens.set(t.token, t.user_id);
  }
  const strKeys = ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'currency', 'note', 'visibility', 'created_at'];
  for (const p of st.payments) {
    V(isObj(p), 'payment');
    for (const k of strKeys) V(typeof p[k] === 'string', 'payment.' + k);
    V(Number.isSafeInteger(p.amount) && p.amount >= 0, 'payment.amount');
    V(p.visibility === 'public' || p.visibility === 'private', 'payment.visibility');
    V(p.request_id === null || typeof p.request_id === 'string', 'payment.request_id');
    V(p.settlement_id === null || typeof p.settlement_id === 'string', 'payment.settlement_id');
    V(n.users.has(p.from_user_id) && n.users.has(p.to_user_id) && !n.paymentById.has(p.payment_id), 'payment refs');
    const pay = {};
    for (const k of strKeys.slice(0, 5)) pay[k] = p[k];
    Object.assign(pay, { amount: p.amount, currency: p.currency, note: p.note, visibility: p.visibility,
      request_id: p.request_id, settlement_id: p.settlement_id, created_at: p.created_at });
    n.payments.push(pay);
    n.paymentById.set(pay.payment_id, pay);
  }
  const rkeys = ['request_id', 'requester_id', 'requester_handle', 'payer_id', 'payer_handle', 'currency', 'note', 'status', 'created_at'];
  for (const r of st.requests) {
    V(isObj(r), 'request');
    for (const k of rkeys) V(typeof r[k] === 'string', 'request.' + k);
    V(Number.isSafeInteger(r.amount) && r.amount >= 0, 'request.amount');
    V(DAYS_STATUSES.has(r.status), 'request.status');
    V(r.payment_id === null || typeof r.payment_id === 'string', 'request.payment_id');
    V(n.users.has(r.requester_id) && n.users.has(r.payer_id) && !n.requestById.has(r.request_id), 'request refs');
    const rq = {
      request_id: r.request_id, requester_id: r.requester_id, requester_handle: r.requester_handle,
      payer_id: r.payer_id, payer_handle: r.payer_handle, amount: r.amount, currency: r.currency,
      note: r.note, status: r.status, payment_id: r.payment_id, created_at: r.created_at,
    };
    n.requests.push(rq);
    n.requestById.set(rq.request_id, rq);
  }
  for (const [list, map, idk] of [[st.splits, n.splits, 'split_id'], [st.settlements, n.settlements, 'settlement_id']]) {
    for (const x of list) {
      V(isObj(x) && typeof x[idk] === 'string' && !map.has(x[idk]), idk);
      map.set(x[idk], x);
    }
  }
  for (const o of st.operators) { V(typeof o === 'string', 'operator'); n.operators.add(o); }
  for (const r of st.idempotency) {
    V(isObj(r) && typeof r.user_id === 'string' && typeof r.method === 'string' && typeof r.path === 'string' &&
      typeof r.key === 'string' && isObj(r.body) && r.status === 201 && r.response !== undefined, 'idempotency record');
    const composite = r.user_id + '\n' + r.method + ' ' + r.path + '\n' + r.key;
    V(!n.idem.has(composite), 'duplicate idempotency record');
    n.idem.set(composite, { user_id: r.user_id, method: r.method, path: r.path, key: r.key, body: r.body, status: 201, response: JSON.stringify(r.response) });
  }
  return n;
}

// Reset and import share one queue so state swaps happen in arrival order.
let controlChain = Promise.resolve();
function serialized(fn) {
  const p = controlChain.then(fn);
  controlChain = p.catch(() => {});
  return p;
}

async function reset(ctx) {
  const f = parseObject(ctx.body);
  const plan = planFixture(f);
  await serialized(() => applyFixture(plan));
  return { status: 204 };
}
function exportRoute() {
  return { status: 200, json: JSON.stringify(exportState()) };
}
async function importRoute(ctx) {
  const b = parseObject(ctx.body);
  if (b.track !== 'pocketful') throw invalid('wrong track');
  if (b.format_version !== 1) throw invalid('unsupported format_version');
  if (b.state === undefined) throw invalid('state is required');
  await serialized(async () => { S = buildImported(b.state); });
  return { status: 204 };
}

// ------------------------------------------------------------------ routing
const ROUTES = [
  ['GET', /^\/health$/, false, () => ({ status: 200, obj: { status: 'ok' } })],
  ['POST', /^\/_test\/reset$/, false, reset, 'control'],
  ['GET', /^\/_test\/export$/, false, exportRoute],
  ['POST', /^\/_test\/import$/, false, importRoute, 'control'],
  ['POST', /^\/auth\/signup$/, false, signup],
  ['POST', /^\/auth\/login$/, false, login],
  ['GET', /^\/me$/, true, me],
  ['POST', /^\/payments$/, true, createPayment],
  ['POST', /^\/requests$/, true, createRequest],
  ['GET', /^\/requests$/, true, listRequests],
  ['POST', /^\/requests\/([^/]+)\/pay$/, true, payRequest],
  ['POST', /^\/requests\/([^/]+)\/decline$/, true, decideRequest('decline')],
  ['POST', /^\/requests\/([^/]+)\/cancel$/, true, decideRequest('cancel')],
  ['POST', /^\/splits$/, true, createSplit],
  ['GET', /^\/activity$/, true, activity],
  ['POST', /^\/settlements$/, true, createSettlement],
];

function readBody(req, limit) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) { tooLarge = true; chunks.length = 0; } else if (!tooLarge) chunks.push(c);
    });
    req.on('end', () => resolve({ buf: Buffer.concat(chunks), tooLarge }));
    req.on('error', () => resolve({ buf: Buffer.alloc(0), tooLarge: false }));
    req.on('aborted', () => resolve({ buf: Buffer.alloc(0), tooLarge: false }));
  });
}

function send(res, status, json) {
  if (status === 204) {
    res.writeHead(204);
    return res.end();
  }
  const buf = Buffer.from(json, 'utf8');
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': buf.length });
  res.end(buf);
}
const sendError = (res, e) => send(res, e.status, JSON.stringify({ error: { code: e.code, message: e.message } }));

async function handle(req, res) {
  try {
    let url;
    try {
      url = new URL(req.url, 'http://localhost');
    } catch (e) {
      await readBody(req, 0);
      throw notFound('no such route');
    }
    const path = url.pathname;
    let route = null;
    let params = null;
    for (const r of ROUTES) {
      if (r[0] !== req.method) continue;
      const m = r[1].exec(path);
      if (m) {
        route = r;
        let id = m[1];
        if (id !== undefined) { try { id = decodeURIComponent(id); } catch (e) { /* keep raw */ } }
        params = { id };
        break;
      }
    }
    const body = await readBody(req, route && route[4] === 'control' ? CONTROL_BODY_LIMIT : BODY_LIMIT);
    if (!route) throw notFound('no such route');
    const ctx = { req, res, path, query: url.searchParams, params, body, user: null };
    if (route[2]) ctx.user = authenticate(req);
    const out = await route[3](ctx);
    send(res, out.status, out.json !== undefined ? out.json : out.obj !== undefined ? JSON.stringify(out.obj) : '');
  } catch (e) {
    if (e instanceof ApiError) return sendError(res, e);
    console.error(e);
    sendError(res, new ApiError(500, 'internal_error', 'internal error'));
  }
}

const server = http.createServer({ maxHeaderSize: 64 * 1024 }, handle);
server.keepAliveTimeout = 65000;
server.headersTimeout = 66000;
server.requestTimeout = 0;
server.on('clientError', (err, socket) => {
  if (!socket.writable) return;
  const body = JSON.stringify({ error: { code: 'malformed_request', message: 'bad HTTP request' } });
  socket.end(`HTTP/1.1 400 Bad Request\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`);
});
process.on('uncaughtException', (e) => console.error('uncaught', e));
process.on('unhandledRejection', (e) => console.error('unhandled', e));

let port = parseInt(process.env.PORT, 10);
if (!(port >= 1 && port <= 65535)) port = 8080;
server.listen(port, '0.0.0.0', () => console.log('pocketful stage-1 listening on ' + port));
