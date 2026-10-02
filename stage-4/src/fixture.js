'use strict';

/** Reset fixtures: validate everything first, then build a complete new state. */

const { invalid } = require('./errors');
const { isObject } = require('./json');
const { emptyState } = require('./state');
const { hashPassword } = require('./passwords');
const { HANDLE_RE } = require('./validation');
const { deriveHandle } = require('./handles');
const { nowMs, formatTimestamp } = require('./clock');
const I = require('./instant');
const { appendPayment } = require('./ledger');

const msOf = (text) => {
  const p = I.parse(text);
  return p === null ? null : p.ms;
};
const { addAuthorization, sweep } = require('./holds');

const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];

const { MAX_BALANCE, REQUEST_STATUSES: STATUSES } = require('./constants');
const MINOR_UNITS = [0, 2, 3];

const isId = (v) => typeof v === 'string' && v.length >= 1 && v.length <= 64;
const isMoney = (v) => Number.isInteger(v) && v >= 0 && v <= MAX_BALANCE;

function list(fixture, key) {
  const v = fixture[key];
  if (v === undefined) return [];
  if (!Array.isArray(v)) throw invalid(`${key} must be an array`);
  return v;
}

function parseUser(u, seen) {
  if (!isObject(u)) throw invalid('user must be an object');
  if (!isId(u.id)) throw invalid('user id must be a non-empty string of at most 64 characters');
  for (const k of ['email', 'password', 'display_name']) {
    if (typeof u[k] !== 'string') throw invalid(`user ${k} must be a string`);
  }
  const handle = u.handle === undefined ? deriveHandle(u.email) : u.handle;
  if (typeof handle !== 'string' || !HANDLE_RE.test(handle)) throw invalid('user handle is invalid');
  const balance = u.balance === undefined ? 0 : u.balance;
  if (typeof balance !== 'number' || !Number.isInteger(balance)) throw invalid('balance must be an integer');
  if (balance < 0 || balance > MAX_BALANCE) throw invalid('balance out of range');
  if (seen.ids.has(u.id) || seen.handles.has(handle) || seen.emails.has(u.email)) {
    throw invalid('duplicate user id, handle or email');
  }
  seen.ids.add(u.id);
  seen.handles.add(handle);
  seen.emails.add(u.email);
  return { id: u.id, email: u.email, display_name: u.display_name, handle, balance, password: u.password };
}

/** Seeded authorizations; an unexpired open hold counts against the payer's balance. */
function parseAuthorizations(entries, seen, ttl, users) {
  const now = nowMs();
  const ids = new Set();
  const held = new Map();
  const parsed = entries.map((e) => {
    if (!isObject(e) || !isId(e.id) || ids.has(e.id)) throw invalid('authorization needs a unique id');
    ids.add(e.id);
    if (!seen.ids.has(e.from_user_id) || !seen.ids.has(e.to_user_id)) throw invalid('authorization names an unknown user');
    if (!Number.isInteger(e.amount) || e.amount < 1 || e.amount > 1000000000) throw invalid('authorization amount is invalid');
    if (e.note !== undefined && typeof e.note !== 'string') throw invalid('authorization note must be a string');
    if (e.visibility !== undefined && e.visibility !== 'public' && e.visibility !== 'private') {
      throw invalid('authorization visibility is invalid');
    }
    const status = e.status === undefined ? 'open' : e.status;
    if (!AUTH_STATUSES.includes(status)) throw invalid('authorization status is invalid');
    const createdMs = e.created_at === undefined ? undefined : msOf(e.created_at);
    const expiresMs = e.expires_at === undefined ? undefined : msOf(e.expires_at);
    if (createdMs === null || expiresMs === null) throw invalid('authorization timestamps must be RFC 3339');
    if (createdMs !== undefined && createdMs > now) throw invalid('authorization created_at lies in the future');
    const captured = e.captured_amount === undefined ? (status === 'captured' ? e.amount : 0) : e.captured_amount;
    if (!Number.isInteger(captured) || captured < 0 || captured > e.amount) throw invalid('captured_amount is invalid');
    if (e.payment_id !== undefined && e.payment_id !== null && !isId(e.payment_id)) throw invalid('payment_id is invalid');
    const paymentIds = e.payment_ids === undefined ? (e.payment_id ? [e.payment_id] : []) : e.payment_ids;
    if (!Array.isArray(paymentIds) || !paymentIds.every(isId)) throw invalid('payment_ids must be an array of ids');
    if (status === 'open' && (expiresMs === undefined ? now + ttl * 1000 : expiresMs) > now) {
      held.set(e.from_user_id, (held.get(e.from_user_id) || 0) + e.amount - captured);
    }
    return { e, status, createdMs, expiresMs, captured, paymentIds };
  });
  for (const [id, total] of held) {
    if (total > users.find((u) => u.id === id).balance) throw invalid('open holds exceed the wallet balance');
  }
  return parsed;
}

/** Throws 422 validation_failed unless the fixture is entirely well formed. */
function parseFixture(f) {
  if (!isObject(f)) throw invalid('fixture must be a JSON object');
  const currency = f.currency === undefined ? 'EUR' : f.currency;
  if (typeof currency !== 'string' || currency === '') throw invalid('currency must be a non-empty string');
  const minorUnits = f.minor_units === undefined ? 2 : f.minor_units;
  if (!MINOR_UNITS.includes(minorUnits)) throw invalid('minor_units must be 0, 2 or 3');

  const seen = { ids: new Set(), handles: new Set(), emails: new Set() };
  const users = list(f, 'users').map((u) => parseUser(u, seen));

  const payments = list(f, 'payments').map((p) => {
    if (!isObject(p) || !isId(p.id)) throw invalid('payment needs an id');
    if (!seen.ids.has(p.from_user_id) || !seen.ids.has(p.to_user_id)) throw invalid('payment names an unknown user');
    if (!isMoney(p.amount)) throw invalid('payment amount must be a nonnegative integer');
    if (p.note !== undefined && typeof p.note !== 'string') throw invalid('payment note must be a string');
    if (p.visibility !== undefined && p.visibility !== 'public' && p.visibility !== 'private') {
      throw invalid('payment visibility is invalid');
    }
    if (p.created_at !== undefined) {
      const at = I.parse(p.created_at);
      if (at === null) throw invalid('payment created_at must be an RFC 3339 instant with an offset');
      if (at.ms > nowMs()) throw invalid('payment created_at lies in the future');
    }
    return p;
  });
  if (new Set(payments.map((p) => p.id)).size !== payments.length) throw invalid('duplicate payment id');

  const requests = list(f, 'requests').map((r) => {
    if (!isObject(r) || !isId(r.id)) throw invalid('request needs an id');
    if (!seen.ids.has(r.requester_id) || !seen.ids.has(r.payer_id)) throw invalid('request names an unknown user');
    if (!isMoney(r.amount)) throw invalid('request amount must be a nonnegative integer');
    if (r.note !== undefined && typeof r.note !== 'string') throw invalid('request note must be a string');
    if (!STATUSES.includes(r.status === undefined ? 'pending' : r.status)) throw invalid('request status is invalid');
    if (r.payment_id !== undefined && r.payment_id !== null && !isId(r.payment_id)) throw invalid('payment_id is invalid');
    return r;
  });
  if (new Set(requests.map((r) => r.id)).size !== requests.length) throw invalid('duplicate request id');

  const operators = list(f, 'settlement_operator_ids');
  for (const id of operators) if (typeof id !== 'string' || !seen.ids.has(id)) throw invalid('operator names an unknown user');

  const ttl = f.authorization_ttl_seconds === undefined ? 600 : f.authorization_ttl_seconds;
  if (typeof ttl !== 'number' || !Number.isInteger(ttl) || ttl < 1) {
    throw invalid('authorization_ttl_seconds must be a positive integer');
  }
  const authorizations = parseAuthorizations(list(f, 'authorizations'), seen, ttl, users);

  return { currency, minorUnits, users, payments, requests, operators, ttl, authorizations };
}

/** Build a fresh state from a parsed fixture (hashes passwords concurrently). */
async function buildState(plan) {
  const hashes = await Promise.all(plan.users.map((u) => hashPassword(u.password)));
  const resetMs = nowMs();
  const resetAt = formatTimestamp(resetMs);
  const state = emptyState();
  state.currency = plan.currency;
  state.minorUnits = plan.minorUnits;
  plan.users.forEach((u, i) => {
    const user = {
      id: u.id,
      email: u.email,
      display_name: u.display_name,
      handle: u.handle,
      balance: u.balance,
      held: 0,
      opening_balance: u.balance, // adjusted below once the seeded payments are known
      password: hashes[i],
    };
    state.users.set(user.id, user);
    state.byHandle.set(user.handle, user);
    state.byEmail.set(user.email, user);
    state.seededTotal += u.balance;
  });
  // Seeded payments are already inside the seeded balances: the opening balance is what the
  // wallet held before they moved, so the balances are not touched.
  for (const p of plan.payments) {
    appendPayment(state, {
      id: p.id, from: p.from_user_id, to: p.to_user_id, amount: p.amount,
      note: p.note === undefined ? '' : p.note,
      visibility: p.visibility === undefined ? 'public' : p.visibility,
      createdAt: p.created_at === undefined ? resetAt : p.created_at, seeded: true,
    });
    state.users.get(p.from_user_id).opening_balance += p.amount;
    state.users.get(p.to_user_id).opening_balance -= p.amount;
  }
  for (const r of plan.requests) {
    const request = {
      id: r.id, requester: r.requester_id, payer: r.payer_id, amount: r.amount,
      note: r.note === undefined ? '' : r.note,
      status: r.status === undefined ? 'pending' : r.status,
      payment_id: r.payment_id === undefined ? null : r.payment_id,
      created_at: resetAt,
    };
    state.requests.push(request);
    state.requestsById.set(request.id, request);
  }
  for (const id of plan.operators) state.operators.add(id);
  state.authTtlSeconds = plan.ttl;
  for (const { e, status, createdMs, expiresMs, captured, paymentIds } of plan.authorizations) {
    const created = createdMs === undefined ? resetMs : createdMs;
    const expires = expiresMs === undefined ? created + plan.ttl * 1000 : expiresMs;
    const createdAt = e.created_at === undefined ? resetAt : e.created_at;
    const expiresAt = e.expires_at === undefined ? formatTimestamp(expires) : e.expires_at;
    const lastCapture = paymentIds.map((id) => state.paymentsById.get(id)).filter(Boolean).pop();
    const closedAt = { open: null, expired: expiresAt, captured: lastCapture ? lastCapture.created_at : createdAt, voided: createdAt }[status];
    addAuthorization(state, {
      id: e.id, from: e.from_user_id, to: e.to_user_id, amount: e.amount, captured_amount: captured,
      status, note: e.note === undefined ? '' : e.note,
      visibility: e.visibility === undefined ? 'public' : e.visibility,
      expires_at: expiresAt, expires_ms: expires,
      payment_id: e.payment_id === undefined ? (paymentIds.length ? paymentIds[paymentIds.length - 1] : null) : e.payment_id,
      payment_ids: paymentIds, seeded: true, closed_at: closedAt,
      no_history: status !== 'open' || expires <= resetMs, // a seeded closed hold has no lifecycle to replay
      created_at: createdAt,
    });
  }
  sweep(state, resetMs); // a seeded open hold whose deadline has passed is expired
  state.clockFloor = resetMs + 1; // every later timestamp is strictly after the reset instant
  return state;
}

module.exports = { parseFixture, buildState };
