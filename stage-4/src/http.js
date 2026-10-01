// HTTP plumbing: body reading, response writing, error envelope.
import { ApiError } from './errors.js';

const MAX_BODY = 8 * 1024 * 1024;
const JSON_TYPE = 'application/json; charset=utf-8';

export function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let over = false;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) over = true;
      else chunks.push(c);
    });
    req.on('end', () => (over ? reject(new ApiError(400, 'malformed_request', 'body is too large')) : resolve(Buffer.concat(chunks))));
    req.on('error', reject);
  });
}

export function send(res, status, bodyText) {
  if (res.headersSent || res.writableEnded) return;
  if (bodyText === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  const buf = Buffer.from(bodyText, 'utf8');
  res.writeHead(status, { 'Content-Type': JSON_TYPE, 'Content-Length': buf.length });
  res.end(buf);
}

export const sendJson = (res, status, value) => send(res, status, JSON.stringify(value));

export function sendError(res, status, code, message) {
  sendJson(res, status, { error: { code, message } });
}
