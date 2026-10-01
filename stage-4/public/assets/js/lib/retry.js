// Retry identity. The idempotency key belongs to the content of a form, not to a click:
// a new key is minted only when the content differs from what the current key was minted
// for, and the same key is reused for every submission of unchanged content (after success,
// after a retryable refusal, after a lost response).
export function newKey() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export class RetryIdentity {
  fingerprint = null;
  key = null;
  busy = false; // true while a submission is in flight; a second click is ignored

  keyFor(fingerprint) {
    if (fingerprint !== this.fingerprint) {
      this.fingerprint = fingerprint;
      this.key = newKey();
    }
    return this.key;
  }
}
