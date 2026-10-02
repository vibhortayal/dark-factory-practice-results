'use strict';

/**
 * Instants: the one parser and the one comparison for every RFC 3339 time the service reads.
 *
 * An instant is {ms, rest}: whole epoch milliseconds plus the digits of any finer fraction
 * (trailing zeros dropped), so a client's microsecond or nanosecond instant is compared exactly
 * and never rounded to the service's millisecond clock. Different spellings of one instant
 * (offsets, `Z`, trailing zeros) are equal. The original text is kept by the callers that echo it.
 */

const SHAPE = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$/;

/** Parse an RFC 3339 date-time with an explicit offset; null when it is not one. */
function parse(text) {
  if (typeof text !== 'string') return null;
  const m = SHAPE.exec(text);
  if (!m) return null;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  if (month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return null;
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  let offsetMinutes = 0;
  const zone = m[8];
  if (zone !== 'Z' && zone !== 'z') {
    const oh = Number(zone.slice(1, 3));
    const om = Number(zone.slice(4, 6));
    if (oh > 23 || om > 59) return null;
    offsetMinutes = (zone[0] === '-' ? -1 : 1) * (oh * 60 + om);
  }
  const fraction = m[7] || '';
  const ms = date.getTime() + Number(fraction.slice(0, 3).padEnd(3, '0')) - offsetMinutes * 60000;
  return { ms, rest: fraction.slice(3).replace(/0+$/, '') };
}

/** Exact comparison: negative, zero or positive. */
function compare(a, b) {
  if (a.ms !== b.ms) return a.ms < b.ms ? -1 : 1;
  if (a.rest === b.rest) return 0;
  const width = Math.max(a.rest.length, b.rest.length);
  const x = a.rest.padEnd(width, '0');
  const y = b.rest.padEnd(width, '0');
  return x < y ? -1 : 1;
}

const fromMs = (ms) => ({ ms, rest: '' });
const MIN = { ms: -Infinity, rest: '' };

/** Millisecond-precision RFC 3339 text with a +00:00 offset. */
const format = (ms) => new Date(ms).toISOString().replace('Z', '+00:00');

/** Memoised parse for stored strings (the cache is keyed by the text itself). */
const cache = new Map();
function parseCached(text) {
  let v = cache.get(text);
  if (v === undefined) {
    v = parse(text);
    if (cache.size > 200000) cache.clear();
    cache.set(text, v);
  }
  return v;
}

/**
 * A raw query-string parameter, percent-decoded but with `+` left as `+` (so an instant written
 * with a raw `+` offset reads as that offset). Undefined when absent.
 */
function rawParam(search, name) {
  for (const part of String(search || '').replace(/^\?/, '').split('&')) {
    if (part === '') continue;
    const i = part.indexOf('=');
    const key = i < 0 ? part : part.slice(0, i);
    let decodedKey;
    try {
      decodedKey = decodeURIComponent(key.replace(/\+/g, ' '));
    } catch (_) {
      continue;
    }
    if (decodedKey !== name) continue;
    if (i < 0) return '';
    try {
      return decodeURIComponent(part.slice(i + 1));
    } catch (_) {
      return part.slice(i + 1); // undecodable: let the parser reject it
    }
  }
  return undefined;
}

module.exports = { parse, parseCached, compare, fromMs, format, rawParam, MIN };
