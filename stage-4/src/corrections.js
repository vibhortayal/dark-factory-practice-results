// Payment corrections: the single-payment endpoint and operator batches share one plan/check/commit path.
//   plan    validate fields, find the payments, check what each item may do
//   check   combined current affordability, then historical total/available for every affected wallet,
//           with ALL proposed revisions applied together
//   commit  append every revision in one synchronous step (one recorded_at, one knowledge position)
import { store, availableOf, tickStamp, clockMs } from './state.js';
import { conflict, forbidden, invalid, notFound, ApiError } from './errors.js';
import { has, isObject } from './json.js';
import { parseInstantNs, msToNs } from './instants.js';
import { stampAtUs } from './time.js';
import { overdrawsHistory } from './history.js';
import { MAX_AMOUNT } from './validate.js';

const err = (code, message) => { const e = invalid(message); e.code = code; return e; };
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

export const publicRevision = (p, r) => ({
  payment_id: p.payment_id,
  revision: r.revision,
  amount: r.amount,
  effective_at: r.effective_at,
  recorded_at: r.recorded_at,
  reason: r.reason,
  correction_batch_id: r.batch === undefined ? null : r.batch,
});

// Ordinary correction fields; every missing or invalid field, wrong JSON types included, is 422.
function fieldsOf(item) {
  if (!has(item, 'expected_revision') || !isInt(item.expected_revision) || item.expected_revision < 1) throw invalid('expected_revision must be a positive integer');
  if (!has(item, 'amount') || !isInt(item.amount) || item.amount < 0 || item.amount > MAX_AMOUNT) throw invalid('amount must be an integer from 0 to 1000000000');
  if (!has(item, 'reason') || typeof item.reason !== 'string' || [...item.reason].length < 1 || [...item.reason].length > 200) throw invalid('reason must be a string of 1 to 200 characters');
  const effNs = has(item, 'effective_at') ? parseInstantNs(item.effective_at) : null;
  if (effNs === null) throw invalid('effective_at must be an RFC 3339 instant with an offset');
  // "Not later than now": the clock reads whole milliseconds, so accept up to the end of the current millisecond.
  if (effNs > msToNs(clockMs(store.s)) + 999999n) throw invalid('effective_at must not be in the future');
  return { expected: item.expected_revision, amount: item.amount, reason: item.reason, effText: item.effective_at, effNs };
}

const latest = (p) => p.revisions[p.revisions.length - 1];

function planItem(s, item, id, { caller, batch }) {
  const f = fieldsOf(item);
  const p = s.paymentById.get(id);
  if (!p) throw notFound('no such payment');
  if (!batch && p.from_user_id !== caller.id) throw forbidden('only the original sender may correct a payment');
  if (p.authorization_id !== null || p.refund_of !== null || (!batch && p.settlement_id !== null)) {
    throw err('linked_payment_immutable', 'captures, refunds and settlement members cannot be corrected here');
  }
  if (f.amount < p.refunded) throw err('refund_exceeds_payment', 'a payment cannot be corrected below its refunded amount');
  const last = latest(p);
  if (f.expected !== last.revision) throw conflict('stale_revision', 'the payment has a newer revision');
  return { p, last, ...f, diff: f.amount - last.amount };
}

// Current affordability on the combined effect, then history with every proposal applied together.
function check(s, plans) {
  const net = new Map();
  for (const x of plans) {
    net.set(x.p.from_user_id, (net.get(x.p.from_user_id) || 0) - x.diff);
    net.set(x.p.to_user_id, (net.get(x.p.to_user_id) || 0) + x.diff);
  }
  for (const [uid, d] of net) {
    if (d < 0 && availableOf(s, s.users.get(uid)) + d < 0) throw conflict('insufficient_funds', 'available balance is below the difference');
  }
  const proposals = new Map(plans.map((x) => [x.p, { amount: x.amount, eff: x.effNs }]));
  for (const uid of net.keys()) {
    if (overdrawsHistory(s, s.users.get(uid), proposals)) throw conflict('historical_overdraft', 'the correction would overdraw a wallet at an earlier time');
  }
}

function commit(s, plans, batchId) {
  // One recorded_at for the whole step: the real clock, but strictly later than every member's previous one.
  let floorUs = 0;
  for (const x of plans) floorUs = Math.max(floorUs, Number(x.last.rec / 1000n) + 1);
  const stamp = stampAtUs(Math.max(tickStamp(s).ms * 1000, floorUs));
  const kseq = ++s.kseq; // one knowledge position: no read can see half a batch
  return plans.map((x) => {
    const rev = {
      revision: x.last.revision + 1, amount: x.amount, effective_at: x.effText, eff: x.effNs,
      recorded_at: stamp.text, rec: stamp.ns, reason: x.reason, kseq, batch: batchId,
    };
    x.p.revisions.push(rev);
    s.users.get(x.p.from_user_id).balance -= x.diff;
    s.users.get(x.p.to_user_id).balance += x.diff;
    return rev;
  });
}

export function correctPayment(user, id, body) {
  const s = store.s;
  // Single-payment order: validation, 404, 403, linked, refund bound, stale, current funds, history.
  const plan = planItem(s, body, id, { caller: user, batch: false });
  check(s, [plan]);
  const [rev] = commit(s, [plan], null);
  return publicRevision(plan.p, rev);
}

export function listRevisions(user, id) {
  const p = store.s.paymentById.get(id);
  if (!p || (p.from_user_id !== user.id && p.to_user_id !== user.id)) throw notFound('no such payment');
  return { revisions: p.revisions.map((r) => publicRevision(p, r)) };
}

export function correctBatch(user, body) {
  const s = store.s;
  const items = body.corrections;
  // Batch shape first.
  if (!Array.isArray(items) || items.length < 1 || items.length > 32 || items.some((x) => !isObject(x))) throw invalid('corrections must be an array of 1 to 32 objects');
  const ids = items.map((x) => x.payment_id);
  const strings = ids.filter((x) => typeof x === 'string');
  if (new Set(strings).size !== strings.length) throw invalid('payment_ids must be distinct');
  // Items in input order; the first item with an error decides.
  const plans = items.map((item) => {
    if (typeof item.payment_id !== 'string' || item.payment_id === '') throw invalid('payment_id must be a string');
    return planItem(s, item, item.payment_id, { caller: user, batch: true });
  });
  // Settlement completeness, then identical effective instants within a settlement.
  const inBatch = new Set(plans.map((x) => x.p.payment_id));
  const bySettlement = new Map();
  for (const x of plans) {
    if (x.p.settlement_id === null) continue;
    if (!bySettlement.has(x.p.settlement_id)) bySettlement.set(x.p.settlement_id, []);
    bySettlement.get(x.p.settlement_id).push(x);
  }
  for (const [sid] of bySettlement) {
    const settlement = s.settlements.find((z) => z.id === sid);
    const members = settlement ? settlement.payment_ids : [];
    if (members.some((m) => !inBatch.has(m))) throw err('incomplete_settlement', 'every member of a settlement must be corrected together');
  }
  for (const group of bySettlement.values()) {
    if (group.some((x) => x.effNs !== group[0].effNs)) throw invalid('members of one settlement must share one effective instant');
  }
  check(s, plans);
  const batchId = `cb_${String(++s.counters.cb).padStart(8, '0')}`;
  const revs = commit(s, plans, batchId);
  return { correction_batch_id: batchId, recorded_at: revs[0].recorded_at, revisions: revs.map((r, i) => publicRevision(plans[i].p, r)) };
}
