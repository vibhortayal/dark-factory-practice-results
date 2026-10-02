'use strict';

const { malformed } = require('./errors');

const MAX_DEPTH = 200;
const decoder = new TextDecoder('utf-8', { fatal: true });

/** Nesting depth of JSON text, scanned without recursion. */
function depthOf(text) {
  let depth = 0;
  let max = 0;
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (inString) {
      if (c === 92) i++; // backslash
      else if (c === 34) inString = false;
    } else if (c === 34) inString = true;
    else if (c === 91 || c === 123) {
      depth++;
      if (depth > max) max = depth;
    } else if (c === 93 || c === 125) depth--;
  }
  return max;
}

/** Parse a request body; throws 400 malformed_request when it is not valid UTF-8 JSON. */
function parseJson(buffer) {
  let text;
  try {
    text = decoder.decode(buffer);
  } catch (_) {
    throw malformed('body is not valid UTF-8');
  }
  if (text.trim() === '') throw malformed('empty body');
  if (depthOf(text) > MAX_DEPTH) throw malformed('body nested too deeply');
  try {
    return JSON.parse(text);
  } catch (_) {
    throw malformed('body is not valid JSON');
  }
}

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

/** JSON value equality: key order is irrelevant, numbers compare by value. */
function jsonEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== 'object') return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    return a.length === b.length && a.every((v, i) => jsonEqual(v, b[i]));
  }
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && jsonEqual(a[k], b[k]));
}

module.exports = { parseJson, isObject, jsonEqual };
