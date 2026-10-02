'use strict';

/**
 * Route table. Each method entry says how the pipeline treats it:
 *   body:      'none' | 'json' (any value) | 'object' | 'objectOptional' (empty body = {})
 *   idem:      requires Idempotency-Key (the five idempotent write paths)
 *   operator:  caller must be a settlement operator
 */

const { health } = require('./handlers/health');
const { signup, login } = require('./handlers/auth');
const { me } = require('./handlers/me');
const { createPayment } = require('./handlers/payments');
const { createRequest, payRequest, declineRequest, cancelRequest, listRequests } = require('./handlers/requests');
const { createSplit } = require('./handlers/splits');
const { activity } = require('./handlers/activity');
const { createSettlement } = require('./handlers/settlements');
const { reset, exportAll, importAll } = require('./handlers/testControl');

const IDEM_OBJECT = { body: 'object', idem: true };

const exact = {
  '/health': { public: true, GET: { fn: health, body: 'none' } },
  '/_test/reset': { public: true, POST: { fn: reset, body: 'json' } },
  '/_test/export': { public: true, GET: { fn: exportAll, body: 'none' } },
  '/_test/import': { public: true, POST: { fn: importAll, body: 'json' } },
  '/auth/signup': { public: true, POST: { fn: signup, body: 'object' } },
  '/auth/login': { public: true, POST: { fn: login, body: 'object' } },
  '/me': { GET: { fn: me, body: 'none' } },
  '/payments': { POST: { fn: createPayment, ...IDEM_OBJECT } },
  '/requests': {
    GET: { fn: listRequests, body: 'none' },
    POST: { fn: createRequest, ...IDEM_OBJECT },
  },
  '/splits': { POST: { fn: createSplit, ...IDEM_OBJECT } },
  '/activity': { GET: { fn: activity, body: 'none' } },
  '/settlements': { POST: { fn: createSettlement, ...IDEM_OBJECT, operator: true } },
};

const requestActions = {
  pay: { POST: { fn: payRequest, body: 'objectOptional', idem: true } },
  decline: { POST: { fn: declineRequest, body: 'none' } },
  cancel: { POST: { fn: cancelRequest, body: 'none' } },
};

// Paths below these prefixes belong to the authenticated API; unknown paths there need a token before 404.
const AUTH_FAMILIES = new Set(['me', 'payments', 'requests', 'splits', 'activity', 'settlements']);

/** Returns {route, params, family} where route is null when no path matches. */
function match(pathname) {
  if (Object.prototype.hasOwnProperty.call(exact, pathname)) return { route: exact[pathname], params: {} };
  const m = /^\/requests\/([^/]+)\/([a-z]+)$/.exec(pathname);
  if (m && Object.prototype.hasOwnProperty.call(requestActions, m[2])) {
    let id;
    try {
      id = decodeURIComponent(m[1]);
    } catch (_) {
      id = m[1];
    }
    return { route: requestActions[m[2]], params: { id } };
  }
  return { route: null, params: {}, needsAuth: AUTH_FAMILIES.has(pathname.split('/')[1]) };
}

module.exports = { match };
