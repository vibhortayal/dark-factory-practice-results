// Error envelope helpers (spec section 5).
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export const malformed = (m = 'malformed request') => new ApiError(400, 'malformed_request', m);
export const missingKey = () => new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key header is required');
export const unauthenticated = (m = 'missing, malformed or unknown bearer token') => new ApiError(401, 'unauthenticated', m);
export const forbidden = (m = 'not permitted') => new ApiError(403, 'forbidden', m);
export const notFound = (m = 'not found') => new ApiError(404, 'not_found', m);
export const invalid = (m = 'validation failed') => new ApiError(422, 'validation_failed', m);
export const conflict = (code, m) => new ApiError(409, code, m);
