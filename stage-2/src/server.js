'use strict';

const http = require('http');
const { ApiError } = require('./errors');
const { handle } = require('./pipeline');
const { serve } = require('./ui');

// Generous caps: an over-long value must reach validation and get its 422, not a transport error.
const MAX_BODY = 8 * 1024 * 1024;
const MAX_TEST_BODY = 128 * 1024 * 1024;
const MAX_HEADER = 1024 * 1024;
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

/**
 * Collects the body; resolves null as soon as it exceeds the limit, without buffering the rest
 * (a declared Content-Length over the limit is not read at all). The pipeline answers 422.
 */
function collect(req, limit) {
  return new Promise((resolve) => {
    if (Number(req.headers['content-length']) > limit) {
      req.resume();
      resolve(null);
      return;
    }
    const chunks = [];
    let size = 0;
    const onData = (c) => {
      size += c.length;
      if (size > limit) {
        req.off('data', onData);
        req.resume();
        resolve(null);
      } else chunks.push(c);
    };
    req.on('data', onData);
    req.on('end', () => resolve(Buffer.concat(chunks)));
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
    const page = serve(req.method, url.pathname, req.headers);
    if (page) {
      req.resume();
      res.writeHead(page.status, { ...page.headers, 'Content-Length': page.body.length });
      res.end(page.body);
      return;
    }
    const large = url.pathname === '/_test/reset' || url.pathname === '/_test/import';
    const buffer = await collect(req, large ? MAX_TEST_BODY : MAX_BODY);
    const result = await handle({
      method: req.method, pathname: url.pathname, query: url.searchParams, headers: req.headers, buffer,
    });
    send(res, result.status, result.body);
  } catch (err) {
    sendError(res, err);
  }
}

function createServer() {
  const server = http.createServer({ maxHeaderSize: MAX_HEADER }, onRequest);
  server.on('clientError', (err, socket) => {
    if (!socket.writable) return;
    const tooBig = err.code === 'HPE_HEADER_OVERFLOW';
    const [status, text, code] = tooBig
      ? [422, 'Unprocessable Entity', 'validation_failed']
      : [400, 'Bad Request', 'malformed_request'];
    const body = JSON.stringify({ error: { code, message: tooBig ? 'request head too large' : 'malformed HTTP request' } });
    socket.end(`HTTP/1.1 ${status} ${text}\r\nContent-Type: ${JSON_TYPE}\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`);
  });
  server.keepAliveTimeout = 65000;
  server.headersTimeout = 66000;
  return server;
}

if (require.main === module) {
  const port = Number(process.env.PORT) || 8080;
  createServer().listen(port, '0.0.0.0', () => console.log(`pocketful listening on ${port}`));
}

module.exports = { createServer };
