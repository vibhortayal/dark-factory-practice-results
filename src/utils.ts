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
 * Comprehensive validation including monetary invariants and nested structures
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

  // Validate settlement_operator_ids are all strings
  for (const opId of state.settlement_operator_ids) {
    if (typeof opId !== 'string') return false;
  }

  // Validate users have required fields and valid values
  for (const user of state.users) {
    if (!user || typeof user !== 'object') return false;
    if (typeof user.id !== 'string') return false;
    if (typeof user.email !== 'string') return false;
    if (typeof user.password_hash !== 'string') return false;
    if (typeof user.display_name !== 'string') return false;
    if (typeof user.handle !== 'string') return false;
    if (typeof user.balance !== 'number') return false;
    // §1: No wallet balance may be negative
    if (user.balance < 0) return false;
    if (typeof user.created_at !== 'string') return false;
  }

  // Validate tokens have required fields
  for (const token of state.tokens) {
    if (!token || typeof token !== 'object') return false;
    if (typeof token.user_id !== 'string') return false;
    if (typeof token.token !== 'string') return false;
  }

  // Validate payments have required fields and valid values
  for (const payment of state.payments) {
    if (!payment || typeof payment !== 'object') return false;
    if (typeof payment.id !== 'string') return false;
    if (typeof payment.from_user_id !== 'string') return false;
    if (typeof payment.from_handle !== 'string') return false;
    if (typeof payment.to_user_id !== 'string') return false;
    if (typeof payment.to_handle !== 'string') return false;
    if (typeof payment.amount !== 'number' || payment.amount < 0) return false;
    if (typeof payment.note !== 'string') return false;
    if (payment.visibility !== 'public' && payment.visibility !== 'private') return false;
    if (payment.request_id !== null && typeof payment.request_id !== 'string') return false;
    if (payment.settlement_id !== null && typeof payment.settlement_id !== 'string') return false;
    if (typeof payment.created_at !== 'string') return false;
  }

  // Validate requests have required fields and valid values
  for (const request of state.requests) {
    if (!request || typeof request !== 'object') return false;
    if (typeof request.id !== 'string') return false;
    if (typeof request.requester_id !== 'string') return false;
    if (typeof request.requester_handle !== 'string') return false;
    if (typeof request.payer_id !== 'string') return false;
    if (typeof request.payer_handle !== 'string') return false;
    if (typeof request.amount !== 'number' || request.amount < 0) return false;
    if (typeof request.note !== 'string') return false;
    if (request.status !== 'pending' && request.status !== 'paid' && request.status !== 'declined' && request.status !== 'cancelled') return false;
    if (request.payment_id !== null && typeof request.payment_id !== 'string') return false;
    if (typeof request.created_at !== 'string') return false;
  }

  // Validate splits have required fields and valid values
  for (const split of state.splits) {
    if (!split || typeof split !== 'object') return false;
    if (typeof split.id !== 'string') return false;
    if (typeof split.requester_id !== 'string') return false;
    if (typeof split.amount !== 'number' || split.amount < 0) return false;
    if (typeof split.currency !== 'string') return false;
    if (typeof split.note !== 'string') return false;
    if (!Array.isArray(split.shares)) return false;
    for (const share of split.shares) {
      if (!share || typeof share !== 'object') return false;
      if (typeof share.handle !== 'string') return false;
      if (typeof share.amount !== 'number' || share.amount < 0) return false;
    }
    if (!Array.isArray(split.request_ids)) return false;
    for (const reqId of split.request_ids) {
      if (typeof reqId !== 'string') return false;
    }
    if (typeof split.created_at !== 'string') return false;
  }

  // Validate settlements have required fields and valid values
  for (const settlement of state.settlements) {
    if (!settlement || typeof settlement !== 'object') return false;
    if (typeof settlement.id !== 'string') return false;
    if (typeof settlement.operator_id !== 'string') return false;
    if (!Array.isArray(settlement.payment_ids)) return false;
    for (const payId of settlement.payment_ids) {
      if (typeof payId !== 'string') return false;
    }
    if (typeof settlement.committed_at !== 'string') return false;
  }

  // Validate idempotency records have required fields
  for (const record of state.idempotency_records) {
    if (!record || typeof record !== 'object') return false;
    if (typeof record.key !== 'string') return false;
    if (typeof record.user_id !== 'string') return false;
    if (typeof record.method !== 'string') return false;
    if (typeof record.path !== 'string') return false;
    if (typeof record.body !== 'string') return false;
    if (typeof record.status !== 'number') return false;
    // response is response: unknown, so we don't validate it deeply
  }

  return true;
}
