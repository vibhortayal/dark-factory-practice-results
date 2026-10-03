"""API error type and the error constructors used across the service."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message: str = "malformed request") -> ApiError:
    return ApiError(400, "malformed_request", message)


def missing_key() -> ApiError:
    return ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")


def unauthenticated(message: str = "missing or invalid bearer token") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "not permitted") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "not found") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def invalid(message: str, code: str = "validation_failed") -> ApiError:
    return ApiError(422, code, message)
