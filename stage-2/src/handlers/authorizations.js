'use strict';

const { notFound, forbidden, conflict, selfPayment, malformed, invalid, ApiError } = require('../errors');
const { assertTypes, requireField, paymentFields, pagination, page } = require('../validation');
const { nowMs, formatTimestamp } = require('../clock');
const holds = require('../holds');
const { authorizationJson, paymentJson } = require('../serializers');

const STATUSES = ['open', 'captured', 'voided', 'expired'];

function createAuthorization({ state, user, body }) {
  assertTypes(body, { to_handle: 'string' });
  const toHandle = requireField(body, 'to_handle');
  const { amount, note, visibility } = paymentFields(body);
  const receiver = state.byHandle.get(toHandle);
  if (!receiver) throw notFound('no user has that handle');
  if (receiver === user) throw selfPayment();
  if (user.balance - user.held < amount) throw conflict('insufficient_funds', 'available balance is too low');

  const createdMs = nowMs();
  const auth = holds.addAuthorization(state, {
    id: holds.newAuthorizationId(state),
    from: user.id, to: receiver.id, amount, captured_amount: 0, status: 'open', note, visibility,
    expires_ms: createdMs + state.authTtlSeconds * 1000,
    expires_at: formatTimestamp(createdMs + state.authTtlSeconds * 1000),
    payment_id: null, payment_ids: [], created_at: formatTimestamp(createdMs),
  });
  return { status: 201, body: authorizationJson(state, auth) };
}

/** Capture amount: omitted -> remainder; otherwise an integral number of at least 1. */
function captureAmount(body) {
  if (body.amount === undefined) return null;
  const v = body.amount;
  if (typeof v !== 'number' || !Number.isFinite(v) || !Number.isInteger(v) || v < 1) {
    throw invalid('amount must be an integer of at least 1');
  }
  return v;
}

function captureAuthorization({ state, user, body, params }) {
  if (body.final !== undefined && typeof body.final !== 'boolean') throw malformed('final must be a boolean');
  const requested = captureAmount(body);
  const auth = state.authById.get(params.id);
  if (!auth) throw notFound('no such authorization');
  if (auth.to !== user.id) throw forbidden('only the receiver may capture');
  if (auth.status === 'captured' || auth.status === 'voided') {
    throw conflict('authorization_not_open', 'authorization is not open');
  }
  if (auth.status === 'expired') throw new ApiError(409, 'authorization_expired', 'authorization has expired');
  const remaining = holds.remainingOf(auth);
  const amount = requested === null ? remaining : requested;
  if (amount > remaining) {
    throw new ApiError(422, 'capture_exceeds_authorization', 'amount exceeds the remaining authorization');
  }
  const payment = holds.capture(state, auth, amount, body.final !== false, formatTimestamp(nowMs()));
  return { status: 201, body: paymentJson(state, payment) };
}

function voidAuthorization({ state, user, params }) {
  const auth = state.authById.get(params.id);
  if (!auth) throw notFound('no such authorization');
  if (auth.from !== user.id) throw forbidden('only the payer may void');
  if (auth.status !== 'voided') {
    if (auth.status !== 'open') throw conflict('authorization_not_open', 'authorization is not open');
    holds.voidAuthorization(state, auth);
  }
  return { status: 200, body: authorizationJson(state, auth) };
}

function listAuthorizations({ state, user, query }) {
  const paging = pagination(query);
  const direction = query.get('direction');
  const status = query.get('status');
  if (direction !== null && direction !== 'incoming' && direction !== 'outgoing') throw invalid('unknown direction');
  if (status !== null && !STATUSES.includes(status)) throw invalid('unknown status');
  const mine = [];
  for (let i = state.authorizations.length - 1; i >= 0; i--) {
    const a = state.authorizations[i];
    const outgoing = a.from === user.id;
    const incoming = a.to === user.id;
    if (!outgoing && !incoming) continue;
    if (direction === 'outgoing' && !outgoing) continue;
    if (direction === 'incoming' && !incoming) continue;
    if (status !== null && a.status !== status) continue;
    mine.push(a);
  }
  const { items, hasMore } = page(mine, paging);
  return { status: 200, body: { authorizations: items.map((a) => authorizationJson(state, a)), has_more: hasMore } };
}

module.exports = { createAuthorization, captureAuthorization, voidAuthorization, listAuthorizations };
