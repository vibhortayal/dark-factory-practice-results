'use strict';

const { notFound, invalid, selfPayment } = require('../errors');
const { isObject } = require('../json');
const { assertTypes, requireField, paymentFields } = require('../validation');
const { applySettlement } = require('../ledger');
const { nowTimestamp } = require('../clock');
const { paymentJson } = require('../serializers');

const MAX_TRANSFERS = 32;

/** One entry, fully checked in the order: types, fields, unknown handle, self-transfer. */
function parseTransfer(state, entry) {
  assertTypes(entry, { from_handle: 'string', to_handle: 'string' });
  const fromHandle = requireField(entry, 'from_handle');
  const toHandle = requireField(entry, 'to_handle');
  const { amount, note, visibility } = paymentFields(entry);
  const from = state.byHandle.get(fromHandle);
  const to = state.byHandle.get(toHandle);
  if (!from || !to) throw notFound('no user has that handle');
  if (from === to) throw selfPayment();
  return { from: from.id, to: to.id, amount, note, visibility };
}

function createSettlement({ state, body }) {
  const transfers = body.transfers;
  if (!Array.isArray(transfers)) throw invalid('transfers must be an array');
  if (transfers.length < 1 || transfers.length > MAX_TRANSFERS) throw invalid('transfers must hold 1 to 32 entries');
  if (!transfers.every(isObject)) throw invalid('every transfer must be an object');
  const parsed = transfers.map((entry) => parseTransfer(state, entry));
  const committedAt = nowTimestamp();
  const { settlementId, payments } = applySettlement(state, parsed, committedAt);
  return {
    status: 201,
    body: { settlement_id: settlementId, committed_at: committedAt, payments: payments.map((p) => paymentJson(state, p)) },
  };
}

module.exports = { createSettlement };
