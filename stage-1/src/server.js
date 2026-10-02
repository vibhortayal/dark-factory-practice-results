'use strict';

const http = require('http');
const { ApiError } = require('./errors');
const { handle } = require('./pipeline');

const MAX_BODY = 2 * 1024 * 1024;
const MAX_TEST_BODY = 128 * 1024 * 1024;
const JSON_TYPE = 'application/json; charset=utf-8';

function send(res, status, body) {
  if (body === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  const payload = Buffer.from(JSON.stringify(body), 'utf8');
  res.writeHead(status, { 'Content-Type': JSON_TYPE, 'Content-Length': payload.length });
  res.end(payload);
}

function sendError(res, err) {
  if (err instanceof ApiError) {
    send(res, err.status, { error: { code: err.code, message: err.message } });
  } else {
    console.error(err);
    send(res, 500, { error: { code: 'internal_error', message: 'unexpected error' } });
  }
}

/** Collects the body; resolves null once it exceeds the limit (the rest is discarded). */
function collect(req, limit) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    let over = false;
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) over = true;
      else chunks.push(c);
    });
    req.on('end', () => resolve(over ? null : Buffer.concat(chunks)));
    req.on('error', () => resolve(null));
  });
}

async function onRequest(req, res) {
  try {
    let url;
    try {
      url = new URL(req.url, 'http://localhost');
    } catch (_) {
      throw new ApiError(404, 'not_found', 'no such route');
    }
    const large = url.pathname === '/_test/reset' || url.pathname === '/_test/import';
    const buffer = await collect(req, large ? MAX_TEST_BODY : MAX_BODY);
    if (buffer === null) throw new ApiError(400, 'malformed_request', 'request body too large');
    const result = await handle({
      method: req.method, pathname: url.pathname, query: url.searchParams, headers: req.headers, buffer,
    });
    send(res, result.status, result.body);
  } catch (err) {
    sendError(res, err);
  }
}

function createServer() {
  const server = http.createServer(onRequest);
  server.keepAliveTimeout = 65000;
  server.headersTimeout = 66000;
  return server;
}

if (require.main === module) {
  const port = Number(process.env.PORT) || 8080;
  createServer().listen(port, '0.0.0.0', () => console.log(`pocketful listening on ${port}`));
}

module.exports = { createServer };
