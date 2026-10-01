// Wallet/payment/request logic. Every function here runs synchronously against
// store.s, so each call is atomic and serialisable by construction.
import { store, insertOrdered, newId, publicPayment, publicRequest, publicAuthorization, availableOf, heldOf } from './state.js';
import { nowStamp, nowStampMs, stampAt } from './time.js';
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
    ts: stamp.ms,
    seq: ++s.seq,
  };
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
  return publicPayment(createPayment(s, user, to, amount, note, visibility, null, null, nowStamp()));
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
  return publicRequest(createRequest(s, user, payer, amount, note, nowStamp()));
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
  const p = createPayment(s, user, requester, r.amount, r.note, visibility, r.request_id, null, nowStamp());
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
  const stamp = nowStamp();
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
  const stamp = nowStamp();
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
  const created = nowStampMs();
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
    exp: expires.ms,
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
  const p = createPayment(s, from, user, amount, a.note, a.visibility, null, null, nowStamp(), a.authorization_id);
  a.captured_amount += amount;
  a.payment_id = p.payment_id;
  a.payment_ids.push(p.payment_id);
  if (body.final !== false || amount === remaining) {
    a.status = 'captured';
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
  a.status = 'voided';
  s.openAuths.delete(a);
  return publicAuthorization(a);
}
