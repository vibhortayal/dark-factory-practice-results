'use strict';

const { notFound, invalid, ApiError } = require('../errors');
const { isObject } = require('../json');
const { nextId } = require('../state');
const I = require('../instant');
const { parseFields, checkEligible, commit, revisionJson } = require('../corrections');

const MAX_ITEMS = 32;

/** `POST /correction-batches`: a settlement operator corrects several payments in one step. */
function createBatch({ state, body }) {
  const items = body.corrections;
  if (!Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS) {
    throw invalid('corrections must hold 1 to 32 objects');
  }
  if (!items.every(isObject)) throw invalid('every correction must be an object');
  const ids = items.map((item) => item.payment_id).filter((id) => typeof id === 'string');
  if (new Set(ids).size !== ids.length) throw invalid('payment_ids must be distinct');

  // Item errors, in input order: fields, unknown payment, immutability, revision, refunds.
  const plans = items.map((item) => {
    if (typeof item.payment_id !== 'string') throw invalid('payment_id must be a string');
    const fields = parseFields(item);
    const payment = state.paymentsById.get(item.payment_id);
    if (!payment) throw notFound(`no such payment ${JSON.stringify(item.payment_id)}`);
    checkEligible(state, payment, fields, { allowSettlementMember: true });
    return { payment, fields };
  });

  // Settlements: every member or none, all at one effective instant.
  const inBatch = new Set(plans.map((p) => p.payment.id));
  const bySettlement = new Map();
  for (const plan of plans) {
    const sid = plan.payment.settlement_id;
    if (sid === null) continue;
    if (!bySettlement.has(sid)) bySettlement.set(sid, []);
    bySettlement.get(sid).push(plan);
  }
  for (const sid of bySettlement.keys()) {
    if (!state.settlements.get(sid).payment_ids.every((id) => inBatch.has(id))) {
      throw new ApiError(422, 'incomplete_settlement', `settlement ${sid} must be corrected as a whole`);
    }
  }
  for (const group of bySettlement.values()) {
    if (!group.every((p) => I.compare(p.fields.at, group[0].fields.at) === 0)) {
      throw invalid('members of one settlement need identical effective instants');
    }
  }

  const id = nextId(state, 'batch', 'cb_', state.batches);
  const revisions = commit(state, plans, id);
  state.batches.set(id, { id, recorded_at: revisions[0].recorded_at, payment_ids: plans.map((p) => p.payment.id) });
  return {
    status: 201,
    body: {
      correction_batch_id: id,
      recorded_at: revisions[0].recorded_at,
      revisions: revisions.map((r, i) => revisionJson(plans[i].payment.id, r)),
    },
  };
}

module.exports = { createBatch };
