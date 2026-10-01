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
    return JSON.parse(exactNumbers(text));
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

const NUMBER = /-?(?:0|[1-9]\d*)(?:\.(\d+))?(?:[eE]([+-]?\d+))?/y;

// JSON.parse rounds to a double before anyone can look at the literal, so a literal such as
// 1.0000000000000000000001 would pass as the integer 1. Judge number literals on their exact
// decimal value: a literal that is not integral but would round to an integer is rewritten to 0.5
// (any non-integer) before parsing.
function exactNumbers(text) {
  if (!/[0-9][.eE]/.test(text)) return text;
  let out = null;
  let last = 0;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text.charCodeAt(i);
    if (c === 34) {
      i++;
      while (i < n && text.charCodeAt(i) !== 34) i += text.charCodeAt(i) === 92 ? 2 : 1;
      i++;
    } else if (c === 45 || (c >= 48 && c <= 57)) {
      NUMBER.lastIndex = i;
      const m = NUMBER.exec(text);
      if (!m) { i++; continue; }
      const end = i + m[0].length;
      if (m[1] !== undefined || m[2] !== undefined) {
        if (nonIntegralYetRounds(m[0], m[1] || '', m[2])) {
          out = (out || '') + text.slice(last, i) + '0.5';
          last = end;
        }
      }
      i = end;
    } else i++;
  }
  return out === null ? text : out + text.slice(last);
}

function nonIntegralYetRounds(literal, frac, exp) {
  const x = exp === undefined ? 0 : Number(exp);
  if (!Number.isFinite(x) || Math.abs(x) > 100000) return false;
  const mantissa = literal.replace(/^-/, '').split(/[eE]/)[0];
  const digits = mantissa.replace('.', '').replace(/^0+/, '');
  if (digits === '') return false;
  const shift = frac.length - x; // digits after the decimal point in the exact value
  if (shift <= 0) return false;
  const tail = digits.length >= shift ? digits.slice(digits.length - shift) : digits.padStart(shift, '0');
  if (/^0*$/.test(tail)) return false;
  return Number.isInteger(Number(literal));
}
