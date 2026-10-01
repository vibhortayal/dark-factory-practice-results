'use strict';

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const err = {
  malformed: (m) => new ApiError(400, 'malformed_request', m || 'malformed request'),
  missingKey: () => new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key header is required'),
  unauthenticated: (m) => new ApiError(401, 'unauthenticated', m || 'missing or invalid bearer token'),
  forbidden: (m) => new ApiError(403, 'forbidden', m || 'not permitted'),
  notFound: (m) => new ApiError(404, 'not_found', m || 'not found'),
  conflict: (code, m) => new ApiError(409, code, m || code),
  validation: (m) => new ApiError(422, 'validation_failed', m || 'validation failed'),
  unprocessable: (code, m) => new ApiError(422, code, m || code),
};

const MAX_AMOUNT = 1000000000;
const MAX_NOTE = 200;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;

function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

// Stable string form of a parsed JSON value: key order is irrelevant.
function canonical(v) {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (isObject(v)) {
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  }
  return JSON.stringify(v);
}

// RFC 3339, whole seconds, always UTC with an explicit offset.
function iso(ms) {
  return new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', '+00:00');
}

function charLength(s) {
  let n = 0;
  for (const _ of s) n++; // code points
  return n;
}

function parseAmount(v) {
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 1 || v > MAX_AMOUNT) {
    throw err.validation('amount must be an integer between 1 and ' + MAX_AMOUNT);
  }
  return v;
}

function parseNote(v) {
  if (v === undefined) return '';
  if (typeof v !== 'string') throw err.validation('note must be a string');
  if (charLength(v) > MAX_NOTE) throw err.validation('note is longer than ' + MAX_NOTE + ' characters');
  return v;
}

function parseVisibility(v) {
  if (v === undefined) return 'public';
  if (v !== 'public' && v !== 'private') throw err.validation('visibility must be public or private');
  return v;
}

// Required string field: missing is 422, a non-string is 400, empty is 422.
function requiredString(body, field) {
  const v = body[field];
  if (v === undefined) throw err.validation(field + ' is required');
  if (typeof v !== 'string') throw err.malformed(field + ' must be a string');
  if (v === '') throw err.validation(field + ' must not be empty');
  return v;
}

function parseQueryInt(q, name, def, min, max) {
  const v = q.get(name);
  if (v === null) return def;
  if (!/^[0-9]+$/.test(v)) throw err.validation(name + ' must be plain decimal digits');
  const n = Number(v);
  if (n < min || n > max) throw err.validation(name + ' out of range');
  return n;
}

module.exports = {
  ApiError, err, isObject, canonical, iso, charLength,
  parseAmount, parseNote, parseVisibility, requiredString, parseQueryInt,
  MAX_AMOUNT, MAX_NOTE, HANDLE_RE,
};
