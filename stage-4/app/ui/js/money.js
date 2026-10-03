// Decimal <-> minor units without floating point.

const MAX_MINOR = 1_000_000_000;

export function formatMinor(minor, minorUnits, currency) {
  const digits = String(Math.abs(Number(minor)));
  if (minorUnits === 0) return `${digits} ${currency}`;
  const padded = digits.padStart(minorUnits + 1, '0');
  return `${padded.slice(0, -minorUnits)}.${padded.slice(-minorUnits)} ${currency}`;
}

// Returns {ok: true, minor} or {ok: false, message}. Never rounds.
export function parseAmount(text, minorUnits) {
  const raw = String(text ?? '').trim();
  if (!raw) return { ok: false, message: 'Enter an amount.' };
  const match = /^(\d*)(?:\.(\d*))?$/.exec(raw);
  if (!match || (match[1] === '' && !match[2])) {
    return { ok: false, message: 'Amounts use digits and one decimal point, for example 15.00.' };
  }
  const whole = match[1] || '0';
  const fraction = match[2];
  if (raw.includes('.') && !fraction) {
    return { ok: false, message: 'Add digits after the decimal point, or remove it.' };
  }
  if (fraction && fraction.length > minorUnits) {
    return {
      ok: false,
      message: minorUnits === 0
        ? 'This currency has no decimal places.'
        : `This currency allows at most ${minorUnits} decimal place${minorUnits === 1 ? '' : 's'}.`,
    };
  }
  const minorText = (whole + (fraction || '').padEnd(minorUnits, '0')).replace(/^0+(?=\d)/, '');
  if (minorText.length > 12) return { ok: false, message: 'That amount is too large.' };
  const minor = Number(minorText);
  if (minor < 1) return { ok: false, message: 'The amount must be greater than zero.' };
  if (minor > MAX_MINOR) return { ok: false, message: 'That amount is above the allowed maximum.' };
  return { ok: true, minor };
}

// The stage-1 rule: whole units, extra units go to the first shares.
export function equalSplit(amount, count) {
  const base = Math.floor(amount / count);
  const extra = amount - base * count;
  return Array.from({ length: count }, (_, i) => base + (i < extra ? 1 : 0));
}

export function minorToInput(minor, minorUnits) {
  const text = formatMinor(minor, minorUnits, '');
  return text.trim();
}
