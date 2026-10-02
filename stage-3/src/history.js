'use strict';

/**
 * The historical ledger, as pure functions over the state.
 *
 * Money: every user has an opening balance. Every payment has an append-only list of revisions;
 * in a view with knowledge instant K the payment's *selected revision* is its latest revision
 * recorded at or before K (none yet recorded: the payment contributes nothing). A selected
 * revision is one *movement* of its amount from sender to receiver at its effective instant.
 *
 * Holds: an authorization reserves money from its creation until it is released (a final
 * capture, a void or its expiry); captures reduce it when they happen. Which of these events
 * are known at K follows their server-assigned times; once a creation is known the expiry
 * deadline is known too.
 *
 * Nothing here changes the state.
 */

const I = require('./instant');

const codePointCompare = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));

const recordedOf = (rev) => I.parseCached(rev.recorded_at);
const effectiveOf = (rev) => I.parseCached(rev.effective_at);

/** Latest revision of `p` known at `known` (null: all) and within `seqLimit` (null: all). */
function selectRevision(p, known, seqLimit) {
  for (let i = p.revisions.length - 1; i >= 0; i--) {
    const rev = p.revisions[i];
    if (seqLimit !== null && rev.seq > seqLimit) continue;
    if (known !== null && I.compare(recordedOf(rev), known) > 0) continue;
    return rev;
  }
  return null;
}

/** The movements of `userId` in a view: [{t, delta, payment, rev}], unordered. */
function movements(state, userId, known, seqLimit, override) {
  const out = [];
  for (const p of state.userPayments.get(userId) || []) {
    const rev = override && override.paymentId === p.id ? override.rev : selectRevision(p, known, seqLimit);
    if (rev === null) continue;
    out.push({ t: effectiveOf(rev), delta: p.from === userId ? -rev.amount : rev.amount, payment: p, rev });
  }
  return out;
}

// ---- holds ---------------------------------------------------------------------------------

/** The lifecycle facts of one authorization as instants. */
function holdInfo(state, a) {
  const captures = a.payment_ids.map((id) => state.paymentsById.get(id)).filter(Boolean)
    .map((p) => ({ t: I.parseCached(p.created_at), amount: p.amount }));
  const captured = captures.reduce((sum, c) => sum + c.amount, 0);
  return {
    created: I.parseCached(a.created_at),
    expires: I.parseCached(a.expires_at),
    closed: a.closed_at === null || a.closed_at === undefined ? null : I.parseCached(a.closed_at),
    preCaptured: Math.max(0, a.captured_amount - captured), // captured before any record exists (seeded)
    captures,
  };
}

/** When the hold is released, as known at `known`: the deadline, or an earlier known close. */
function releaseTime(info, known) {
  let release = info.expires;
  if (info.closed !== null && (known === null || I.compare(info.closed, known) <= 0) && I.compare(info.closed, release) < 0) {
    release = info.closed;
  }
  return release;
}

/** The amount still held by `a` at instant `at`, as known at `known`. */
function standing(a, info, at, known) {
  if (I.compare(info.created, at) > 0) return 0;
  if (known !== null && I.compare(info.created, known) > 0) return 0;
  if (I.compare(releaseTime(info, known), at) <= 0) return 0;
  let remaining = a.amount - info.preCaptured;
  for (const c of info.captures) {
    if (I.compare(c.t, at) <= 0 && (known === null || I.compare(c.t, known) <= 0)) remaining -= c.amount;
  }
  return remaining;
}

function heldAt(state, userId, at, known) {
  let held = 0;
  for (const a of state.authorizations) {
    if (a.from !== userId || a.no_history) continue;
    held += standing(a, holdInfo(state, a), at, known);
  }
  return held;
}

// ---- views ---------------------------------------------------------------------------------

/** total / held / available of a user at instant `at`, knowing what was recorded by `known`. */
function view(state, user, at, known) {
  let total = user.opening_balance;
  for (const m of movements(state, user.id, known, null, null)) {
    if (I.compare(m.t, at) <= 0) total += m.delta;
  }
  const held = heldAt(state, user.id, at, known);
  return { total, held, available: total - held };
}

// ---- statements ----------------------------------------------------------------------------

/**
 * The statement of `userId` for the half-open window [from, to) (from null: the wallet's
 * opening), over the revisions known at `known` and recorded within `seqLimit`.
 */
function statement(state, user, { from, to, known, seq }) {
  const all = movements(state, user.id, known, seq, null);
  let opening = user.opening_balance;
  const inWindow = [];
  for (const m of all) {
    if (from !== null && I.compare(m.t, from) < 0) opening += m.delta;
    else if (I.compare(m.t, to) < 0) inWindow.push(m);
  }
  inWindow.sort((a, b) => I.compare(a.t, b.t) || codePointCompare(a.payment.id, b.payment.id));
  let running = opening;
  const entries = inWindow.map((m) => {
    running += m.delta;
    return { payment: m.payment, rev: m.rev, delta: m.delta, balanceAfter: running };
  });
  return { opening, closing: running, entries };
}

// ---- boundary walk for corrections -----------------------------------------------------------

/** Timeline of [{t, total, held}] checkpoints (events at one instant combined), latest knowledge. */
function checkpoints(state, user, override, now) {
  const events = [];
  for (const m of movements(state, user.id, null, null, override)) {
    if (I.compare(m.t, now) <= 0) events.push({ t: m.t, dTotal: m.delta, dHeld: 0 });
  }
  for (const a of state.authorizations) {
    if (a.from !== user.id || a.no_history) continue;
    const info = holdInfo(state, a);
    if (I.compare(info.created, now) > 0) continue;
    events.push({ t: info.created, dTotal: 0, dHeld: a.amount - info.preCaptured });
    let remaining = a.amount - info.preCaptured;
    for (const c of info.captures) {
      remaining -= c.amount;
      if (I.compare(c.t, now) <= 0) events.push({ t: c.t, dTotal: 0, dHeld: -c.amount });
    }
    const release = releaseTime(info, null);
    if (remaining > 0 && I.compare(release, now) <= 0) events.push({ t: release, dTotal: 0, dHeld: -remaining });
  }
  events.sort((x, y) => I.compare(x.t, y.t));
  const out = [];
  let total = user.opening_balance;
  let held = 0;
  for (const e of events) {
    total += e.dTotal;
    held += e.dHeld;
    const last = out[out.length - 1];
    if (last && I.compare(last.t, e.t) === 0) {
      last.total = total;
      last.held = held;
    } else out.push({ t: e.t, total, held });
  }
  return out;
}

/**
 * True when applying `rev` to `payment` would push a party's total or available below zero at a
 * past boundary, lower than it already was there.
 */
function causesHistoricalOverdraft(state, payment, rev, now) {
  for (const id of [payment.from, payment.to]) {
    const user = state.users.get(id);
    const before = checkpoints(state, user, null, now);
    const after = checkpoints(state, user, { paymentId: payment.id, rev }, now);
    let b = -1;
    for (const cp of after) {
      while (b + 1 < before.length && I.compare(before[b + 1].t, cp.t) <= 0) b++;
      const prevTotal = b >= 0 ? before[b].total : user.opening_balance;
      const prevAvail = b >= 0 ? before[b].total - before[b].held : user.opening_balance;
      const total = cp.total;
      const avail = cp.total - cp.held;
      if ((total < 0 && total < prevTotal) || (avail < 0 && avail < prevAvail)) return true;
    }
  }
  return false;
}

module.exports = {
  selectRevision, movements, holdInfo, view, statement, causesHistoricalOverdraft, codePointCompare,
  recordedOf, effectiveOf,
};
