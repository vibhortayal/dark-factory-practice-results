// RFC 3339 helpers. Timestamps are emitted with an explicit numeric offset.
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export function nowStamp() {
  const d = new Date();
  return { text: d.toISOString().slice(0, 19) + '+00:00', ms: Math.floor(d.getTime() / 1000) * 1000 };
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
