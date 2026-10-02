'use strict';

/** Reset fixtures: validate everything first, then build a complete new state. */

const { invalid } = require('./errors');
const { isObject } = require('./json');
const { emptyState } = require('./state');
const { hashPassword } = require('./passwords');
const { nowTimestamp } = require('./clock');
const { HANDLE_RE } = require('./validation');
const { deriveHandle } = require('./handles');

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

  return { currency, minorUnits, users, payments, requests, operators };
}

/** Build a fresh state from a parsed fixture (hashes passwords concurrently). */
async function buildState(plan) {
  const hashes = await Promise.all(plan.users.map((u) => hashPassword(u.password)));
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
      initial_balance: u.balance,
      password: hashes[i],
    };
    state.users.set(user.id, user);
    state.byHandle.set(user.handle, user);
    state.byEmail.set(user.email, user);
    state.seededTotal += u.balance;
  });
  for (const p of plan.payments) {
    const payment = {
      id: p.id, from: p.from_user_id, to: p.to_user_id, amount: p.amount,
      note: p.note === undefined ? '' : p.note,
      visibility: p.visibility === undefined ? 'public' : p.visibility,
      request_id: null, settlement_id: null, created_at: nowTimestamp(), seeded: true,
    };
    state.payments.push(payment);
    state.paymentsById.set(payment.id, payment);
  }
  for (const r of plan.requests) {
    const request = {
      id: r.id, requester: r.requester_id, payer: r.payer_id, amount: r.amount,
      note: r.note === undefined ? '' : r.note,
      status: r.status === undefined ? 'pending' : r.status,
      payment_id: r.payment_id === undefined ? null : r.payment_id,
      created_at: nowTimestamp(),
    };
    state.requests.push(request);
    state.requestsById.set(request.id, request);
  }
  for (const id of plan.operators) state.operators.add(id);
  return state;
}

module.exports = { parseFixture, buildState };
