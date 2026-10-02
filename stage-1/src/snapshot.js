'use strict';

/** Export / import of the complete service state as one JSON document. */

const { invalid } = require('./errors');
const { isObject } = require('./json');
const { emptyState } = require('./state');
const { isValidRecord } = require('./passwords');
const { HANDLE_RE } = require('./validation');

const MAX_BALANCE = 2 ** 53;
const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];

function exportState(state) {
  return {
    track: 'pocketful',
    format_version: 1,
    state: {
      currency: state.currency,
      minor_units: state.minorUnits,
      seeded_total: state.seededTotal,
      counters: { ...state.counters },
      users: [...state.users.values()],
      tokens: [...state.tokens.entries()],
      payments: state.payments,
      requests: state.requests,
      settlements: [...state.settlements.values()],
      operators: [...state.operators],
      idempotency: [...state.idem.values()],
    },
  };
}

const fail = (msg) => invalid(`invalid state: ${msg}`);
const str = (v, what) => {
  if (typeof v !== 'string') throw fail(what);
  return v;
};
const money = (v, what) => {
  if (!Number.isInteger(v) || v < 0 || v > MAX_BALANCE) throw fail(what);
  return v;
};
const arr = (v, what) => {
  if (!Array.isArray(v)) throw fail(what);
  return v;
};
const unique = (map, id, what) => {
  if (map.has(id)) throw fail(`duplicate ${what}`);
};

/** Validate an export document and build a state from it; throws 422 on any problem. */
function importState(doc) {
  if (!isObject(doc)) throw invalid('import body must be a JSON object');
  if (doc.track !== 'pocketful') throw invalid('wrong track');
  if (doc.format_version !== 1) throw invalid('unsupported format_version');
  if (!isObject(doc.state)) throw invalid('state is missing');
  try {
    return buildFromDocument(doc.state);
  } catch (err) {
    if (err.status) throw err;
    throw fail('unreadable');
  }
}

function buildFromDocument(s) {
  const state = emptyState();
  if (typeof s.currency !== 'string' || s.currency === '') throw fail('currency');
  if (![0, 2, 3].includes(s.minor_units)) throw fail('minor_units');
  state.currency = s.currency;
  state.minorUnits = s.minor_units;
  state.seededTotal = money(s.seeded_total, 'seeded_total');
  if (!isObject(s.counters)) throw fail('counters');
  for (const k of Object.keys(state.counters)) state.counters[k] = money(s.counters[k], `counter ${k}`);

  for (const u of arr(s.users, 'users')) {
    if (!isObject(u)) throw fail('user');
    const user = {
      id: str(u.id, 'user id'), email: str(u.email, 'email'), display_name: str(u.display_name, 'display_name'),
      handle: str(u.handle, 'handle'), balance: money(u.balance, 'balance'),
      initial_balance: money(u.initial_balance, 'initial_balance'), password: u.password,
    };
    if (!HANDLE_RE.test(user.handle) || !isValidRecord(user.password)) throw fail('user fields');
    unique(state.users, user.id, 'user id');
    unique(state.byHandle, user.handle, 'handle');
    unique(state.byEmail, user.email, 'email');
    state.users.set(user.id, user);
    state.byHandle.set(user.handle, user);
    state.byEmail.set(user.email, user);
  }

  for (const t of arr(s.tokens, 'tokens')) {
    if (!Array.isArray(t) || t.length !== 2 || !state.users.has(str(t[1], 'token owner'))) throw fail('token');
    state.tokens.set(str(t[0], 'token'), t[1]);
  }

  for (const p of arr(s.payments, 'payments')) {
    if (!isObject(p)) throw fail('payment');
    const payment = {
      id: str(p.id, 'payment id'), from: str(p.from, 'from'), to: str(p.to, 'to'), amount: money(p.amount, 'amount'),
      note: str(p.note, 'note'), visibility: p.visibility, request_id: p.request_id, settlement_id: p.settlement_id,
      created_at: str(p.created_at, 'created_at'), seeded: p.seeded === true,
    };
    if (!state.users.has(payment.from) || !state.users.has(payment.to)) throw fail('payment parties');
    if (payment.visibility !== 'public' && payment.visibility !== 'private') throw fail('visibility');
    if (payment.request_id !== null) str(payment.request_id, 'request_id');
    if (payment.settlement_id !== null) str(payment.settlement_id, 'settlement_id');
    unique(state.paymentsById, payment.id, 'payment id');
    state.payments.push(payment);
    state.paymentsById.set(payment.id, payment);
  }

  for (const r of arr(s.requests, 'requests')) {
    if (!isObject(r)) throw fail('request');
    const request = {
      id: str(r.id, 'request id'), requester: str(r.requester, 'requester'), payer: str(r.payer, 'payer'),
      amount: money(r.amount, 'amount'), note: str(r.note, 'note'), status: r.status,
      payment_id: r.payment_id, created_at: str(r.created_at, 'created_at'),
    };
    if (!state.users.has(request.requester) || !state.users.has(request.payer)) throw fail('request parties');
    if (!STATUSES.includes(request.status)) throw fail('request status');
    if (request.payment_id !== null) str(request.payment_id, 'payment_id');
    unique(state.requestsById, request.id, 'request id');
    state.requests.push(request);
    state.requestsById.set(request.id, request);
  }

  for (const st of arr(s.settlements, 'settlements')) {
    if (!isObject(st)) throw fail('settlement');
    const ids = arr(st.payment_ids, 'payment_ids');
    if (!ids.every((id) => state.paymentsById.has(id))) throw fail('settlement members');
    unique(state.settlements, str(st.id, 'settlement id'), 'settlement id');
    state.settlements.set(st.id, { id: st.id, committed_at: str(st.committed_at, 'committed_at'), payment_ids: ids });
  }
  for (const p of state.payments) {
    if (p.settlement_id !== null && !state.settlements.has(p.settlement_id)) throw fail('settlement link');
  }

  for (const id of arr(s.operators, 'operators')) {
    if (!state.users.has(str(id, 'operator'))) throw fail('operator');
    state.operators.add(id);
  }

  for (const rec of arr(s.idempotency, 'idempotency')) {
    if (!isObject(rec) || !state.users.has(rec.user_id) || !isObject(rec.response)) throw fail('idempotency record');
    str(rec.method, 'method'); str(rec.path, 'path'); str(rec.key, 'key');
    state.idem.set(JSON.stringify([rec.user_id, rec.method, rec.path, rec.key]), rec);
  }

  checkBalances(state);
  return state;
}

/** Every balance must equal its opening balance plus recorded non-seeded flows. */
function checkBalances(state) {
  const expected = new Map([...state.users.values()].map((u) => [u.id, u.initial_balance]));
  for (const p of state.payments) {
    if (p.seeded) continue;
    expected.set(p.from, expected.get(p.from) - p.amount);
    expected.set(p.to, expected.get(p.to) + p.amount);
  }
  let total = 0;
  let opening = 0;
  for (const u of state.users.values()) {
    if (u.balance !== expected.get(u.id) || u.balance < 0) throw fail('balance does not match history');
    total += u.balance;
    opening += u.initial_balance;
  }
  if (total !== state.seededTotal || opening !== state.seededTotal) throw fail('balances do not sum to the seeded total');
}

module.exports = { exportState, importState };
