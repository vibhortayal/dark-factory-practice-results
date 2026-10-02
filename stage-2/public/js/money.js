// Money in minor units: formatting, parsing typed decimals and equal splits.
// Integers only; no floating-point arithmetic touches an amount.

const MAX_SAFE = 2n ** 53n;

/** `100.00 EUR`; with minorUnits 0 there is no decimal point (`1200 JPY`). */
export function formatAmount(minor, minorUnits, currency) {
  const negative = String(minor).startsWith('-');
  const digits = String(minor).replace('-', '');
  const text =
    minorUnits === 0
      ? digits
      : `${digits.padStart(minorUnits + 1, '0').slice(0, -minorUnits)}.${digits.padStart(minorUnits + 1, '0').slice(-minorUnits)}`;
  return `${negative ? '-' : ''}${text} ${currency}`;
}

/** The decimal a person would type for `minor` (`2000` -> `20.00`). */
export function toTypedDecimal(minor, minorUnits) {
  return formatAmount(minor, minorUnits, '').trim();
}

/**
 * Typed decimal -> minor units. Accepts digits with an optional point followed by 1..minorUnits
 * digits (surrounding spaces ignored). Anything else is refused, never rounded.
 */
export function parseDecimal(text, minorUnits) {
  const value = String(text).trim();
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return { ok: false, reason: 'Enter an amount using digits only, for example 15.00.' };
  const [, whole, fraction = ''] = match;
  if (fraction.length > minorUnits) {
    return {
      ok: false,
      reason:
        minorUnits === 0
          ? 'This currency has no decimal places. Enter a whole number.'
          : `Use at most ${minorUnits} decimal places.`,
    };
  }
  const minor = BigInt(whole + fraction.padEnd(minorUnits, '0'));
  if (minor > MAX_SAFE) return { ok: false, reason: 'That amount is too large.' };
  return { ok: true, minor: Number(minor) };
}

/** Equal split: whole units, extra units go to the first participants. */
export function splitShares(amount, count) {
  const base = Math.floor(amount / count);
  const extra = amount - base * count;
  return Array.from({ length: count }, (_, i) => base + (i < extra ? 1 : 0));
}

/** Handles typed as `ada, bob,cy`: split on commas, trim, drop empty entries. */
export function parseHandles(text) {
  return String(text)
    .split(',')
    .map((h) => h.trim())
    .filter((h) => h !== '');
}
