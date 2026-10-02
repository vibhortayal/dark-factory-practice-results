'use strict';

/**
 * The request pipeline. Order of checks (acceptance map C11):
 *   authentication -> operator permission -> Idempotency-Key -> body parse
 *   -> claimed-key replay/conflict -> endpoint validation and effect.
 */

const { ApiError, malformed, invalid, unauthenticated, forbidden, notFound } = require('./errors');
const { parseJson, isObject } = require('./json');
const { getState } = require('./state');
const idempotency = require('./idempotency');
const { codePoints } = require('./validation');
const { match } = require('./routes');
const { sweep } = require('./holds');
const { nowMs, freeze, unfreeze } = require('./clock');

const isThenable = (v) => v !== null && typeof v === 'object' && typeof v.then === 'function';

function authenticate(headers) {
  const m = /^Bearer\s+(\S+)$/i.exec(headers.authorization || '');
  const state = getState();
  const userId = m && state.tokens.get(m[1]);
  const user = userId && state.users.get(userId);
  if (!user) throw unauthenticated('missing, malformed or unknown bearer token');
  return user;
}

function readBody(spec, buffer) {
  if (spec.body === 'none') return undefined;
  if (buffer === null) throw invalid('request body exceeds the size the service processes');
  if (spec.body === 'objectOptional' && buffer.length === 0) return {};
  const value = parseJson(buffer);
  if (spec.body !== 'json' && !isObject(value)) throw malformed('body must be a JSON object');
  return value;
}

function idempotencyKey(headers) {
  const key = headers['idempotency-key'];
  if (key === undefined || key === '') {
    throw new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key header is required');
  }
  if (codePoints(key) > 255) throw invalid('Idempotency-Key must be 1 to 255 characters');
  return key;
}

/** Runs one request; returns {status, body?}. Handlers may be async (hashing, reset). */
async function handle(request) {
  // The clock is read once: the synchronous part of the request sees a single instant.
  freeze();
  let result;
  try {
    result = prepareAndRun(request);
  } finally {
    unfreeze();
  }
  return result;
}

function prepareAndRun({ method, pathname, query, headers, buffer }) {
  sweep(getState(), nowMs()); // expiry is derived from the clock on every request
  // buffer === null means the body exceeded the service's size cap and was not read.
  const { route, params, needsAuth, scopePath } = match(pathname);
  if (!route) {
    if (needsAuth) authenticate(headers);
    throw notFound('no such route');
  }
  const spec = method !== 'public' && Object.prototype.hasOwnProperty.call(route, method) ? route[method] : null;
  if (!spec) {
    if (!route.public) authenticate(headers);
    throw notFound('no such route');
  }

  const user = route.public ? null : authenticate(headers);
  if (spec.operator && !getState().operators.has(user.id)) throw forbidden('settlement operators only');

  const scope = scopePath || pathname; // percent-decoded path parameters share one idempotency scope
  const key = spec.idem ? idempotencyKey(headers) : null;
  const body = readBody(spec, buffer);

  if (spec.idem) {
    const replay = idempotency.lookup(getState(), user.id, method, scope, key, body);
    if (replay) return replay;
  }

  // Idempotent handlers must stay synchronous: lookup, effect and store then run in one
  // uninterrupted step, so concurrent same-key requests cannot interleave.
  const result = spec.fn({ state: getState(), user, body, params, query });
  if (isThenable(result)) {
    if (spec.idem) throw new Error('idempotent handlers must be synchronous');
    return result; // async handlers (login, signup, reset) finish after the instant is released
  }
  if (spec.idem && result.status === 201) {
    idempotency.store(getState(), user.id, method, scope, key, body, result.body);
  }
  return result;
}

module.exports = { handle };
