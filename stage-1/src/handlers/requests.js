'use strict';

const { notFound, forbidden, conflict, selfRequest, invalid } = require('../errors');
const {
  assertTypes, requireField, checkAmount, checkNote, checkVisibility, pagination, page,
} = require('../validation');
const { recordPayment } = require('../ledger');
const { nowTimestamp } = require('../clock');
const { nextId } = require('../state');
const { paymentJson, requestJson } = require('../serializers');

const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];

/** Insert a pending request; shared with splits. */
function addRequest(state, { requester, payer, amount, note, createdAt }) {
  const request = {
    id: nextId(state, 'request', 'rq_', state.requestsById),
    requester, payer, amount, note, status: 'pending', payment_id: null, created_at: createdAt,
  };
  state.requests.push(request);
  state.requestsById.set(request.id, request);
  return request;
}

function createRequest({ state, user, body }) {
  assertTypes(body, { payer_handle: 'string' });
  const payerHandle = requireField(body, 'payer_handle');
  const amount = checkAmount(requireField(body, 'amount'));
  const note = checkNote(body.note);
  const payer = state.byHandle.get(payerHandle);
  if (!payer) throw notFound('no user has that handle');
  if (payer === user) throw selfRequest();
  const request = addRequest(state, { requester: user.id, payer: payer.id, amount, note, createdAt: nowTimestamp() });
  return { status: 201, body: requestJson(state, request) };
}

function payRequest({ state, user, body, params }) {
  const visibility = checkVisibility(body.visibility);
  const request = state.requestsById.get(params.id);
  if (!request) throw notFound('no such request');
  if (request.payer !== user.id) throw forbidden('only the payer may pay this request');
  if (request.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
  const payment = recordPayment(state, {
    from: request.payer, to: request.requester, amount: request.amount, note: request.note,
    visibility, requestId: request.id, createdAt: nowTimestamp(),
  });
  request.status = 'paid';
  request.payment_id = payment.id;
  return { status: 201, body: paymentJson(state, payment) };
}

/** decline (payer) and cancel (requester) differ only in who acts and the final status. */
function closer(role, finalStatus) {
  return ({ state, user, params }) => {
    const request = state.requestsById.get(params.id);
    if (!request) throw notFound('no such request');
    if (request[role] !== user.id) throw forbidden(`only the ${role} may do this`);
    if (request.status !== finalStatus) {
      if (request.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
      request.status = finalStatus;
    }
    return { status: 200, body: requestJson(state, request) };
  };
}

function listRequests({ state, user, query }) {
  const paging = pagination(query);
  const direction = query.get('direction');
  const status = query.get('status');
  if (direction !== null && direction !== 'incoming' && direction !== 'outgoing') throw invalid('unknown direction');
  if (status !== null && !STATUSES.includes(status)) throw invalid('unknown status');
  const mine = [];
  for (let i = state.requests.length - 1; i >= 0; i--) {
    const r = state.requests[i];
    const incoming = r.payer === user.id;
    const outgoing = r.requester === user.id;
    if (!incoming && !outgoing) continue;
    if (direction === 'incoming' && !incoming) continue;
    if (direction === 'outgoing' && !outgoing) continue;
    if (status !== null && r.status !== status) continue;
    mine.push(r);
  }
  const { items, hasMore } = page(mine, paging);
  return { status: 200, body: { requests: items.map((r) => requestJson(state, r)), has_more: hasMore } };
}

module.exports = {
  addRequest, createRequest, payRequest, listRequests,
  declineRequest: closer('payer', 'declined'),
  cancelRequest: closer('requester', 'cancelled'),
};
