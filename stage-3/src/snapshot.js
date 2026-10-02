'use strict';

/**
 * Export / import of the complete service state as one JSON document.
 *
 * Three state layouts are told apart inside `state`: stage 1 (no `authorizations`), stage 2
 * (authorizations, no `layout`) and stage 3 (`layout: 3`: opening balances, payment revisions,
 * `closed_at` and statement snapshots). Older layouts are upgraded on import: every payment
 * gets its revision 1 and opening balances and close times are derived.
 */

const { invalid } = require('./errors');
const { isObject } = require('./json');
const { emptyState } = require('./state');
const { isValidRecord } = require('./passwords');
const { HANDLE_RE, codePoints } = require('./validation');
const I = require('./instant');
const { addAuthorization, sweep } = require('./holds');
const { indexPayment } = require('./ledger');
const { nowMs } = require('./clock');

const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];

const { MAX_BALANCE, REQUEST_STATUSES: STATUSES } = require('./constants');

function exportState(state) {
  return {
    track: 'pocketful',
    format_version: 1,
    state: {
      layout: 3,
      currency: state.currency,
      minor_units: state.minorUnits,
      seeded_total: state.seededTotal,
      counters: { ...state.counters },
      users: [...state.users.values()].map(({ held, ...user }) => user),
      tokens: [...state.tokens.entries()],
      payments: state.payments,
      requests: state.requests,
      settlements: [...state.settlements.values()],
      operators: [...state.operators],
      idempotency: [...state.idem.values()],
      authorization_ttl_seconds: state.authTtlSeconds,
      authorizations: state.authorizations.map(({ expires_ms, ...a }) => a),
      snapshots: [...state.snapshots.values()],
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
const bool = (v, what) => {
  if (v !== undefined && typeof v !== 'boolean') throw fail(what);
  return v === true;
};
const stamp = (v, what) => {
  if (I.parse(str(v, what)) === null) throw fail(what);
  return v;
};
const int = (v, what, min = 0) => {
  if (!Number.isInteger(v) || v < min || v > Number.MAX_SAFE_INTEGER) throw fail(what);
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
  const layout3 = s.layout === 3;
  if (s.layout !== undefined && !layout3) throw fail('layout');
  if (typeof s.currency !== 'string' || s.currency === '') throw fail('currency');
  if (![0, 2, 3].includes(s.minor_units)) throw fail('minor_units');
  state.currency = s.currency;
  state.minorUnits = s.minor_units;
  state.seededTotal = money(s.seeded_total, 'seeded_total');
  if (!isObject(s.counters)) throw fail('counters');
  const hasHolds = layout3 || s.authorizations !== undefined;
  for (const k of Object.keys(state.counters)) {
    const optional = (k === 'authorization' && !hasHolds) || (k === 'revisionSeq' && !layout3);
    if (optional && s.counters[k] === undefined) continue;
    state.counters[k] = money(s.counters[k], `counter ${k}`);
  }
  if (hasHolds) {
    if (!Number.isInteger(s.authorization_ttl_seconds) || s.authorization_ttl_seconds < 1) throw fail('authorization_ttl_seconds');
    state.authTtlSeconds = s.authorization_ttl_seconds;
  }

  for (const u of arr(s.users, 'users')) {
    if (!isObject(u)) throw fail('user');
    const user = {
      id: str(u.id, 'user id'), email: str(u.email, 'email'), display_name: str(u.display_name, 'display_name'),
      handle: str(u.handle, 'handle'), balance: money(u.balance, 'balance'),
      held: 0, password: u.password,
    };
    // Older layouts store the balance after the seeded payments; the opening balance is derived below.
    if (layout3) user.opening_balance = int(u.opening_balance, 'opening_balance', -MAX_BALANCE);
    else user.opening_balance = money(u.initial_balance, 'initial_balance');
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

  const seqs = new Set();
  for (const p of arr(s.payments, 'payments')) {
    if (!isObject(p)) throw fail('payment');
    const payment = {
      id: str(p.id, 'payment id'), from: str(p.from, 'from'), to: str(p.to, 'to'), amount: money(p.amount, 'amount'),
      note: str(p.note, 'note'), visibility: p.visibility, request_id: p.request_id, settlement_id: p.settlement_id,
      authorization_id: p.authorization_id === undefined ? null : p.authorization_id,
      created_at: stamp(p.created_at, 'created_at'), seeded: bool(p.seeded, 'seeded'),
    };
    if (!state.users.has(payment.from) || !state.users.has(payment.to)) throw fail('payment parties');
    if (payment.visibility !== 'public' && payment.visibility !== 'private') throw fail('visibility');
    if (payment.request_id !== null) str(payment.request_id, 'request_id');
    if (payment.settlement_id !== null) str(payment.settlement_id, 'settlement_id');
    if (payment.authorization_id !== null) str(payment.authorization_id, 'authorization_id');
    unique(state.paymentsById, payment.id, 'payment id');
    payment.revisions = layout3 ? parseRevisions(p, payment, seqs, state.counters.revisionSeq) : [{
      revision: 1, amount: payment.amount, effective_at: payment.created_at, recorded_at: payment.created_at,
      reason: '', seq: ++state.counters.revisionSeq,
    }];
    indexPayment(state, payment);
  }

  for (const r of arr(s.requests, 'requests')) {
    if (!isObject(r)) throw fail('request');
    const request = {
      id: str(r.id, 'request id'), requester: str(r.requester, 'requester'), payer: str(r.payer, 'payer'),
      amount: money(r.amount, 'amount'), note: str(r.note, 'note'), status: r.status,
      payment_id: r.payment_id, created_at: stamp(r.created_at, 'created_at'),
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
    state.settlements.set(st.id, { id: st.id, committed_at: stamp(st.committed_at, 'committed_at'), payment_ids: ids });
  }
  for (const p of state.payments) {
    if (p.settlement_id !== null && !state.settlements.has(p.settlement_id)) throw fail('settlement link');
  }

  for (const a of hasHolds ? arr(s.authorizations, 'authorizations') : []) {
    if (!isObject(a)) throw fail('authorization');
    const auth = {
      id: str(a.id, 'authorization id'), from: str(a.from, 'from'), to: str(a.to, 'to'),
      amount: money(a.amount, 'amount'), captured_amount: money(a.captured_amount, 'captured_amount'),
      status: a.status, note: str(a.note, 'note'), visibility: a.visibility, expires_at: str(a.expires_at, 'expires_at'),
      expires_ms: (I.parse(a.expires_at) || {}).ms, payment_id: a.payment_id,
      payment_ids: arr(a.payment_ids, 'payment_ids'), seeded: bool(a.seeded, 'seeded'), created_at: stamp(a.created_at, 'created_at'),
    };
    if (!state.users.has(auth.from) || !state.users.has(auth.to)) throw fail('authorization parties');
    if (!AUTH_STATUSES.includes(auth.status) || auth.expires_ms === undefined) throw fail('authorization status or expiry');
    if (auth.visibility !== 'public' && auth.visibility !== 'private') throw fail('authorization visibility');
    if (auth.captured_amount > auth.amount || auth.amount < 1) throw fail('authorization amounts');
    if (auth.payment_id !== null) str(auth.payment_id, 'payment_id');
    let capturedSum = 0;
    let lastCapture = null;
    for (const pid of auth.payment_ids) {
      const pay = state.paymentsById.get(str(pid, 'payment id'));
      if (!pay || (!auth.seeded && pay.authorization_id !== auth.id)) throw fail('capture payment link');
      capturedSum += pay.amount;
      lastCapture = pay;
    }
    // Authorizations made through the API record exactly their capture payments.
    if (!auth.seeded && capturedSum !== auth.captured_amount) throw fail('captured amount does not match captures');
    if (auth.payment_ids.length && auth.payment_id !== auth.payment_ids[auth.payment_ids.length - 1]) throw fail('latest capture');
    if (layout3) {
      auth.closed_at = a.closed_at === null ? null : stamp(a.closed_at, 'closed_at');
      auth.no_history = bool(a.no_history, 'no_history');
      if ((auth.status === 'open') !== (auth.closed_at === null)) throw fail('closed_at does not match status');
    } else {
      // Earlier layouts record no close time: the earliest time consistent with what is known.
      auth.closed_at = { open: null, expired: auth.expires_at, captured: lastCapture ? lastCapture.created_at : auth.created_at, voided: lastCapture ? lastCapture.created_at : auth.created_at }[auth.status];
      if (auth.status === 'captured' && !lastCapture) auth.closed_at = auth.created_at;
      auth.no_history = auth.seeded && auth.status !== 'open';
    }
    unique(state.authById, auth.id, 'authorization id');
    addAuthorization(state, auth);
  }
  for (const p of state.payments) {
    if (p.authorization_id !== null && !state.authById.has(p.authorization_id)) throw fail('authorization link');
  }
  for (const u of state.users.values()) if (u.held > u.balance) throw fail('holds exceed balance');
  sweep(state, nowMs());

  for (const id of arr(s.operators, 'operators')) {
    if (!state.users.has(str(id, 'operator'))) throw fail('operator');
    state.operators.add(id);
  }

  for (const rec of arr(s.idempotency, 'idempotency')) {
    if (!isObject(rec) || !state.users.has(rec.user_id) || !isObject(rec.response)) throw fail('idempotency record');
    str(rec.method, 'method'); str(rec.path, 'path'); str(rec.key, 'key');
    state.idem.set(JSON.stringify([rec.user_id, rec.method, rec.path, rec.key]), rec);
  }

  if (!layout3) deriveOpeningBalances(state);
  checkBalances(state);

  if (layout3) {
    for (const sn of arr(s.snapshots, 'snapshots')) {
      if (!isObject(sn) || !state.users.has(sn.user_id)) throw fail('snapshot');
      const record = {
        token: str(sn.token, 'snapshot token'), user_id: sn.user_id,
        from: sn.from === null ? null : stamp(sn.from, 'snapshot from'), to: stamp(sn.to, 'snapshot to'),
        known_at: sn.known_at === null ? null : stamp(sn.known_at, 'snapshot known_at'), seq: int(sn.seq, 'snapshot seq'),
      };
      if (record.seq > state.counters.revisionSeq) throw fail('snapshot seq');
      unique(state.snapshots, record.token, 'snapshot token');
      state.snapshots.set(record.token, record);
    }
  }
  state.clockFloor = latestInstantMs(state);
  return state;
}

/** Revisions of a stage-3 payment: sequential, immutable-looking, strictly increasing in time. */
function parseRevisions(p, payment, seqs, maxSeq) {
  const revisions = arr(p.revisions, 'revisions').map((r, i) => {
    if (!isObject(r)) throw fail('revision');
    const rev = {
      revision: int(r.revision, 'revision', 1), amount: money(r.amount, 'revision amount'),
      effective_at: stamp(r.effective_at, 'effective_at'), recorded_at: stamp(r.recorded_at, 'recorded_at'),
      reason: str(r.reason, 'reason'), seq: int(r.seq, 'revision seq', 1),
    };
    if (rev.revision !== i + 1 || rev.seq > maxSeq || seqs.has(rev.seq)) throw fail('revision numbering');
    seqs.add(rev.seq);
    if (i === 0) {
      if (rev.amount !== payment.amount || rev.effective_at !== payment.created_at || rev.recorded_at !== payment.created_at || rev.reason !== '') {
        throw fail('first revision does not match the payment');
      }
    } else if (codePoints(rev.reason) < 1 || codePoints(rev.reason) > 200) throw fail('revision reason');
    return rev;
  });
  if (revisions.length === 0) throw fail('revisions');
  for (let i = 1; i < revisions.length; i++) {
    if (I.compare(I.parse(revisions[i].recorded_at), I.parse(revisions[i - 1].recorded_at)) <= 0 || revisions[i].seq <= revisions[i - 1].seq) {
      throw fail('revision order');
    }
  }
  return revisions;
}

/** Older layouts: opening = the stored balance before API flows, minus the seeded payments' effect. */
function deriveOpeningBalances(state) {
  for (const p of state.payments) {
    if (!p.seeded) continue;
    state.users.get(p.from).opening_balance += p.amount;
    state.users.get(p.to).opening_balance -= p.amount;
  }
}

/** The latest instant the state already records (the clock must not run behind it). */
function latestInstantMs(state) {
  let latest = 0;
  const see = (text) => {
    const at = I.parse(text);
    if (at !== null && at.ms > latest) latest = at.ms;
  };
  for (const p of state.payments) {
    see(p.created_at);
    for (const r of p.revisions) {
      see(r.recorded_at);
      see(r.effective_at);
    }
  }
  for (const r of state.requests) see(r.created_at);
  for (const a of state.authorizations) {
    see(a.created_at);
    if (a.closed_at) see(a.closed_at);
  }
  for (const st of state.settlements.values()) see(st.committed_at);
  return latest;
}

/** balance = opening + latest movements; balances and openings sum to the seeded total. */
function checkBalances(state) {
  const expected = new Map([...state.users.values()].map((u) => [u.id, u.opening_balance]));
  for (const p of state.payments) {
    const rev = p.revisions[p.revisions.length - 1];
    expected.set(p.from, expected.get(p.from) - rev.amount);
    expected.set(p.to, expected.get(p.to) + rev.amount);
  }
  let total = 0;
  let opening = 0;
  for (const u of state.users.values()) {
    if (u.balance !== expected.get(u.id) || u.balance < 0) throw fail('balance does not match history');
    total += u.balance;
    opening += u.opening_balance;
  }
  if (total !== state.seededTotal || opening !== state.seededTotal) throw fail('balances do not sum to the seeded total');
}

module.exports = { exportState, importState };
