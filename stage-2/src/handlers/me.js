'use strict';

function me({ state, user }) {
  return {
    status: 200,
    body: {
      user_id: user.id, display_name: user.display_name, handle: user.handle,
      balance: user.balance, total: user.balance, available: user.balance - user.held, held: user.held,
      currency: state.currency, minor_units: state.minorUnits,
    },
  };
}

module.exports = { me };
