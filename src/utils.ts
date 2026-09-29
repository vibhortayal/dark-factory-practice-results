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
