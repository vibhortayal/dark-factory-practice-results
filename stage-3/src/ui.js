'use strict';

/**
 * The browser UI: a static single-page shell plus its scripts and styles, all shipped in the
 * image. Screens are routed on the client; the server only decides whether a GET gets the shell.
 */

const fs = require('fs');
const path = require('path');

const PUBLIC_DIR = path.join(__dirname, '..', 'public');
const UI_ROUTES = new Set(['/', '/requests', '/split', '/signup', '/login', '/authorizations']);
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
};
const SECURITY_HEADERS = {
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Cache-Control': 'no-cache',
};

/** Every file under public/, read once: request paths can only name files in this table. */
function loadAssets(dir = PUBLIC_DIR, prefix = '') {
  const assets = new Map();
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const [k, v] of loadAssets(full, `${prefix}${entry.name}/`)) assets.set(k, v);
    } else if (entry.name !== 'package.json') {
      assets.set(`${prefix}${entry.name}`, fs.readFileSync(full));
    }
  }
  return assets;
}

const assets = loadAssets();
const shell = assets.get('index.html');

const wantsHtml = (headers) => /text\/html/i.test(headers.accept || '');

/** A response {status, headers, body} for UI routes and assets, or null for the JSON API. */
function serve(method, pathname, headers) {
  if (method !== 'GET') return null;
  if (pathname.startsWith('/assets/')) {
    let name;
    try {
      name = decodeURIComponent(pathname.slice('/assets/'.length));
    } catch (_) {
      return null;
    }
    const body = assets.get(name);
    if (!body || name === 'index.html') return null;
    return { status: 200, headers: { ...SECURITY_HEADERS, 'Content-Type': TYPES[path.extname(name)] || 'application/octet-stream' }, body };
  }
  if (UI_ROUTES.has(pathname) && wantsHtml(headers)) {
    return { status: 200, headers: { ...SECURITY_HEADERS, 'Content-Type': TYPES['.html'] }, body: shell };
  }
  return null;
}

module.exports = { serve };
