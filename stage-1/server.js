'use strict';
const http = require('http');
const { ApiError, err } = require('./src/util');
const H = require('./src/handlers');

const PORT = Number(process.env.PORT) || 8080;
const BODY_LIMIT = 1 << 20;            // 1 MiB for the public API
const TEST_BODY_LIMIT = 512 << 20;     // export/import/reset may carry a whole state

// [method, pattern, handler, authenticated, body limit]
const routes = [
  ['GET', /^\/health$/, H.health, false],
  ['POST', /^\/_test\/reset$/, H.reset, false, TEST_BODY_LIMIT],
  ['GET', /^\/_test\/export$/, H.exportState, false],
  ['POST', /^\/_test\/import$/, H.importState, false, TEST_BODY_LIMIT],
  ['POST', /^\/auth\/signup$/, H.signup, false],
  ['POST', /^\/auth\/login$/, H.login, false],
  ['GET', /^\/me$/, H.me, true],
  ['POST', /^\/payments$/, H.createPayment, true],
  ['POST', /^\/requests$/, H.createRequest, true],
  ['GET', /^\/requests$/, H.listRequests, true],
  ['POST', /^\/requests\/([^/]+)\/pay$/, H.payRequest, true],
  ['POST', /^\/requests\/([^/]+)\/decline$/, H.declineRequest, true],
  ['POST', /^\/requests\/([^/]+)\/cancel$/, H.cancelRequest, true],
  ['POST', /^\/splits$/, H.createSplit, true],
  ['GET', /^\/activity$/, H.listActivity, true],
  ['POST', /^\/settlements$/, H.createSettlement, true],
];

const JSON_TYPE = 'application/json; charset=utf-8';

function send(res, status, json, extraHeaders) {
  if (res.headersSent || res.writableEnded) return;
  if (status === 204) {
    res.writeHead(204);
    res.end();
    return;
  }
  const buf = Buffer.from(json, 'utf8');
  res.writeHead(status, Object.assign({ 'Content-Type': JSON_TYPE, 'Content-Length': buf.length }, extraHeaders));
  res.end(buf);
}

function sendError(res, e) {
  const apiErr = e instanceof ApiError ? e : null;
  if (!apiErr) console.error(e);
  const status = apiErr ? apiErr.status : 500;
  const code = apiErr ? apiErr.code : 'internal_error';
  const message = apiErr ? apiErr.message : 'internal error';
  send(res, status, JSON.stringify({ error: { code, message } }), apiErr && apiErr.allow ? { Allow: apiErr.allow } : undefined);
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooBig = false;
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) { tooBig = true; chunks.length = 0; } else if (!tooBig) chunks.push(c);
    });
    req.on('end', () => (tooBig ? reject(new ApiError(413, 'payload_too_large', 'request body too large')) : resolve(Buffer.concat(chunks))));
    req.on('error', reject);
  });
}

async function handle(req, res) {
  try {
    const url = new URL(req.url, 'http://localhost');
    let path = url.pathname;
    if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
    let match = null;
    const allowed = [];
    for (const route of routes) {
      const m = route[1].exec(path);
      if (!m) continue;
      if (route[0] === req.method) { match = { route, m }; break; }
      allowed.push(route[0]);
    }
    if (!match) {
      if (allowed.length) {
        const notAllowed = new ApiError(405, 'method_not_allowed', 'method not allowed');
        notAllowed.allow = allowed.join(', ');
        throw notAllowed;
      }
      throw err.notFound('no such route');
    }
    const { route, m } = match;
    const rawBody = await readBody(req, route[4] || BODY_LIMIT);
    let id;
    try { id = m[1] === undefined ? undefined : decodeURIComponent(m[1]); } catch (e) { id = m[1]; }
    const ctx = { method: req.method, path, query: url.searchParams, headers: req.headers, rawBody, params: { id } };
    const user = route[3] ? H.authenticate(req.headers) : null;
    const out = await route[2](ctx, user);
    send(res, out.status, out.json);
  } catch (e) {
    sendError(res, e);
  }
}

const server = http.createServer({ maxHeaderSize: 1 << 20 }, (req, res) => {
  handle(req, res).catch((e) => sendError(res, e));
});
server.keepAliveTimeout = 65000;
server.headersTimeout = 66000;
server.requestTimeout = 0;
server.on('clientError', (e, socket) => {
  if (!socket.writable) return;
  const body = JSON.stringify({ error: { code: 'malformed_request', message: 'bad request' } });
  socket.end('HTTP/1.1 400 Bad Request\r\nContent-Type: ' + JSON_TYPE + '\r\nContent-Length: ' + Buffer.byteLength(body) +
    '\r\nConnection: close\r\n\r\n' + body);
});
process.on('uncaughtException', (e) => console.error('uncaught', e));
process.on('unhandledRejection', (e) => console.error('unhandled', e));
process.on('SIGTERM', () => process.exit(0));
process.on('SIGINT', () => process.exit(0));

server.listen(PORT, '0.0.0.0', () => console.log('pocketful stage 1 listening on ' + PORT));
