'use strict';

const { setState, getState } = require('../state');
const { parseFixture, buildState } = require('../fixture');
const { exportState, importState } = require('../snapshot');
const { setFloor } = require('../clock');

async function reset({ body }) {
  const plan = parseFixture(body); // all validation before anything changes
  const state = await buildState(plan);
  setState(state);
  setFloor(state.clockFloor);
  return { status: 204 };
}

function exportAll() {
  return { status: 200, body: exportState(getState()) };
}

function importAll({ body }) {
  const state = importState(body);
  setState(state);
  setFloor(state.clockFloor);
  return { status: 204 };
}

module.exports = { reset, exportAll, importAll };
