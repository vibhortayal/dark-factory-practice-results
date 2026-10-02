// Human wording for API outcomes and time.

const REFUSALS = {
  insufficient_funds: 'Not enough available funds. Money on hold cannot be spent.',
  not_found: 'We could not find that person or item.',
  self_payment: 'You cannot send money to yourself.',
  self_request: 'You cannot request money from yourself.',
  request_not_pending: 'This request is no longer pending.',
  authorization_not_open: 'This authorisation is no longer open.',
  authorization_expired: 'This authorisation has expired.',
  capture_exceeds_authorization: 'That is more than is still available to capture.',
  forbidden: 'You are not allowed to do that.',
  email_taken: 'That email is already registered.',
  handle_taken: 'Another account already uses the handle that email would give you.',
  unauthenticated: 'Those details did not match an account.',
  idempotency_key_reuse: 'This was already sent with different details. Change the form and try again.',
};

export function refusalText(err) {
  return REFUSALS[err.code] || err.message || 'The service refused that.';
}

const when = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export function formatWhen(iso) {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? iso : when.format(new Date(ms));
}
