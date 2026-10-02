'use strict';

/** Internal records -> API response objects. */

function paymentJson(state, p) {
  return {
    payment_id: p.id,
    from_user_id: p.from,
    from_handle: state.users.get(p.from).handle,
    to_user_id: p.to,
    to_handle: state.users.get(p.to).handle,
    amount: p.amount,
    currency: state.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.request_id,
    settlement_id: p.settlement_id,
    created_at: p.created_at,
  };
}

function requestJson(state, r) {
  return {
    request_id: r.id,
    requester_id: r.requester,
    requester_handle: state.users.get(r.requester).handle,
    payer_id: r.payer,
    payer_handle: state.users.get(r.payer).handle,
    amount: r.amount,
    currency: state.currency,
    note: r.note,
    status: r.status,
    payment_id: r.payment_id,
    created_at: r.created_at,
  };
}

module.exports = { paymentJson, requestJson };
