'use strict';

/**
 * Payment corrections, shared by the single endpoint and the operator's batch: one validation,
 * one eligibility check, one commit path. A single correction is a batch of one payment.
 */

const { invalid, conflict, ApiError } = require('./errors');
const { codePoints, MAX_AMOUNT } = require('./validation');
const { nowMs, formatTimestamp } = require('./clock');
const { MAX_BALANCE } = require('./constants');
const { refundedTotal } = require('./ledger');
const I = require('./instant');
const history = require('./history');

const isInt = (v, min, max) => typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;

/** The ordinary correction fields; every invalid or missing one (also a wrong JSON type) is 422. */
function parseFields(item) {
  const { expected_revision: expected, amount, effective_at: effective, reason } = item;
  if (!isInt(expected, 1, Number.MAX_SAFE_INTEGER)) throw invalid('expected_revision must be a positive integer');
  if (!isInt(amount, 0, MAX_AMOUNT)) throw invalid(`amount must be an integer from 0 to ${MAX_AMOUNT}`);
  if (typeof reason !== 'string' || codePoints(reason) < 1 || codePoints(reason) > 200) {
    throw invalid('reason must be 1 to 200 characters');
  }
  const at = I.parse(effective);
  if (at === null) throw invalid('effective_at must be an RFC 3339 instant with an offset');
  if (at.ms > nowMs()) throw invalid('effective_at must not be in the future'); // judged to the clock tick
  return { expected, amount, effective, at, reason };
}

/**
 * What may be corrected, in the order the errors are reported: captures and refunds are never
 * correctable; settlement members only in a batch; the revision must be current; the amount may
 * not fall below what has already been refunded.
 */
function checkEligible(state, payment, fields, { allowSettlementMember }) {
  const linked = payment.authorization_id !== null || payment.refund_of !== null ||
    (!allowSettlementMember && payment.settlement_id !== null);
  if (linked) throw new ApiError(422, 'linked_payment_immutable', 'this payment cannot be corrected on its own');
  const latest = payment.revisions[payment.revisions.length - 1];
  if (fields.expected !== latest.revision) throw conflict('stale_revision', `the latest revision is ${latest.revision}`);
  if (fields.amount < refundedTotal(state, payment.id)) {
    throw new ApiError(422, 'refund_exceeds_payment', 'the payment has already been refunded for more');
  }
}

/**
 * Commit every plan [{payment, fields}] in one step: the money differences move together, all
 * new revisions share one recorded instant, and nothing changes unless the whole set is
 * affordable now and never overdraws a wallet at any past boundary.
 * Returns the new revisions in plan order.
 */
function commit(state, plans, batchId) {
  // Current funds: each wallet's net change across all proposed revisions.
  const net = new Map();
  for (const { payment, fields } of plans) {
    const diff = fields.amount - payment.revisions[payment.revisions.length - 1].amount;
    net.set(payment.from, (net.get(payment.from) || 0) - diff);
    net.set(payment.to, (net.get(payment.to) || 0) + diff);
  }
  for (const [id, delta] of net) {
    const user = state.users.get(id);
    if (user.balance + delta - user.held < 0) throw conflict('insufficient_funds', 'available balance is too low');
    if (user.balance + delta > MAX_BALANCE) throw invalid('receiving wallet would exceed the maximum balance');
  }

  // One recorded instant, strictly later than the previous one of every payment involved.
  const now = nowMs();
  let latestPrevious = null;
  for (const { payment } of plans) {
    const previous = I.parseCached(payment.revisions[payment.revisions.length - 1].recorded_at);
    if (latestPrevious === null || I.compare(previous, latestPrevious) > 0) latestPrevious = previous;
  }
  const recordedMs = I.compare(I.fromMs(now), latestPrevious) > 0 ? now : latestPrevious.ms + 1;
  const recordedAt = formatTimestamp(recordedMs);

  let seq = state.counters.revisionSeq;
  const revisions = plans.map(({ payment, fields }) => ({
    revision: payment.revisions.length + 1, amount: fields.amount, effective_at: fields.effective,
    recorded_at: recordedAt, reason: fields.reason, seq: ++seq, correction_batch_id: batchId,
  }));
  const proposed = new Map(plans.map(({ payment }, i) => [payment.id, revisions[i]]));
  const horizon = { ms: now, rest: '9'.repeat(12) }; // every instant of the current tick is "now"
  if (history.causesHistoricalOverdraft(state, proposed, horizon)) {
    throw conflict('historical_overdraft', 'the corrections would overdraw a wallet at an earlier time');
  }

  state.counters.revisionSeq = seq;
  plans.forEach(({ payment }, i) => payment.revisions.push(revisions[i]));
  for (const [id, delta] of net) state.users.get(id).balance += delta;
  return revisions;
}

/** The API form of a revision. */
function revisionJson(paymentId, r) {
  return {
    payment_id: paymentId, revision: r.revision, amount: r.amount, effective_at: r.effective_at,
    recorded_at: r.recorded_at, reason: r.reason, correction_batch_id: r.correction_batch_id || null,
  };
}

module.exports = { parseFields, checkEligible, commit, revisionJson };
