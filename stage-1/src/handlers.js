'use strict';
const crypto = require('crypto');
const U = require('./util');
const { err, isObject } = U;
const S = require('./store');
const { store } = S;

// A handler returns { status, json } (json is an already serialised string) or { status: 204 }.
const ok = (status, obj) => ({ status, json: JSON.stringify(obj) });

// ---------- views ----------

function paymentView(s, p) {
  return {
    payment_id: p.id,
    from_user_id: p.from,
    from_handle: s.users.get(p.from).handle,
    to_user_id: p.to,
    to_handle: s.users.get(p.to).handle,
    amount: p.amount,
    currency: s.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.request_id,
    settlement_id: p.settlement_id,
    created_at: U.iso(p.ts),
  };
}

function requestView(s, r) {
  return {
    request_id: r.id,
    requester_id: r.requester,
    requester_handle: s.users.get(r.requester).handle,
    payer_id: r.payer,
    payer_handle: s.users.get(r.payer).handle,
    amount: r.amount,
    currency: s.currency,
    note: r.note,
    status: r.status,
    payment_id: r.payment_id,
    created_at: U.iso(r.ts),
  };
}

// ---------- shared pieces ----------

function authenticate(headers) {
  const h = headers.authorization;
  const m = typeof h === 'string' ? /^Bearer (\S+)$/i.exec(h) : null;
  if (!m) throw err.unauthenticated();
  const s = store.s;
  const uid = s.tokens.get(m[1]);
  const user = uid === undefined ? undefined : s.users.get(uid);
  if (!user) throw err.unauthenticated();
  return user;
}

function newToken(s, user) {
  const token = crypto.randomBytes(24).toString('hex');
  s.tokens.set(token, user.id);
  return token;
}

function parseJsonBody(ctx, { allowEmpty = false } = {}) {
  const raw = ctx.rawBody;
  if (raw.length === 0 && allowEmpty) return {};
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  } catch (e) {
    throw err.malformed('body is not valid UTF-8');
  }
  let v;
  try {
    v = JSON.parse(text);
  } catch (e) {
    throw err.malformed('body is not valid JSON');
  }
  if (!isObject(v)) throw err.malformed('body must be a JSON object');
  return v;
}

function parsePaging(q) {
  return { limit: U.parseQueryInt(q, 'limit', 50, 1, 200), offset: U.parseQueryInt(q, 'offset', 0, 0, Infinity) };
}

function page(items, { limit, offset }) {
  return { slice: items.slice(offset, offset + limit), hasMore: offset + limit < items.length };
}

function newestFirst(list) {
  return list.slice().sort((a, b) => (b.ts - a.ts) || (b.seq - a.seq));
}

// Runs `exec` once per (user, path, key). A claimed key is resolved before any field validation.
function idempotent(ctx, user, body, exec) {
  const key = ctx.headers['idempotency-key'];
  if (key === undefined || key === '') throw err.missingKey();
  if (U.charLength(key) > 255) throw err.validation('Idempotency-Key longer than 255 characters');
  let canon;
  try {
    canon = U.canonical(body);
  } catch (e) {
    throw err.malformed('body too deeply nested');
  }
  const s = store.s;
  const ck = JSON.stringify([user.id, ctx.path, key]);
  const rec = s.idem.get(ck);
  if (rec) {
    if (rec.body === canon) return { status: 200, json: rec.response };
    throw err.conflict('idempotency_key_reuse', 'Idempotency-Key was used with a different request body');
  }
  const result = exec(s);
  const json = JSON.stringify(result);
  s.idem.set(ck, { user_id: user.id, method: 'POST', path: ctx.path, key, body: canon, response: json });
  return { status: 201, json };
}

function recordPayment(s, from, to, amount, note, visibility, requestId, settlementId, ts) {
  const p = { id: S.nextId(s, 'p', (id) => s.paymentIndex.has(id)), from: from.id, to: to.id, amount, note, visibility,
    request_id: requestId, settlement_id: settlementId, ts, seq: s.seq++ };
  from.balance -= amount;
  to.balance += amount;
  s.payments.push(p);
  s.paymentIndex.set(p.id, p);
  return p;
}

function recordRequest(s, requester, payer, amount, note, ts) {
  const r = { id: S.nextId(s, 'rq', (id) => s.requestIndex.has(id)), requester: requester.id, payer: payer.id, amount, note,
    status: 'pending', payment_id: null, ts, seq: s.seq++ };
  s.requests.push(r);
  s.requestIndex.set(r.id, r);
  return r;
}

// ---------- health and test control ----------

function health() {
  return ok(200, { status: 'ok' });
}

async function reset(ctx) {
  const fx = parseJsonBody(ctx, { allowEmpty: true });
  store.s = await S.buildFromFixture(fx);
  return { status: 204 };
}

function exportState() {
  const state = JSON.stringify(S.serialize(store.s));
  return { status: 200, json: '{"track":"pocketful","format_version":1,"state":' + state + '}' };
}

function importState(ctx) {
  const body = parseJsonBody(ctx);
  if (body.track !== 'pocketful') throw err.validation('track must be "pocketful"');
  if (body.format_version !== 1) throw err.validation('format_version must be 1');
  if (!isObject(body.state)) throw err.validation('state is required');
  store.s = S.deserialize(body.state);
  return { status: 204 };
}

// ---------- auth ----------

function deriveHandle(email) {
  const local = email.slice(0, email.indexOf('@'));
  return local.toLowerCase().replace(/[^a-z0-9_]/gu, '_').slice(0, 20);
}

async function signup(ctx) {
  const body = parseJsonBody(ctx);
  for (const f of ['email', 'password', 'display_name']) {
    if (body[f] !== undefined && typeof body[f] !== 'string') throw err.malformed(f + ' must be a string');
  }
  for (const f of ['email', 'password', 'display_name']) {
    if (body[f] === undefined) throw err.validation(f + ' is required');
  }
  const { email, password, display_name } = body;
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) throw err.validation('email must be of the form local@domain');
  if (U.charLength(password) < 8) throw err.validation('password must be at least 8 characters');
  if (display_name === '') throw err.validation('display_name must not be empty');
  const handle = deriveHandle(email);
  const quick = store.s;
  if (quick.emailIndex.has(email)) throw err.conflict('email_taken', 'email already registered');
  if (quick.handleIndex.has(handle)) throw err.conflict('handle_taken', 'handle already taken');
  const hashed = await S.hashPassword(password);
  // Re-check on the live state: another signup or a reset may have run while hashing.
  const s = store.s;
  if (s.emailIndex.has(email)) throw err.conflict('email_taken', 'email already registered');
  if (s.handleIndex.has(handle)) throw err.conflict('handle_taken', 'handle already taken');
  const user = { id: S.nextId(s, 'u', (id) => s.users.has(id)), email, display_name, handle, balance: 0, password: hashed };
  s.users.set(user.id, user);
  s.emailIndex.set(email, user);
  s.handleIndex.set(handle, user);
  return ok(201, { user_id: user.id, display_name: user.display_name, token: newToken(s, user) });
}

async function login(ctx) {
  const body = parseJsonBody(ctx);
  for (const f of ['email', 'password']) {
    if (body[f] !== undefined && typeof body[f] !== 'string') throw err.malformed(f + ' must be a string');
  }
  for (const f of ['email', 'password']) {
    if (body[f] === undefined) throw err.validation(f + ' is required');
  }
  const user = store.s.emailIndex.get(body.email);
  const good = user ? await S.verifyPassword(body.password, user.password) : false;
  if (!good) throw err.unauthenticated('wrong email or password');
  const s = store.s;
  if (s.users.get(user.id) !== user) throw err.unauthenticated('wrong email or password');
  return ok(200, { user_id: user.id, display_name: user.display_name, token: newToken(s, user) });
}

// ---------- wallet ----------

function me(ctx, user) {
  const s = store.s;
  return ok(200, { user_id: user.id, display_name: user.display_name, handle: user.handle, balance: user.balance,
    currency: s.currency, minor_units: s.minorUnits });
}

function createPayment(ctx, user) {
  const body = parseJsonBody(ctx);
  return idempotent(ctx, user, body, (s) => {
    const amount = U.parseAmount(body.amount);
    const note = U.parseNote(body.note);
    const visibility = U.parseVisibility(body.visibility);
    const toHandle = U.requiredString(body, 'to_handle');
    if (toHandle === user.handle) throw err.unprocessable('self_payment', 'cannot pay yourself');
    const to = s.handleIndex.get(toHandle);
    if (!to) throw err.notFound('no user with that handle');
    if (user.balance < amount) throw err.conflict('insufficient_funds', 'balance is below the amount');
    return paymentView(s, recordPayment(s, user, to, amount, note, visibility, null, null, Date.now()));
  });
}

function createRequest(ctx, user) {
  const body = parseJsonBody(ctx);
  return idempotent(ctx, user, body, (s) => {
    const amount = U.parseAmount(body.amount);
    const note = U.parseNote(body.note);
    const payerHandle = U.requiredString(body, 'payer_handle');
    if (payerHandle === user.handle) throw err.unprocessable('self_request', 'cannot request money from yourself');
    const payer = s.handleIndex.get(payerHandle);
    if (!payer) throw err.notFound('no user with that handle');
    return requestView(s, recordRequest(s, user, payer, amount, note, Date.now()));
  });
}

function payRequest(ctx, user) {
  const body = parseJsonBody(ctx, { allowEmpty: true });
  return idempotent(ctx, user, body, (s) => {
    const visibility = U.parseVisibility(body.visibility);
    const rq = s.requestIndex.get(ctx.params.id);
    if (!rq) throw err.notFound('no such request');
    if (rq.payer !== user.id) throw err.forbidden('only the payer may pay this request');
    if (rq.status !== 'pending') throw err.conflict('request_not_pending', 'request is ' + rq.status);
    if (user.balance < rq.amount) throw err.conflict('insufficient_funds', 'balance is below the amount');
    const to = s.users.get(rq.requester);
    const p = recordPayment(s, user, to, rq.amount, rq.note, visibility, rq.id, null, Date.now());
    rq.status = 'paid';
    rq.payment_id = p.id;
    return paymentView(s, p);
  });
}

function transition(target, role) {
  return (ctx, user) => {
    const s = store.s;
    const rq = s.requestIndex.get(ctx.params.id);
    if (!rq) throw err.notFound('no such request');
    if (rq[role] !== user.id) throw err.forbidden('only the ' + role + ' may do this');
    if (rq.status === 'pending') rq.status = target;
    else if (rq.status !== target) throw err.conflict('request_not_pending', 'request is ' + rq.status);
    return ok(200, requestView(s, rq));
  };
}

const declineRequest = transition('declined', 'payer');
const cancelRequest = transition('cancelled', 'requester');

function listRequests(ctx, user) {
  const s = store.s;
  const q = ctx.query;
  const direction = q.get('direction');
  if (direction !== null && direction !== 'incoming' && direction !== 'outgoing') throw err.validation('invalid direction');
  const status = q.get('status');
  if (status !== null && !['pending', 'paid', 'declined', 'cancelled'].includes(status)) throw err.validation('invalid status');
  const paging = parsePaging(q);
  const mine = s.requests.filter((r) => {
    if (direction === 'incoming') { if (r.payer !== user.id) return false; }
    else if (direction === 'outgoing') { if (r.requester !== user.id) return false; }
    else if (r.payer !== user.id && r.requester !== user.id) return false;
    return status === null || r.status === status;
  });
  const { slice, hasMore } = page(newestFirst(mine), paging);
  return ok(200, { requests: slice.map((r) => requestView(s, r)), has_more: hasMore });
}

function listActivity(ctx, user) {
  const s = store.s;
  const paging = parsePaging(ctx.query);
  const visible = s.payments.filter((p) => p.visibility === 'public' || p.from === user.id || p.to === user.id);
  const { slice, hasMore } = page(newestFirst(visible), paging);
  return ok(200, { payments: slice.map((p) => paymentView(s, p)), has_more: hasMore });
}

// ---------- splits ----------

function createSplit(ctx, user) {
  const body = parseJsonBody(ctx);
  return idempotent(ctx, user, body, (s) => {
    const amount = U.parseAmount(body.amount);
    const note = U.parseNote(body.note);
    const handles = body.participant_handles;
    if (handles === undefined) throw err.validation('participant_handles is required');
    if (!Array.isArray(handles)) throw err.malformed('participant_handles must be an array');
    if (handles.some((h) => typeof h !== 'string')) throw err.malformed('participant_handles must contain strings');
    if (handles.length === 0) throw err.validation('participant_handles must not be empty');
    if (new Set(handles).size !== handles.length) throw err.validation('participant_handles contains a duplicate');
    const people = handles.map((h) => s.handleIndex.get(h));
    if (people.some((p) => !p)) throw err.notFound('unknown participant handle');
    const n = handles.length;
    const base = Math.floor(amount / n);
    const extra = amount % n;
    const shares = handles.map((handle, i) => ({ handle, amount: base + (i < extra ? 1 : 0) }));
    const ts = Date.now();
    const requests = [];
    people.forEach((person, i) => {
      if (person.id !== user.id) requests.push(recordRequest(s, user, person, shares[i].amount, note, ts));
    });
    const id = S.nextId(s, 'sp', (x) => s.splits.some((sp) => sp.id === x));
    s.splits.push({ id, requester: user.id, amount, note, shares, request_ids: requests.map((r) => r.id), ts });
    return { split_id: id, amount, currency: s.currency, note, shares, requests: requests.map((r) => requestView(s, r)),
      created_at: U.iso(ts) };
  });
}

// ---------- settlements ----------

function createSettlement(ctx, user) {
  if (!store.s.operators.has(user.id)) throw err.forbidden('settlements require an operator');
  const body = parseJsonBody(ctx);
  return idempotent(ctx, user, body, (s) => {
    const transfers = body.transfers;
    if (!Array.isArray(transfers) || transfers.length < 1 || transfers.length > 32) {
      throw err.validation('transfers must be an array of 1 to 32 objects');
    }
    const entries = [];
    for (const t of transfers) {
      if (!isObject(t)) throw err.validation('each transfer must be an object');
      const amount = U.parseAmount(t.amount);
      const note = U.parseNote(t.note);
      const visibility = U.parseVisibility(t.visibility);
      const fromHandle = U.requiredString(t, 'from_handle');
      const toHandle = U.requiredString(t, 'to_handle');
      if (fromHandle === toHandle) throw err.unprocessable('self_payment', 'cannot transfer to the same wallet');
      const from = s.handleIndex.get(fromHandle);
      const to = s.handleIndex.get(toHandle);
      if (!from || !to) throw err.notFound('unknown handle in transfer');
      entries.push({ from, to, amount, note, visibility });
    }
    const delta = new Map();
    for (const e of entries) {
      delta.set(e.from, (delta.get(e.from) || 0) - e.amount);
      delta.set(e.to, (delta.get(e.to) || 0) + e.amount);
    }
    for (const [u, d] of delta) {
      if (u.balance + d < 0) throw err.conflict('insufficient_funds', 'settlement is not affordable');
    }
    const ts = Date.now();
    const id = S.nextId(s, 'st', (x) => s.settlements.some((m) => m.id === x));
    const payments = entries.map((e) => recordPayment(s, e.from, e.to, e.amount, e.note, e.visibility, null, id, ts));
    s.settlements.push({ id, operator: user.id, ts, payment_ids: payments.map((p) => p.id) });
    return { settlement_id: id, committed_at: U.iso(ts), payments: payments.map((p) => paymentView(s, p)) };
  });
}

module.exports = {
  authenticate, health, reset, exportState, importState, signup, login, me,
  createPayment, createRequest, payRequest, declineRequest, cancelRequest,
  listRequests, listActivity, createSplit, createSettlement,
};
