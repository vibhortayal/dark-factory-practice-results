'use strict';

const { notFound, forbidden, conflict, invalid, ApiError } = require('../errors');
const { codePoints } = require('../validation');
const { nowMs, formatTimestamp } = require('../clock');
const I = require('../instant');
const history = require('../history');
const { MAX_AMOUNT } = require('../validation');
const { MAX_BALANCE } = require('../constants');

const isInt = (v, min, max) => typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;

/** Every field is required; every invalid one (also a wrong JSON type) is 422. */
function parseCorrection(body) {
  const { expected_revision: expected, amount, effective_at: effective, reason } = body;
  if (!isInt(expected, 1, Number.MAX_SAFE_INTEGER)) throw invalid('expected_revision must be a positive integer');
  if (!isInt(amount, 0, MAX_AMOUNT)) throw invalid(`amount must be an integer from 0 to ${MAX_AMOUNT}`);
  if (typeof reason !== 'string' || codePoints(reason) < 1 || codePoints(reason) > 200) {
    throw invalid('reason must be 1 to 200 characters');
  }
  const at = I.parse(effective);
  if (at === null) throw invalid('effective_at must be an RFC 3339 instant with an offset');
  if (at.ms > nowMs()) throw invalid('effective_at must not be in the future'); // judged to the clock tick
  return { expected, amount, effective, reason };
}

/** `POST /payments/{id}/corrections`: append a revision and move the difference, atomically. */
function correctPayment({ state, user, body, params }) {
  const { expected, amount, effective, reason } = parseCorrection(body);
  const payment = state.paymentsById.get(params.id);
  if (!payment) throw notFound('no such payment');
  if (payment.from !== user.id) throw forbidden('only the sender may correct a payment');
  if (payment.settlement_id !== null || payment.authorization_id !== null) {
    throw new ApiError(422, 'linked_payment_immutable', 'settlement members and captures cannot be corrected');
  }
  const latest = payment.revisions[payment.revisions.length - 1];
  if (expected !== latest.revision) throw conflict('stale_revision', `the latest revision is ${latest.revision}`);

  // An increase is paid by the sender, a decrease by the receiver.
  const difference = amount - latest.amount;
  const sender = state.users.get(payment.from);
  const receiver = state.users.get(payment.to);
  const debited = difference >= 0 ? sender : receiver;
  const credited = difference >= 0 ? receiver : sender;
  const size = Math.abs(difference);
  if (debited.balance - debited.held < size) throw conflict('insufficient_funds', 'available balance is too low');
  if (credited.balance + size > MAX_BALANCE) throw invalid('receiving wallet would exceed the maximum balance');

  // Recorded times for one payment strictly increase, also within one clock tick.
  const previous = I.parseCached(latest.recorded_at);
  const now = nowMs();
  const recordedMs = I.compare(I.fromMs(now), previous) > 0 ? now : previous.ms + 1;
  const revision = {
    revision: latest.revision + 1, amount, effective_at: effective, recorded_at: formatTimestamp(recordedMs),
    reason, seq: state.counters.revisionSeq + 1,
  };
  const horizon = { ms: now, rest: '9'.repeat(12) }; // every instant of the current tick is "now"
  if (history.causesHistoricalOverdraft(state, payment, revision, horizon)) {
    throw conflict('historical_overdraft', 'the correction would overdraw a wallet at an earlier time');
  }

  state.counters.revisionSeq += 1;
  payment.revisions.push(revision);
  debited.balance -= size;
  credited.balance += size;
  return {
    status: 201,
    body: {
      payment_id: payment.id, revision: revision.revision, amount: revision.amount,
      effective_at: revision.effective_at, recorded_at: revision.recorded_at, reason: revision.reason,
    },
  };
}

/** `GET /payments/{id}/revisions`: only the two parties may read the history. */
function listRevisions({ state, user, params }) {
  const payment = state.paymentsById.get(params.id);
  if (!payment || (payment.from !== user.id && payment.to !== user.id)) throw notFound('no such payment');
  return {
    status: 200,
    body: {
      revisions: payment.revisions.map((r) => ({
        payment_id: payment.id, revision: r.revision, amount: r.amount,
        effective_at: r.effective_at, recorded_at: r.recorded_at, reason: r.reason,
      })),
    },
  };
}

module.exports = { correctPayment, listRevisions };
