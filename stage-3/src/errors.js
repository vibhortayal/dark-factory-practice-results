'use strict';

/** An error that maps directly to an HTTP error response. */
class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}

const malformed = (msg) => new ApiError(400, 'malformed_request', msg || 'malformed request');
const invalid = (msg) => new ApiError(422, 'validation_failed', msg || 'validation failed');
const unauthenticated = (msg) => new ApiError(401, 'unauthenticated', msg || 'authentication required');
const forbidden = (msg) => new ApiError(403, 'forbidden', msg || 'not permitted');
const notFound = (msg) => new ApiError(404, 'not_found', msg || 'not found');
const selfPayment = () => new ApiError(422, 'self_payment', 'cannot pay yourself');
const selfRequest = () => new ApiError(422, 'self_request', 'cannot request money from yourself');
const conflict = (code, msg) => new ApiError(409, code, msg);

module.exports = { ApiError, malformed, invalid, unauthenticated, forbidden, notFound, conflict, selfPayment, selfRequest };
