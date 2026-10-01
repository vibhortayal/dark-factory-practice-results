import { malformed, invalid } from './errors.js';
import { has } from './json.js';

export const MAX_AMOUNT = 1000000000;
export const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
export const cpLength = (s) => { let n = 0; for (const _ of s) n++; return n; };

// Amount: numeric type with an integral value, 1..1e9. Everything else is 422.
export function checkAmount(body, { min = 1 } = {}) {
  if (!has(body, 'amount')) throw invalid('amount is required');
  const a = body.amount;
  if (typeof a !== 'number' || !Number.isInteger(a)) throw invalid('amount must be an integer');
  if (a < min || a > MAX_AMOUNT) throw invalid(`amount must be between ${min} and ${MAX_AMOUNT}`);
  return a === 0 ? 0 : a;
}

export function checkNote(body) {
  if (!has(body, 'note')) return '';
  const n = body.note;
  if (typeof n !== 'string') throw invalid('note must be a string');
  if (cpLength(n) > 200) throw invalid('note must be at most 200 characters');
  return n;
}

export function checkVisibility(body) {
  if (!has(body, 'visibility')) return 'public';
  const v = body.visibility;
  if (v !== 'public' && v !== 'private') throw invalid('visibility must be public or private');
  return v;
}

// A handle field: wrong JSON type is 400, missing is 422.
export function checkHandleType(body, field) {
  if (has(body, field) && typeof body[field] !== 'string') throw malformed(`${field} must be a string`);
}
export function requireHandle(body, field) {
  if (!has(body, field)) throw invalid(`${field} is required`);
  return body[field];
}

// Plain decimal digits only.
function digits(query, name, def, min, max) {
  const raw = query.get(name);
  if (raw === null) return def;
  if (!/^[0-9]+$/.test(raw)) throw invalid(`${name} must be plain decimal digits`);
  const n = Number(raw);
  if (n < min || n > max) throw invalid(`${name} out of range`);
  return n;
}

export function paging(query) {
  return {
    limit: digits(query, 'limit', 50, 1, 200),
    offset: digits(query, 'offset', 0, 0, Number.MAX_SAFE_INTEGER),
  };
}

export function oneOf(query, name, allowed) {
  const v = query.get(name);
  if (v === null) return null;
  if (!allowed.includes(v)) throw invalid(`${name} must be one of ${allowed.join(', ')}`);
  return v;
}

// Takes items newest-first via predicate over an ascending list.
export function page(list, pred, { limit, offset }) {
  const out = [];
  let seen = 0;
  let more = false;
  for (let i = list.length - 1; i >= 0; i--) {
    const it = list[i];
    if (!pred(it)) continue;
    if (seen++ < offset) continue;
    if (out.length === limit) { more = true; break; }
    out.push(it);
  }
  return { items: out, has_more: more };
}
