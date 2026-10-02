'use strict';

const crypto = require('crypto');
const { invalid, notFound } = require('../errors');
const { pagination, page, instantParam } = require('../validation');
const { nowMs, formatTimestamp } = require('../clock');
const I = require('../instant');
const history = require('../history');
const { paymentJson } = require('../serializers');

/**
 * `GET /statement`. A first read freezes its parameters (window, knowledge instant and the
 * revision sequence reached so far) under a snapshot token; paging with the token recomputes
 * exactly that result, because revisions are append-only and opening balances never change.
 */
function statement({ state, user, query, search }) {
  const paging = pagination(query);
  let record;
  if (query.has('snapshot')) {
    if (query.has('from') || query.has('to') || query.has('known_at')) {
      throw invalid('only limit and offset may accompany a snapshot');
    }
    record = state.snapshots.get(query.get('snapshot'));
    if (!record || record.user_id !== user.id) throw notFound('no such statement snapshot');
  } else {
    const from = instantParam(search, 'from');
    const to = instantParam(search, 'to');
    const known = instantParam(search, 'known_at');
    if (from !== undefined && to !== undefined && I.compare(from.at, to.at) > 0) {
      throw invalid('from must not be later than to');
    }
    record = {
      token: crypto.randomBytes(18).toString('hex'),
      user_id: user.id,
      from: from === undefined ? null : from.text,
      // Without `to`: just after everything that has taken effect so far (this clock tick included).
      to: to === undefined ? formatTimestamp(nowMs() + 1) : to.text,
      known_at: known === undefined ? null : known.text,
      seq: state.counters.revisionSeq,
    };
    state.snapshots.set(record.token, record);
  }

  const result = history.statement(state, user, {
    from: record.from === null ? null : I.parse(record.from),
    to: I.parse(record.to),
    known: record.known_at === null ? null : I.parse(record.known_at),
    seq: record.seq,
  });
  const { items, hasMore } = page(result.entries, paging);
  const body = {
    opening_balance: result.opening,
    entries: items.map((e) => ({
      payment: { ...paymentJson(state, e.payment), amount: e.rev.amount },
      delta: e.delta,
      balance_after: e.balanceAfter,
      revision: e.rev.revision,
      effective_at: e.rev.effective_at,
      recorded_at: e.rev.recorded_at,
    })),
    closing_balance: result.closing,
    has_more: hasMore,
    snapshot: record.token,
  };
  if (record.known_at !== null) body.known_at = record.known_at;
  return { status: 200, body };
}

module.exports = { statement };
