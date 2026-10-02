// Row Q11: test ids the UI adds must stay outside every id family the specification defines
// per resource, whatever a resource id is. This scans every `testid:` the UI source can emit.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'js');

const FAMILIES = [
  'activity-item-', 'activity-parties-', 'activity-amount-', 'activity-note-',
  'request-item-', 'request-amount-', 'request-pay-', 'request-decline-', 'request-cancel-',
  'split-share-',
  'authorization-item-', 'authorization-amount-', 'authorization-captured-', 'authorization-expires-',
  'authorization-capture-amount-', 'authorization-capture-', 'authorization-void-',
];
// Ids the specification itself defines (fixed ones and the per-resource templates).
const FIXED = new Set([
  'signup-email', 'signup-password', 'signup-display-name', 'signup-submit', 'login-email', 'login-password', 'login-submit',
  'auth-error', 'current-user', 'current-handle', 'logout-button', 'wallet-balance', 'wallet-available', 'wallet-held',
  'wallet-refresh', 'pay-handle', 'pay-amount', 'pay-note', 'pay-visibility', 'pay-submit', 'pay-error', 'pay-uncertain',
  'request-handle', 'request-amount', 'request-note', 'request-submit', 'request-error', 'activity-list', 'empty-activity',
  'incoming-list', 'outgoing-list', 'empty-requests', 'split-amount', 'split-handles', 'split-note', 'split-submit',
  'split-preview', 'split-error', 'authorize-handle', 'authorize-amount', 'authorize-note', 'authorize-visibility',
  'authorize-submit', 'authorize-error', 'authorization-list', 'authorization-error', 'empty-authorizations',
]);
const TEMPLATES = new Set(FAMILIES.map((f) => `${f}\${...}`));

function sources(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sources(path.join(dir, e.name)) : e.name.endsWith('.js') ? [path.join(dir, e.name)] : []);
}

function emitted() {
  const found = new Set();
  for (const file of sources(root)) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(/testid:\s*(`[^`]*`|'[^']*')/g)) found.add(m[1].slice(1, -1).replace(/\$\{[^}]*\}/g, '${...}'));
    for (const m of text.matchAll(/(?:testids|ids):\s*\{([^}]*)\}/g)) {
      for (const v of m[1].matchAll(/:\s*'([^']*)'/g)) found.add(v[1]);
    }
  }
  return found;
}

test('every id the UI emits is a specified one or lies outside all specified families', () => {
  const ids = emitted();
  assert.ok(ids.size > 40, `found only ${ids.size} ids`);
  for (const id of ids) {
    if (FIXED.has(id) || TEMPLATES.has(id)) continue;
    for (const family of FAMILIES) {
      assert.ok(!id.startsWith(family) && !family.startsWith(id.replace('${...}', '')),
        `added test id "${id}" falls inside the specified family "${family}*"`);
    }
  }
});

test('the specified families are all emitted (guards the scan itself)', () => {
  const ids = emitted();
  for (const template of TEMPLATES) {
    assert.ok(ids.has(template), `${template} is not emitted by any screen`);
  }
});
