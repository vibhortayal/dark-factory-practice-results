'use strict';

const { newestFirst } = require('../ordering');

const { pagination, page } = require('../validation');
const { paymentJson } = require('../serializers');

/** Payments only: public ones, plus any the caller sent or received. */
function activity({ state, user, query }) {
  const paging = pagination(query);
  const visible = [];
  for (const p of newestFirst(state.payments)) {
    if (p.visibility === 'public' || p.from === user.id || p.to === user.id) visible.push(p);
  }
  const { items, hasMore } = page(visible, paging);
  return { status: 200, body: { payments: items.map((p) => paymentJson(state, p)), has_more: hasMore } };
}

module.exports = { activity };
