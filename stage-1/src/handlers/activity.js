'use strict';

const { pagination, page } = require('../validation');
const { paymentJson } = require('../serializers');

/** Payments only: public ones, plus any the caller sent or received. */
function activity({ state, user, query }) {
  const paging = pagination(query);
  const visible = [];
  for (let i = state.payments.length - 1; i >= 0; i--) {
    const p = state.payments[i];
    if (p.visibility === 'public' || p.from === user.id || p.to === user.id) visible.push(p);
  }
  const { items, hasMore } = page(visible, paging);
  return { status: 200, body: { payments: items.map((p) => paymentJson(state, p)), has_more: hasMore } };
}

module.exports = { activity };
