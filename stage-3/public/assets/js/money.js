// Money parsing and formatting. All arithmetic is on strings and BigInt, never on floats.

const DECIMAL = /^(\d+)(?:\.(\d+))?$/;

// Parses what a person types ("15", "15.5", "15.00") into integer minor units.
// Whitespace around the value is trimmed. Rejected: empty, signs, exponents, thousands
// separators, ".5", "5.", more decimals than the currency has (never rounded).
// Zero is passed through; the server decides whether it is acceptable.
export function parseAmount(text, minorUnits) {
  const s = String(text ?? '').trim();
  if (s === '') return { ok: false, error: 'Enter an amount.' };
  const m = DECIMAL.exec(s);
  if (!m) return { ok: false, error: 'Enter the amount as a plain number, for example 15.00.' };
  const frac = m[2] || '';
  if (frac.length > minorUnits) {
    return {
      ok: false,
      error: minorUnits === 0
        ? 'This currency has no decimal places.'
        : `Use at most ${minorUnits} decimal places.`,
    };
  }
  const minor = BigInt(m[1] + frac.padEnd(minorUnits, '0'));
  if (minor > BigInt(Number.MAX_SAFE_INTEGER)) return { ok: false, error: 'That amount is too large.' };
  return { ok: true, minor: Number(minor) };
}

// 1500 with 2 units -> "15.00"; 5 with 2 units -> "0.05"; 1200 with 0 units -> "1200".
export function formatPlain(minor, minorUnits) {
  const digits = BigInt(minor).toString();
  if (minorUnits === 0) return digits;
  const padded = digits.padStart(minorUnits + 1, '0');
  return `${padded.slice(0, -minorUnits)}.${padded.slice(-minorUnits)}`;
}

// "100.00 EUR": exactly minor_units decimals, one space, the currency code.
export function formatAmount(minor, minorUnits, currency) {
  return `${formatPlain(minor, minorUnits)} ${currency}`;
}
