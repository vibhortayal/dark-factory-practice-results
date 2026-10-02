// Retry identity for an idempotent write: the key belongs to the content of the form, not to
// the click. Submitting unchanged content again re-sends the same key (a replay); changing
// any field starts a new payment with a new key.

function randomKey() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export class RetryIdentity {
  constructor(makeKey = randomKey) {
    this.makeKey = makeKey;
    this.fingerprint = null;
    this.key = null;
  }

  keyFor(fingerprint) {
    if (fingerprint !== this.fingerprint) {
      this.fingerprint = fingerprint;
      this.key = this.makeKey();
    }
    return this.key;
  }
}
