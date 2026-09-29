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

/**
 * Validate ServiceState structure per §10
 * Ensures the imported state has required fields and valid types
 */
export function validateServiceState(state: any): boolean {
  if (!state || typeof state !== 'object') {
    return false;
  }

  // Required top-level fields
  if (typeof state.currency !== 'string') return false;
  if (typeof state.minor_units !== 'number') return false;
  if (!Array.isArray(state.users)) return false;
  if (!Array.isArray(state.tokens)) return false;
  if (!Array.isArray(state.payments)) return false;
  if (!Array.isArray(state.requests)) return false;
  if (!Array.isArray(state.splits)) return false;
  if (!Array.isArray(state.settlements)) return false;
  if (!Array.isArray(state.settlement_operator_ids)) return false;
  if (!Array.isArray(state.idempotency_records)) return false;

  // Validate users have required fields
  for (const user of state.users) {
    if (!user || typeof user !== 'object') return false;
    if (typeof user.id !== 'string') return false;
    if (typeof user.email !== 'string') return false;
    if (typeof user.password_hash !== 'string') return false;
    if (typeof user.display_name !== 'string') return false;
    if (typeof user.handle !== 'string') return false;
    if (typeof user.balance !== 'number') return false;
    if (typeof user.created_at !== 'string') return false;
  }

  // Validate tokens have required fields
  for (const token of state.tokens) {
    if (!token || typeof token !== 'object') return false;
    if (typeof token.user_id !== 'string') return false;
    if (typeof token.token !== 'string') return false;
  }

  // Validate payments have required fields
  for (const payment of state.payments) {
    if (!payment || typeof payment !== 'object') return false;
    if (typeof payment.id !== 'string') return false;
    if (typeof payment.from_user_id !== 'string') return false;
    if (typeof payment.to_user_id !== 'string') return false;
    if (typeof payment.amount !== 'number') return false;
    if (typeof payment.note !== 'string') return false;
    if (payment.visibility !== 'public' && payment.visibility !== 'private') return false;
    if (typeof payment.created_at !== 'string') return false;
  }

  return true;
}
