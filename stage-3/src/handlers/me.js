'use strict';

const { instantParam } = require('../validation');
const { nowMs } = require('../clock');
const I = require('../instant');
const history = require('../history');

/**
 * `GET /me`, optionally as of an instant (`as_of`) and as known at an instant (`known_at`).
 * Without either, the current values; all four money fields always describe one view.
 */
function me({ state, user, search }) {
  const asOf = instantParam(search, 'as_of');
  const knownAt = instantParam(search, 'known_at');
  let money = { total: user.balance, held: user.held, available: user.balance - user.held };
  if (asOf !== undefined || knownAt !== undefined) {
    const at = asOf !== undefined ? asOf.at : I.fromMs(nowMs());
    money = history.view(state, user, at, knownAt === undefined ? null : knownAt.at);
  }
  const body = {
    user_id: user.id, display_name: user.display_name, handle: user.handle,
    balance: money.total, total: money.total, available: money.available, held: money.held,
    currency: state.currency, minor_units: state.minorUnits,
  };
  if (asOf !== undefined) body.as_of = asOf.text;
  if (knownAt !== undefined) body.known_at = knownAt.text;
  return { status: 200, body };
}

module.exports = { me };
