// Exact decimal <-> minor-unit conversion by string arithmetic. No floating point.
const MAX_SAFE = 9007199254740991n;

export function formatPlain(minor, minorUnits) {
  const digits = BigInt(minor).toString();
  if (minorUnits === 0) return digits;
  const padded = digits.padStart(minorUnits + 1, '0');
  return `${padded.slice(0, -minorUnits)}.${padded.slice(-minorUnits)}`;
}

export function formatAmount(minor, minorUnits, currency) {
  return `${formatPlain(minor, minorUnits)} ${currency}`;
}

// -> { ok: true, minor } or { ok: false, error }
export function parseDecimal(text, minorUnits) {
  const value = String(text ?? '').trim();
  if (value === '') return { ok: false, error: 'Enter an amount.' };
  const match = /^(\d*)(?:\.(\d*))?$/.exec(value);
  if (!match || (match[1] === '' && !match[2])) {
    return { ok: false, error: 'Amounts are plain numbers like 15 or 15.50.' };
  }
  const whole = match[1] || '0';
  const fraction = match[2] ?? '';
  if (value.includes('.') && fraction === '') {
    return { ok: false, error: 'Amounts are plain numbers like 15 or 15.50.' };
  }
  if (fraction.length > minorUnits) {
    return {
      ok: false,
      error: minorUnits === 0
        ? 'This currency has no decimal places.'
        : `At most ${minorUnits} decimal places are allowed.`,
    };
  }
  const minor = BigInt(whole) * 10n ** BigInt(minorUnits) + BigInt(fraction.padEnd(minorUnits, '0') || '0');
  if (minor > MAX_SAFE) return { ok: false, error: 'That amount is too large.' };
  return { ok: true, minor: Number(minor) };
}

// Stage-1 §9: base share for everyone, one extra minor unit to the first (amount mod n).
export function equalShares(amount, count) {
  const base = Math.floor(amount / count);
  const extra = amount - base * count;
  return Array.from({ length: count }, (_, i) => base + (i < extra ? 1 : 0));
}
