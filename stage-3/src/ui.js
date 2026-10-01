// Static UI: one HTML shell for every screen plus plain ES modules and one stylesheet,
// all read from public/ at start-up and served from memory (no CDN, no external URL).
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
};

const files = new Map();
(function load(dir, prefix) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) load(full, `${prefix}${name}/`);
    else files.set(`${prefix}${name}`, { body: readFileSync(full), type: TYPES[path.extname(name)] || 'application/octet-stream' });
  }
})(root, '/');

const HEADERS = {
  'Cache-Control': 'no-cache',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'",
  'X-Content-Type-Options': 'nosniff',
};

function reply(res, file) {
  if (res.headersSent) return true;
  res.writeHead(200, { 'Content-Type': file.type, 'Content-Length': file.body.length, ...HEADERS });
  res.end(file.body);
  return true;
}

export const sendShell = (res) => reply(res, files.get('/index.html'));

// Serves /assets/... when the file exists; returns false otherwise.
export function sendAsset(res, urlPath) {
  const file = urlPath.startsWith('/assets/') ? files.get(urlPath) : undefined;
  return file ? reply(res, file) : false;
}

export const UI_PAGES = new Set(['/', '/split', '/signup', '/login']);
export const SHARED_PAGES = new Set(['/requests', '/authorizations']);
export const wantsHtml = (req) => /text\/html/i.test(req.headers.accept || '');
