import { Response } from 'express';
import { ErrorResponse } from './types';

export class AppError extends Error {
  constructor(
    public status: number,
    public code: string,
    public message: string
  ) {
    super(message);
  }
}

export const sendError = (res: Response, status: number, code: string, message: string) => {
  const response: ErrorResponse = {
    error: {
      code,
      message
    }
  };
  res.status(status).json(response);
};

export const handleError = (res: Response, error: any) => {
  if (error instanceof AppError) {
    sendError(res, error.status, error.code, error.message);
  } else if (error.message === 'validation_failed') {
    sendError(res, 422, 'validation_failed', 'Validation failed');
  } else {
    sendError(res, 500, 'internal_error', 'Internal server error');
  }
};

// Common errors
export const errors = {
  malformedRequest: (msg?: string) => new AppError(400, 'malformed_request', msg || 'Malformed request'),
  missingIdempotencyKey: () => new AppError(400, 'missing_idempotency_key', 'Idempotency-Key header is required'),
  unauthenticated: () => new AppError(401, 'unauthenticated', 'Unauthenticated'),
  forbidden: () => new AppError(403, 'forbidden', 'Forbidden'),
  notFound: () => new AppError(404, 'not_found', 'Not found'),
  idempotencyKeyReuse: () => new AppError(409, 'idempotency_key_reuse', 'Idempotency key reuse with different body'),
  validationFailed: (msg?: string) => new AppError(422, 'validation_failed', msg || 'Validation failed'),
  insufficientFunds: () => new AppError(409, 'insufficient_funds', 'Insufficient funds'),
  selfPayment: () => new AppError(422, 'self_payment', 'Cannot send payment to yourself'),
  selfRequest: () => new AppError(422, 'self_request', 'Cannot request payment from yourself'),
  emailTaken: () => new AppError(409, 'email_taken', 'Email already registered'),
  handleTaken: () => new AppError(409, 'handle_taken', 'Handle already taken'),
  requestNotPending: () => new AppError(409, 'request_not_pending', 'Request is not pending')
};
