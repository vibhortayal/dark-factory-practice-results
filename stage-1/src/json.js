import { malformed } from './errors.js';

const MAX_DEPTH = 64;
const decoder = new TextDecoder('utf-8', { fatal: true });

// Cheap pre-scan so hostile nesting never reaches recursive code.
function depthOk(text) {
  let depth = 0;
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (inString) {
      if (c === 92) i++;
      else if (c === 34) inString = false;
    } else if (c === 34) inString = true;
    else if (c === 91 || c === 123) {
      if (++depth > MAX_DEPTH) return false;
    } else if (c === 93 || c === 125) depth--;
  }
  return true;
}

// Parses a request body buffer. Throws 400 malformed_request on invalid UTF-8,
// invalid JSON or absurd nesting.
export function parseJson(buf) {
  let text;
  try {
    text = decoder.decode(buf);
  } catch {
    throw malformed('body is not valid UTF-8');
  }
  if (!depthOk(text)) throw malformed('body is nested too deeply');
  try {
    return JSON.parse(text);
  } catch {
    throw malformed('body is not valid JSON');
  }
}

export const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// Canonical text of a parsed JSON value: key order and number spelling do not matter.
export function canon(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  const keys = Object.keys(v).sort();
  return '{' + keys.map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
}

export const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
