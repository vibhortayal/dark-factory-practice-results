'use strict';

/**
 * Every balance change goes through this module. Callers check affordability
 * and then call a function here in the same synchronous step, so no reader can
 * observe a debit without its credit or a negative balance.
 */

const { nextId } = require('./state');
const { invalid, conflict } = require('./errors');

const MAX_BALANCE = 2 ** 53;

function insufficient() {
  return conflict('insufficient_funds', 'balance is too low for this amount');
}

/** Record a payment and move the money. Throws before changing anything. */
function recordPayment(state, p) {
  const sender = state.users.get(p.from);
  const receiver = state.users.get(p.to);
  if (sender.balance < p.amount) throw insufficient();
  if (receiver.balance + p.amount > MAX_BALANCE && sender !== receiver) {
    throw invalid('receiving wallet would exceed the maximum balance');
  }
  sender.balance -= p.amount;
  receiver.balance += p.amount;
  return appendPayment(state, p);
}

/** Append a payment record without touching balances (settlements apply their own net). */
function appendPayment(state, p) {
  const payment = {
    id: p.id || nextId(state, 'payment', 'p_', state.paymentsById),
    from: p.from,
    to: p.to,
    amount: p.amount,
    note: p.note,
    visibility: p.visibility,
    request_id: p.requestId || null,
    settlement_id: p.settlementId || null,
    created_at: p.createdAt,
    seeded: Boolean(p.seeded),
  };
  state.payments.push(payment);
  state.paymentsById.set(payment.id, payment);
  return payment;
}

/**
 * Apply a batch of transfers atomically. Affordable iff every wallet ends
 * nonnegative once all incoming and outgoing transfers are netted.
 */
function applySettlement(state, transfers, createdAt) {
  const net = new Map();
  for (const t of transfers) {
    net.set(t.from, (net.get(t.from) || 0) - t.amount);
    net.set(t.to, (net.get(t.to) || 0) + t.amount);
  }
  for (const [id, delta] of net) {
    const after = state.users.get(id).balance + delta;
    if (after < 0) throw insufficient();
    if (after > MAX_BALANCE) throw invalid('receiving wallet would exceed the maximum balance');
  }
  const settlementId = nextId(state, 'settlement', 'st_', state.settlements);
  const payments = transfers.map((t) => appendPayment(state, { ...t, settlementId, createdAt }));
  for (const [id, delta] of net) state.users.get(id).balance += delta;
  state.settlements.set(settlementId, {
    id: settlementId,
    committed_at: createdAt,
    payment_ids: payments.map((p) => p.id),
  });
  return { settlementId, payments };
}

/** Equal split: whole units, extra units to the first participants. */
function equalShares(amount, n) {
  const base = Math.floor(amount / n);
  const extra = amount - base * n;
  return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
}

module.exports = { recordPayment, applySettlement, appendPayment, equalShares };
