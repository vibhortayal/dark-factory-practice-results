/**
 * Format ISO timestamp with explicit offset (RFC 3339)
 * Examples: 2026-09-24T19:00:00+00:00, 2026-09-24T21:00:00+02:00
 */
export function formatTimestamp(date: Date = new Date()): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  const seconds = String(date.getUTCSeconds()).padStart(2, '0');

  // For now, always use +00:00 (UTC)
  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}+00:00`;
}

/**
 * Normalize JSON string for comparison
 * Per §7: "Same body" means the same JSON value after parsing — key order and whitespace do not matter.
 * This function produces a canonical form with sorted keys for reliable comparison.
 */
export function normalizeJsonBody(jsonString: string): string {
  try {
    const parsed = JSON.parse(jsonString);
    return canonicalJson(parsed);
  } catch {
    // If parse fails, return original (error will be caught elsewhere)
    return jsonString;
  }
}

/**
 * Convert a value to canonical JSON form (sorted keys, no extra whitespace)
 */
function canonicalJson(value: any): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return JSON.stringify(value);
  if (typeof value === 'string') return JSON.stringify(value);
  
  if (Array.isArray(value)) {
    const elements = value.map(v => canonicalJson(v));
    return '[' + elements.join(',') + ']';
  }
  
  if (typeof value === 'object') {
    // Sort keys alphabetically for canonical form
    const keys = Object.keys(value).sort();
    const pairs = keys.map(k => JSON.stringify(k) + ':' + canonicalJson(value[k]));
    return '{' + pairs.join(',') + '}';
  }
  
  return JSON.stringify(value);
}
