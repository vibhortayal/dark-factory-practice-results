'use strict';

const { notFound, forbidden, ApiError } = require('../errors');
const { checkAmount, requireField } = require('../validation');
const { recordPayment, refundedTotal } = require('../ledger');
const { nowTimestamp } = require('../clock');
const { paymentJson } = require('../serializers');

/** `POST /payments/{id}/refunds`: the original receiver sends money back, as a new payment. */
function refundPayment({ state, user, body, params }) {
  const amount = checkAmount(requireField(body, 'amount'));
  const target = state.paymentsById.get(params.id);
  if (!target) throw notFound('no such payment');
  if (target.to !== user.id) throw forbidden('only the receiver may refund a payment');
  if (target.refund_of !== null) throw new ApiError(422, 'invalid_refund_target', 'a refund cannot be refunded');
  const current = target.revisions[target.revisions.length - 1].amount;
  if (refundedTotal(state, target.id) + amount > current) {
    throw new ApiError(422, 'refund_exceeds_payment', 'refunds may not exceed the payment amount');
  }
  const refund = recordPayment(state, { // judged against the receiver's available funds
    from: target.to, to: target.from, amount, note: target.note, visibility: target.visibility,
    refundOf: target.id, createdAt: nowTimestamp(),
  });
  return { status: 201, body: paymentJson(state, refund) };
}

module.exports = { refundPayment };
