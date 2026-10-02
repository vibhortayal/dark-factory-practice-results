"""The one exception type every handler raises for an expected failure."""


class ApiError(Exception):
    def __init__(self, status, code, message=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")


def malformed(message="malformed request"):
    return ApiError(400, "malformed_request", message)


def invalid(message="validation failed"):
    return ApiError(422, "validation_failed", message)


def unauthenticated(message="authentication required"):
    return ApiError(401, "unauthenticated", message)


def forbidden(message="not permitted"):
    return ApiError(403, "forbidden", message)


def not_found(message="not found"):
    return ApiError(404, "not_found", message)


def insufficient_funds():
    return ApiError(409, "insufficient_funds", "balance is below the amount")


def request_not_pending():
    return ApiError(409, "request_not_pending", "request is not pending")
