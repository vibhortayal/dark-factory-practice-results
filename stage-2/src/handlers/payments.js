'use strict';

const { notFound, selfPayment } = require('../errors');
const { assertTypes, requireField, paymentFields } = require('../validation');
const { recordPayment } = require('../ledger');
const { nowTimestamp } = require('../clock');
const { paymentJson } = require('../serializers');

function createPayment({ state, user, body }) {
  assertTypes(body, { to_handle: 'string' });
  const toHandle = requireField(body, 'to_handle');
  const { amount, note, visibility } = paymentFields(body);
  const receiver = state.byHandle.get(toHandle);
  if (!receiver) throw notFound('no user has that handle');
  if (receiver === user) throw selfPayment();
  const payment = recordPayment(state, {
    from: user.id, to: receiver.id, amount, note, visibility, createdAt: nowTimestamp(),
  });
  return { status: 201, body: paymentJson(state, payment) };
}

module.exports = { createPayment };
