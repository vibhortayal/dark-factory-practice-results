// RFC 3339 helpers. Timestamps are emitted with an explicit numeric offset.
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

// The real clock, untruncated: millisecond precision with three fractional digits.
export function nowStamp() {
  return stampAt(Date.now());
}

// Returns epoch ms for a valid RFC 3339 timestamp, otherwise null.
export function parseStamp(s) {
  if (typeof s !== 'string') return null;
  const m = RFC3339.exec(s);
  if (!m) return null;
  const [, , mo, da, h, mi, se] = m.map(Number);
  if (mo < 1 || mo > 12 || da < 1 || da > 31 || h > 23 || mi > 59 || se > 60) return null;
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? null : ms;
}


// Millisecond-precision stamp, used for authorizations so a short ttl is judged
// against the exact instant that is returned.
export function stampAt(ms) {
  const d = new Date(ms);
  return { text: d.toISOString().slice(0, 23) + '+00:00', ms };
}

// Exact instant (epoch ms, may carry sub-millisecond digits) of a valid RFC 3339 timestamp, else null.
export function parseInstant(s) {
  const whole = parseStamp(typeof s === 'string' ? s.replace(/\.\d+/, '') : s);
  if (whole === null) return null;
  const frac = /\.(\d+)/.exec(s);
  return whole + (frac ? Number('0.' + frac[1]) * 1000 : 0);
}
