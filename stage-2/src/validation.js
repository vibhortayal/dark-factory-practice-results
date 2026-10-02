'use strict';

/** The one place that knows the field rules shared by every endpoint. */

const { malformed, invalid } = require('./errors');

const MAX_AMOUNT = 1000000000;
const MAX_NOTE = 200;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const codePoints = (s) => Array.from(s).length;

/** 400 when a present field has the wrong JSON type. `types` maps key -> 'string' | 'array'. */
function assertTypes(body, types) {
  for (const [key, type] of Object.entries(types)) {
    const v = body[key];
    if (v === undefined) continue;
    const ok = type === 'string' ? typeof v === 'string' : Array.isArray(v);
    if (!ok) throw malformed(`${key} must be a ${type}`);
  }
}

function requireField(body, key) {
  if (body[key] === undefined) throw invalid(`${key} is required`);
  return body[key];
}

/** Integral JSON number in 1..1000000000; `min` lets seeded/split values be 0. */
function checkAmount(v, min = 1) {
  if (typeof v !== 'number' || !Number.isFinite(v) || !Number.isInteger(v) || v < min || v > MAX_AMOUNT) {
    throw invalid(`amount must be an integer between ${min} and ${MAX_AMOUNT}`);
  }
  return v;
}

function checkNote(v) {
  if (v === undefined) return '';
  if (typeof v !== 'string' || codePoints(v) > MAX_NOTE) {
    throw invalid(`note must be a string of at most ${MAX_NOTE} characters`);
  }
  return v;
}

function checkVisibility(v) {
  if (v === undefined) return 'public';
  if (v !== 'public' && v !== 'private') throw invalid('visibility must be "public" or "private"');
  return v;
}

/** amount + note + visibility as used by payments and settlement entries. */
function paymentFields(body) {
  const amount = checkAmount(requireField(body, 'amount'));
  return { amount, note: checkNote(body.note), visibility: checkVisibility(body.visibility) };
}

const DIGITS = /^[0-9]+$/;

/** Integer query parameter: plain decimal digits within [min, max]. */
function queryInt(params, name, dflt, min, max) {
  if (!params.has(name)) return dflt;
  const raw = params.get(name);
  if (!DIGITS.test(raw)) throw invalid(`${name} must be plain decimal digits`);
  const n = Number(raw);
  if (n < min || n > max) throw invalid(`${name} out of range`);
  return n;
}

function pagination(params) {
  return {
    limit: queryInt(params, 'limit', 50, 1, 200),
    offset: queryInt(params, 'offset', 0, 0, Infinity),
  };
}

function page(items, { limit, offset }) {
  return { items: items.slice(offset, offset + limit), hasMore: items.length > offset + limit };
}

module.exports = {
  MAX_AMOUNT, HANDLE_RE, assertTypes, requireField, checkAmount, checkNote, checkVisibility,
  paymentFields, queryInt, pagination, page, codePoints,
};
