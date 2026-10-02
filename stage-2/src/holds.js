'use strict';

/**
 * Authorizations (holds). A hold reserves part of the payer's `total` without moving it:
 * `user.held` is the sum of the remaining amounts of that user's open authorizations.
 * Like the ledger, every function here runs inside one synchronous handler step.
 *
 * Expiry is derived from the clock, never from a timer: `sweep` runs at the start of every
 * request and closes every open authorization whose deadline has passed.
 */

const { nextId } = require('./state');
const { MAX_BALANCE } = require('./constants');
const { invalid } = require('./errors');
const { appendPayment } = require('./ledger');

const remainingOf = (a) => (a.status === 'open' ? a.amount - a.captured_amount : 0);

/** Register an authorization record (open ones start holding funds). */
function addAuthorization(state, a) {
  state.authorizations.push(a);
  state.authById.set(a.id, a);
  if (a.status === 'open') {
    state.openAuths.add(a.id);
    state.users.get(a.from).held += remainingOf(a);
    state.nextExpiryMs = Math.min(state.nextExpiryMs, a.expires_ms);
  }
  return a;
}

function newAuthorizationId(state) {
  return nextId(state, 'authorization', 'a_', state.authById);
}

/** Close an open authorization with `status`, releasing whatever is still held. */
function close(state, a, status) {
  state.users.get(a.from).held -= remainingOf(a);
  a.status = status;
  state.openAuths.delete(a.id);
}

/** Expire every open authorization whose deadline is at or before `nowMs`. */
function sweep(state, nowMs) {
  if (nowMs < state.nextExpiryMs) return;
  let next = Infinity;
  for (const id of [...state.openAuths]) {
    const a = state.authById.get(id);
    if (a.expires_ms <= nowMs) close(state, a, 'expired');
    else next = Math.min(next, a.expires_ms);
  }
  state.nextExpiryMs = next;
}

/**
 * Move `amount` from the payer to the receiver against an open authorization.
 * A final capture (or one that takes the whole remainder) closes it and releases the rest.
 */
function capture(state, a, amount, isFinal, createdAt) {
  const receiver = state.users.get(a.to);
  if (receiver.balance + amount > MAX_BALANCE) throw invalid('receiving wallet would exceed the maximum balance');
  const sender = state.users.get(a.from);
  const leftover = a.amount - a.captured_amount - amount;
  const closing = isFinal || leftover === 0;

  sender.balance -= amount;
  receiver.balance += amount;
  sender.held -= amount; // the reserved money has now moved
  a.captured_amount += amount;
  const payment = appendPayment(state, {
    from: a.from, to: a.to, amount, note: a.note, visibility: a.visibility,
    authorizationId: a.id, createdAt,
  });
  a.payment_ids.push(payment.id);
  a.payment_id = payment.id;
  if (closing) {
    // `remainingOf` now reports the uncaptured part, which is released with the status change.
    close(state, a, 'captured');
  }
  return payment;
}

/** Void: release the remainder, keep every capture record. */
function voidAuthorization(state, a) {
  close(state, a, 'voided');
}

module.exports = { addAuthorization, newAuthorizationId, sweep, capture, voidAuthorization, remainingOf };
