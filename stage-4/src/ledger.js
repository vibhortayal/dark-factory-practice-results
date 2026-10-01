// Wallet/payment/request logic. Every function here runs synchronously against
// store.s, so each call is atomic and serialisable by construction.
import { store, insertOrdered, newId, publicPayment, publicRequest, publicAuthorization, availableOf, heldOf, tickStamp, clockMs } from './state.js';
import { stampAt, stampAtUs } from './time.js';
import { msToNs, parseInstantNs } from './instants.js';
import { overdrawsHistory } from './history.js';
import { equalShares } from '../public/assets/js/split.js';
import { conflict, forbidden, invalid, malformed, notFound } from './errors.js';
import {
  checkAmount, checkNote, checkVisibility, checkHandleType, requireHandle,
} from './validate.js';
import { has } from './json.js';

function createPayment(s, from, to, amount, note, visibility, requestId, settlementId, stamp, authorizationId = null) {
  from.balance -= amount;
  to.balance += amount;
  const p = {
    payment_id: newId(s, 'p', 'p', (id) => s.paymentById.has(id)),
    from_user_id: from.id,
    from_handle: from.handle,
    to_user_id: to.id,
    to_handle: to.handle,
    amount,
    currency: s.currency,
    note,
    visibility,
    request_id: requestId,
    settlement_id: settlementId,
    authorization_id: authorizationId,
    created_at: stamp.text,
    ts: msToNs(stamp.ms),
    seq: ++s.seq,
  };
  // Revision 1: the amount as originally paid, effective and recorded when the money moved.
  p.revisions = [{ revision: 1, amount, effective_at: stamp.text, eff: p.ts, recorded_at: stamp.text, rec: p.ts, reason: '', kseq: ++s.kseq }];
  s.paymentById.set(p.payment_id, p);
  insertOrdered(s.payments, p);
  return p;
}

function createRequest(s, requester, payer, amount, note, stamp) {
  const r = {
    request_id: newId(s, 'rq', 'rq', (id) => s.requestById.has(id)),
    requester_id: requester.id,
    requester_handle: requester.handle,
    payer_id: payer.id,
    payer_handle: payer.handle,
    amount,
    currency: s.currency,
    note,
    status: 'pending',
    payment_id: null,
    created_at: stamp.text,
    ts: stamp.ms,
    seq: ++s.seq,
  };
  s.requestById.set(r.request_id, r);
  insertOrdered(s.requests, r);
  return r;
}

export function sendPayment(user, body) {
  const s = store.s;
  checkHandleType(body, 'to_handle');
  const handle = requireHandle(body, 'to_handle');
  const amount = checkAmount(body);
  const note = checkNote(body);
  const visibility = checkVisibility(body);
  if (handle === user.handle) throw invalid_self('self_payment', 'cannot pay yourself');
  const to = s.byHandle.get(handle);
  if (!to) throw notFound('no user has that handle');
  if (availableOf(s, user) < amount) throw conflict('insufficient_funds', 'available balance is below amount');
  return publicPayment(createPayment(s, user, to, amount, note, visibility, null, null, tickStamp(s)));
}

export function invalid_self(code, message) {
  const e = invalid(message);
  e.code = code;
  return e;
}

export function openRequest(user, body) {
  const s = store.s;
  checkHandleType(body, 'payer_handle');
  const handle = requireHandle(body, 'payer_handle');
  const amount = checkAmount(body);
  const note = checkNote(body);
  if (handle === user.handle) throw invalid_self('self_request', 'cannot request money from yourself');
  const payer = s.byHandle.get(handle);
  if (!payer) throw notFound('no user has that handle');
  return publicRequest(createRequest(s, user, payer, amount, note, tickStamp(s)));
}

export function payRequest(user, id, body) {
  const s = store.s;
  const visibility = checkVisibility(body);
  const r = s.requestById.get(id);
  if (!r) throw notFound('no such request');
  if (r.payer_id !== user.id) throw forbidden('only the payer may pay this request');
  if (r.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
  if (availableOf(s, user) < r.amount) throw conflict('insufficient_funds', 'available balance is below amount');
  const requester = s.users.get(r.requester_id);
  const p = createPayment(s, user, requester, r.amount, r.note, visibility, r.request_id, null, tickStamp(s));
  r.status = 'paid';
  r.payment_id = p.payment_id;
  return publicPayment(p);
}

function transition(user, id, who, target) {
  const r = store.s.requestById.get(id);
  if (!r) throw notFound('no such request');
  if (r[who] !== user.id) throw forbidden(`only the ${who === 'payer_id' ? 'payer' : 'requester'} may do this`);
  if (r.status === target) return publicRequest(r);
  if (r.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
  r.status = target;
  return publicRequest(r);
}
export const declineRequest = (user, id) => transition(user, id, 'payer_id', 'declined');
export const cancelRequest = (user, id) => transition(user, id, 'requester_id', 'cancelled');

export { equalShares };

export function createSplit(user, body) {
  const s = store.s;
  let handles;
  if (has(body, 'participant_handles')) {
    handles = body.participant_handles;
    if (!Array.isArray(handles) || handles.some((h) => typeof h !== 'string')) {
      throw malformed('participant_handles must be an array of strings');
    }
  }
  if (!handles) throw invalid('participant_handles is required');
  const amount = checkAmount(body);
  const note = checkNote(body);
  if (handles.length === 0) throw invalid('participant_handles must not be empty');
  if (new Set(handles).size !== handles.length) throw invalid('participant_handles contains a duplicate');
  const users = handles.map((h) => s.byHandle.get(h));
  if (users.some((u) => !u)) throw notFound('no user has that handle');
  const stamp = tickStamp(s);
  const amounts = equalShares(amount, handles.length);
  const requests = [];
  users.forEach((u, i) => {
    if (u.id !== user.id) requests.push(createRequest(s, user, u, amounts[i], note, stamp));
  });
  const split = {
    id: newId(s, 'sp', 'sp', (id) => s.splits.some((x) => x.id === id)),
    user_id: user.id,
    amount,
    note,
    shares: handles.map((h, i) => ({ handle: h, amount: amounts[i] })),
    request_ids: requests.map((r) => r.request_id),
    created_at: stamp.text,
  };
  s.splits.push(split);
  return {
    split_id: split.id,
    amount,
    currency: s.currency,
    note,
    shares: split.shares.map((x) => ({ ...x })),
    requests: requests.map(publicRequest),
    created_at: stamp.text,
  };
}

export function createSettlement(user, body) {
  const s = store.s;
  const t = body.transfers;
  if (!Array.isArray(t) || t.length < 1 || t.length > 32 || t.some((e) => e === null || typeof e !== 'object' || Array.isArray(e))) {
    throw invalid('transfers must be an array of 1 to 32 objects');
  }
  const entries = t.map((e) => {
    checkHandleType(e, 'from_handle');
    checkHandleType(e, 'to_handle');
    const from_handle = requireHandle(e, 'from_handle');
    const to_handle = requireHandle(e, 'to_handle');
    const amount = checkAmount(e);
    const note = checkNote(e);
    const visibility = checkVisibility(e);
    if (from_handle === to_handle) throw invalid_self('self_payment', 'cannot pay yourself');
    const from = s.byHandle.get(from_handle);
    const to = s.byHandle.get(to_handle);
    if (!from || !to) throw notFound('no user has that handle');
    return { from, to, amount, note, visibility };
  });
  const delta = new Map();
  for (const e of entries) {
    delta.set(e.from.id, (delta.get(e.from.id) || 0) - e.amount);
    delta.set(e.to.id, (delta.get(e.to.id) || 0) + e.amount);
  }
  for (const [id, d] of delta) {
    const w = s.users.get(id);
    if (w.balance + d - heldOf(s, id) < 0) throw conflict('insufficient_funds', 'settlement is not affordable');
  }
  const stamp = tickStamp(s);
  const id = newId(s, 'st', 'st', (x) => s.settlements.some((y) => y.id === x));
  const payments = entries.map((e) => createPayment(s, e.from, e.to, e.amount, e.note, e.visibility, null, id, stamp));
  s.settlements.push({
    id, operator_id: user.id, committed_at: stamp.text, payment_ids: payments.map((p) => p.payment_id),
  });
  return { settlement_id: id, committed_at: stamp.text, payments: payments.map(publicPayment) };
}

// ---- authorizations (stage 2) ----

function authorizationFor(s, id) {
  const a = s.authById.get(id);
  if (!a) throw notFound('no such authorization');
  return a;
}

export function createAuthorization(user, body) {
  const s = store.s;
  checkHandleType(body, 'to_handle');
  const handle = requireHandle(body, 'to_handle');
  const amount = checkAmount(body);
  const note = checkNote(body);
  const visibility = checkVisibility(body);
  if (handle === user.handle) throw invalid_self('self_payment', 'cannot authorize a payment to yourself');
  const to = s.byHandle.get(handle);
  if (!to) throw notFound('no user has that handle');
  if (availableOf(s, user) < amount) throw conflict('insufficient_funds', 'available balance is below amount');
  const created = tickStamp(s);
  const expires = stampAt(created.ms + s.authTtl * 1000);
  const a = {
    authorization_id: newId(s, 'a', 'a', (id) => s.authById.has(id)),
    from_user_id: user.id,
    from_handle: user.handle,
    to_user_id: to.id,
    to_handle: to.handle,
    amount,
    captured_amount: 0,
    currency: s.currency,
    note,
    visibility,
    status: 'open',
    expires_at: expires.text,
    payment_id: null,
    payment_ids: [],
    created_at: created.text,
    ts: created.ms,
    seq: ++s.seq,
    closed_at: null,
    createdNs: msToNs(created.ms),
    expNs: msToNs(expires.ms),
    kseq: ++s.kseq,
    initialCaptured: 0,
    seededClosed: false,
    voided_at: null, // internal bookkeeping; the instant is also kept as voidNs for the history
    voidNs: null,
    voidKseq: null,
  };
  s.authById.set(a.authorization_id, a);
  insertOrdered(s.authorizations, a);
  s.openAuths.add(a);
  return publicAuthorization(a);
}

export function captureAuthorization(user, id, body) {
  const s = store.s;
  if (has(body, 'final') && typeof body.final !== 'boolean') throw malformed('final must be a boolean');
  let amount;
  if (has(body, 'amount')) {
    const v = body.amount;
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 1) throw invalid('amount must be an integer of at least 1');
    amount = v;
  }
  const a = authorizationFor(s, id);
  if (a.to_user_id !== user.id) throw forbidden('only the receiver may capture');
  if (a.status === 'captured' || a.status === 'voided') throw conflict('authorization_not_open', 'authorization is not open');
  if (a.status === 'expired') throw conflict('authorization_expired', 'authorization has expired');
  const remaining = a.amount - a.captured_amount;
  if (amount === undefined) amount = remaining;
  if (amount > remaining) throw invalid_self('capture_exceeds_authorization', 'amount exceeds the remaining authorization');
  const from = s.users.get(a.from_user_id);
  const p = createPayment(s, from, user, amount, a.note, a.visibility, null, null, tickStamp(s), a.authorization_id);
  a.captured_amount += amount;
  a.payment_id = p.payment_id;
  a.payment_ids.push(p.payment_id);
  if (body.final !== false || amount === remaining) {
    a.status = 'captured';
    a.closed_at = p.created_at;
    s.openAuths.delete(a);
  }
  return publicPayment(p);
}

export function voidAuthorization(user, id) {
  const s = store.s;
  const a = authorizationFor(s, id);
  if (a.from_user_id !== user.id) throw forbidden('only the payer may void');
  if (a.status === 'voided') return publicAuthorization(a);
  if (a.status !== 'open') throw conflict('authorization_not_open', 'authorization is not open');
  const at = tickStamp(s);
  a.status = 'voided';
  a.voided_at = at.text;
  a.voidNs = msToNs(at.ms);
  a.voidKseq = ++s.kseq;
  a.closed_at = at.text;
  s.openAuths.delete(a);
  return publicAuthorization(a);
}

// ---- corrections (stage 3) ----

export const publicRevision = (p, r) => ({
  payment_id: p.payment_id,
  revision: r.revision,
  amount: r.amount,
  effective_at: r.effective_at,
  recorded_at: r.recorded_at,
  reason: r.reason,
});

const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

export function correctPayment(user, id, body) {
  const s = store.s;
  // Field validation: every missing or invalid field, wrong JSON types included, is 422.
  if (!has(body, 'expected_revision') || !isInt(body.expected_revision) || body.expected_revision < 1) throw invalid('expected_revision must be a positive integer');
  if (!has(body, 'amount') || !isInt(body.amount) || body.amount < 0 || body.amount > 1000000000) throw invalid('amount must be an integer from 0 to 1000000000');
  if (!has(body, 'reason') || typeof body.reason !== 'string' || [...body.reason].length < 1 || [...body.reason].length > 200) throw invalid('reason must be a string of 1 to 200 characters');
  const effNs = has(body, 'effective_at') ? parseInstantNs(body.effective_at) : null;
  if (effNs === null) throw invalid('effective_at must be an RFC 3339 instant with an offset');
  // "Not later than now": the service clock reads whole milliseconds, so allow up to the end of the current millisecond.
  if (effNs > msToNs(clockMs(s)) + 999999n) throw invalid('effective_at must not be in the future');
  const p = s.paymentById.get(id);
  if (!p) throw notFound('no such payment');
  if (p.from_user_id !== user.id) throw forbidden('only the original sender may correct a payment');
  if (p.settlement_id !== null || p.authorization_id !== null) throw invalid_self('linked_payment_immutable', 'settlement members and captures cannot be corrected');
  const last = p.revisions[p.revisions.length - 1];
  if (body.expected_revision !== last.revision) throw conflict('stale_revision', 'the payment has a newer revision');
  const diff = body.amount - last.amount;
  const sender = s.users.get(p.from_user_id);
  const receiver = s.users.get(p.to_user_id);
  // The difference moves between the same two wallets: more -> the sender pays it, less -> the receiver gives it back.
  if (diff > 0 && availableOf(s, sender) < diff) throw conflict('insufficient_funds', 'available balance is below the difference');
  if (diff < 0 && availableOf(s, receiver) < -diff) throw conflict('insufficient_funds', 'available balance is below the difference');
  const proposal = { payment: p, revision: { amount: body.amount, eff: effNs } };
  if (overdrawsHistory(s, sender, proposal) || overdrawsHistory(s, receiver, proposal)) {
    throw conflict('historical_overdraft', 'the correction would overdraw a wallet at an earlier time');
  }
  // recorded_at is the real clock, bumped past this payment's own previous recorded_at so that it strictly increases.
  const stamp = stampAtUs(Math.max(tickStamp(s).ms * 1000, Number(last.rec / 1000n) + 1));
  const rev = {
    revision: last.revision + 1, amount: body.amount, effective_at: body.effective_at, eff: effNs,
    recorded_at: stamp.text, rec: stamp.ns, reason: body.reason, kseq: ++s.kseq,
  };
  p.revisions.push(rev);
  sender.balance -= diff;
  receiver.balance += diff;
  return publicRevision(p, rev);
}

export function listRevisions(user, id) {
  const p = store.s.paymentById.get(id);
  if (!p || (p.from_user_id !== user.id && p.to_user_id !== user.id)) throw notFound('no such payment');
  return { revisions: p.revisions.map((r) => publicRevision(p, r)) };
}
