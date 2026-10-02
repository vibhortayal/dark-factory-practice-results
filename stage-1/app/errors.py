"""API error types. Every one renders as {"error": {"code", "message"}}."""


class ApiError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message="", code=None, status=None):
        super().__init__(message)
        self.message = message or self.code
        if code:
            self.code = code
        if status:
            self.status = status


def malformed(message="malformed request"):
    return ApiError(message, "malformed_request", 400)


def unauthenticated(message="missing or invalid bearer token"):
    return ApiError(message, "unauthenticated", 401)


def not_found(message="not found"):
    return ApiError(message, "not_found", 404)


def invalid(message="validation failed", code="validation_failed"):
    return ApiError(message, code, 422)


def conflict(code, message=""):
    return ApiError(message or code, code, 409)
