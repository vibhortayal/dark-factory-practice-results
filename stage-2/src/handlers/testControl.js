'use strict';

const { setState, getState } = require('../state');
const { parseFixture, buildState } = require('../fixture');
const { exportState, importState } = require('../snapshot');

async function reset({ body }) {
  const plan = parseFixture(body); // all validation before anything changes
  setState(await buildState(plan));
  return { status: 204 };
}

function exportAll() {
  return { status: 200, body: exportState(getState()) };
}

function importAll({ body }) {
  setState(importState(body));
  return { status: 204 };
}

module.exports = { reset, exportAll, importAll };
