// Exact instants. A client instant is parsed into an integer count of nanoseconds since the epoch
// (BigInt), never through a float or a millisecond-truncating Date.parse, so comparisons are exact.
// An explicit offset (Z or +-hh:mm) is required; calendar fields are validated.
const RE = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$/;
const NS = 1000000000n;

const isLeap = (y) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const daysIn = (y, m) => [31, isLeap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];

// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm).
function daysFromCivil(y, m, d) {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

// Returns epoch nanoseconds (BigInt), or null when `text` is not an RFC 3339 instant with an offset.
// Fractional digits beyond nanoseconds are truncated.
export function parseInstantNs(text) {
  if (typeof text !== 'string') return null;
  const m = RE.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6]].map(Number);
  if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo) || h > 23 || mi > 59 || s > 59) return null;
  let offset = 0;
  if (m[8] !== 'Z' && m[8] !== 'z') {
    const oh = Number(m[8].slice(1, 3));
    const om = Number(m[8].slice(4, 6));
    if (oh > 23 || om > 59) return null;
    offset = (m[8][0] === '-' ? -1 : 1) * (oh * 3600 + om * 60);
  }
  const seconds = daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s - offset;
  const frac = (m[7] || '').slice(0, 9).padEnd(9, '0');
  return BigInt(seconds) * NS + BigInt(frac);
}

export const msToNs = (ms) => BigInt(Math.round(ms)) * 1000000n;
export const nsToMs = (ns) => Number(ns / 1000000n);

// Query parameter value with percent-decoding only: a raw "+" stays a plus sign (an offset),
// never a space. Returns a Map of first occurrences.
export function rawQuery(search) {
  const out = new Map();
  const qs = search.startsWith('?') ? search.slice(1) : search;
  if (qs === '') return out;
  for (const part of qs.split('&')) {
    if (part === '') continue;
    const eq = part.indexOf('=');
    const name = decode(eq < 0 ? part : part.slice(0, eq));
    const value = eq < 0 ? '' : decode(part.slice(eq + 1));
    if (!out.has(name)) out.set(name, value);
  }
  return out;
}

function decode(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s; // malformed escape: keep it literally (it will fail instant validation)
  }
}
