// The history behind every temporal answer. Money never moves here; this module only *reads*
// the append-only record: payment revisions and authorization events.
//
// A view is (A, K, kseqLimit):
//   A         instant the answer is "as of" (BigInt ns); movements and events at or before A count
//   K         "known at" instant (BigInt ns) or null for "everything known when the read begins"
//   kseqLimit knowledge position: only revisions/events committed at or before it are known
// "Known" is decided by sequence number, never by comparing clock readings, so a revision committed in
// the same clock tick as a later read is still known to that read.
import { publicPayment } from './state.js';

export const FOREVER = Number.MAX_SAFE_INTEGER;

// The latest revision of `p` known in the view, or null when none was known yet.
export function selected(p, K, kseqLimit) {
  const revs = p.revisions;
  for (let i = revs.length - 1; i >= 0; i--) {
    const r = revs[i];
    if (r.kseq <= kseqLimit && (K === null || r.rec <= K)) return r;
  }
  return null;
}

const sign = (p, userId) => (p.from_user_id === userId ? -1 : p.to_user_id === userId ? 1 : 0);

// Wallet total as of A.
export function totalAt(s, user, A, K, kseqLimit) {
  let total = user.opening;
  for (const p of s.payments) {
    const sg = sign(p, user.id);
    if (sg === 0) continue;
    const r = selected(p, K, kseqLimit);
    if (r && r.eff <= A) total += sg * r.amount;
  }
  return total;
}

// Captures of an authorization, in order, derived from its capture payments (immutable linked payments).
export function capturesOf(s, a) {
  const out = [];
  a.payment_ids.forEach((id, i) => {
    const p = s.paymentById.get(id);
    if (!p) return;
    const first = p.revisions[0];
    out.push({ t: p.ts, kseq: first.kseq, amount: first.amount, final: a.status === 'captured' && i === a.payment_ids.length - 1 });
  });
  return out;
}

// Amount of this authorization still held as of the view.
export function holdAt(s, a, A, K, kseqLimit) {
  if (a.seededClosed) return 0;
  const known = (t, ks) => t <= A && (K === null || t <= K) && ks <= kseqLimit;
  if (!known(a.createdNs, a.kseq)) return 0;
  if (a.expNs <= A) return 0; // expiry takes effect at expires_at; once creation is known so is the deadline
  let remaining = a.amount - a.initialCaptured;
  for (const c of capturesOf(s, a)) {
    if (!known(c.t, c.kseq)) continue;
    remaining -= c.amount;
    if (c.final || remaining <= 0) return 0;
  }
  if (a.voidNs !== null && known(a.voidNs, a.voidKseq)) return 0;
  return remaining;
}

export function heldAtView(s, user, A, K, kseqLimit) {
  let held = 0;
  for (const a of s.authorizations) if (a.from_user_id === user.id) held += holdAt(s, a, A, K, kseqLimit);
  return held;
}

// All four money fields of a view.
// `moveA` bounds the money movements; it defaults to A. A default (present-instant) read passes the end of the current
// clock tick here so a movement accepted as "not later than now" is never missed, while holds expire at the plain reading A.
export function viewOf(s, user, A, K, kseqLimit = FOREVER, moveA = A) {
  const total = totalAt(s, user, moveA, K, kseqLimit);
  const held = heldAtView(s, user, A, K, kseqLimit);
  return { total, held, available: total - held };
}

// ---- statements ----

const idLess = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// Full-window statement for a user, before pagination.
export function statementOf(s, user, fromNs, toNsExclusive, K, kseqLimit) {
  const mine = [];
  let opening = user.opening;
  let closing = user.opening;
  for (const p of s.payments) {
    const sg = sign(p, user.id);
    if (sg === 0) continue;
    const r = selected(p, K, kseqLimit);
    if (!r) continue;
    if (fromNs !== null && r.eff < fromNs) opening += sg * r.amount;
    if (r.eff < toNsExclusive) closing += sg * r.amount;
    if ((fromNs === null || r.eff >= fromNs) && r.eff < toNsExclusive) mine.push({ p, r, sg });
  }
  mine.sort((a, b) => (a.r.eff < b.r.eff ? -1 : a.r.eff > b.r.eff ? 1 : idLess(a.p.payment_id, b.p.payment_id)));
  let balance = opening;
  const entries = mine.map(({ p, r, sg }) => {
    const delta = sg * r.amount;
    balance += delta;
    return {
      payment: { ...publicPayment(p), amount: r.amount },
      delta,
      balance_after: balance,
      revision: r.revision,
      effective_at: r.effective_at,
      recorded_at: r.recorded_at,
    };
  });
  return { opening_balance: opening, entries, closing_balance: closing };
}

// ---- historical overdraft ----

// Would the latest revisions, with every proposed revision in `proposals` (Map payment -> { amount, eff }) applied together, ever leave
// `user`'s total or available negative at some boundary? Boundaries are grouped by exact instant and each
// group's combined effect is applied before testing.
export function overdrawsHistory(s, user, proposals) {
  const events = new Map(); // ns -> { dt, dh }
  const at = (t) => { if (!events.has(t)) events.set(t, { dt: 0, dh: 0 }); return events.get(t); };
  for (const p of s.payments) {
    const sg = sign(p, user.id);
    if (sg === 0) continue;
    const r = proposals && proposals.has(p) ? proposals.get(p) : selected(p, null, FOREVER);
    if (r) at(r.eff).dt += sg * r.amount;
  }
  for (const a of s.authorizations) {
    if (a.from_user_id !== user.id || a.seededClosed) continue;
    let remaining = a.amount - a.initialCaptured;
    at(a.createdNs).dh += remaining;
    const timeline = [];
    for (const c of capturesOf(s, a)) timeline.push({ t: c.t, kind: 'capture', c });
    if (a.voidNs !== null) timeline.push({ t: a.voidNs, kind: 'void' });
    timeline.sort((x, y) => (x.t < y.t ? -1 : x.t > y.t ? 1 : 0));
    for (const ev of timeline) {
      if (remaining <= 0 || ev.t >= a.expNs) break;
      const e = at(ev.t);
      if (ev.kind === 'capture') {
        remaining -= ev.c.amount;
        e.dh -= ev.c.amount;
        if (ev.c.final || remaining <= 0) { e.dh -= Math.max(remaining, 0); remaining = 0; }
      } else {
        e.dh -= remaining;
        remaining = 0;
      }
    }
    if (remaining > 0) at(a.expNs).dh -= remaining;
  }
  let total = user.opening;
  let held = 0;
  for (const t of [...events.keys()].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0))) {
    const e = events.get(t);
    total += e.dt;
    held += e.dh;
    if (total < 0 || total - held < 0) return true;
  }
  return false;
}
