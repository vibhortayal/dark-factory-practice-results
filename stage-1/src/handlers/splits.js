'use strict';

const { notFound, invalid, malformed } = require('../errors');
const { assertTypes, requireField, checkAmount, checkNote } = require('../validation');
const { equalShares } = require('../ledger');
const { nowTimestamp } = require('../clock');
const { nextId } = require('../state');
const { addRequest } = require('./requests');
const { requestJson } = require('../serializers');

function createSplit({ state, user, body }) {
  assertTypes(body, { participant_handles: 'array' });
  const handles = requireField(body, 'participant_handles');
  if (!handles.every((h) => typeof h === 'string')) {
    throw malformed('participant_handles must hold strings');
  }
  const amount = checkAmount(requireField(body, 'amount'));
  const note = checkNote(body.note);
  if (handles.length === 0) throw invalid('participant_handles must not be empty');
  if (new Set(handles).size !== handles.length) throw invalid('participant_handles has a duplicate');
  const participants = handles.map((h) => {
    const p = state.byHandle.get(h);
    if (!p) throw notFound(`no user has the handle ${JSON.stringify(h)}`);
    return p;
  });

  const createdAt = nowTimestamp();
  const shares = equalShares(amount, participants.length);
  const requests = [];
  participants.forEach((p, i) => {
    if (p === user) return;
    requests.push(addRequest(state, { requester: user.id, payer: p.id, amount: shares[i], note, createdAt }));
  });
  return {
    status: 201,
    body: {
      split_id: nextId(state, 'split', 'sp_'),
      amount,
      currency: state.currency,
      note,
      shares: participants.map((p, i) => ({ handle: p.handle, amount: shares[i] })),
      requests: requests.map((r) => requestJson(state, r)),
      created_at: createdAt,
    },
  };
}

module.exports = { createSplit };
