'use strict';

const { notFound, forbidden } = require('../errors');
const { parseFields, checkEligible, commit, revisionJson } = require('../corrections');

/** `POST /payments/{id}/corrections`: the original sender appends a revision. */
function correctPayment({ state, user, body, params }) {
  const fields = parseFields(body);
  const payment = state.paymentsById.get(params.id);
  if (!payment) throw notFound('no such payment');
  if (payment.from !== user.id) throw forbidden('only the sender may correct a payment');
  checkEligible(state, payment, fields, { allowSettlementMember: false });
  const [revision] = commit(state, [{ payment, fields }], null);
  const { revision: n, amount, effective_at, recorded_at, reason, correction_batch_id } = revisionJson(payment.id, revision);
  return { status: 201, body: { payment_id: payment.id, revision: n, amount, effective_at, recorded_at, reason, correction_batch_id } };
}

/** `GET /payments/{id}/revisions`: only the two parties may read the history. */
function listRevisions({ state, user, params }) {
  const payment = state.paymentsById.get(params.id);
  if (!payment || (payment.from !== user.id && payment.to !== user.id)) throw notFound('no such payment');
  return { status: 200, body: { revisions: payment.revisions.map((r) => revisionJson(payment.id, r)) } };
}

module.exports = { correctPayment, listRevisions };
