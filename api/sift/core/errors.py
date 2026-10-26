"""Domain errors. Each carries the HTTP status it maps to and a message safe to show users."""

from __future__ import annotations


class SiftError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFound(SiftError):
    status, code = 404, "not_found"


class Conflict(SiftError):
    status, code = 409, "conflict"


class InvalidInput(SiftError):
    status, code = 422, "invalid_input"


class TooLarge(SiftError):
    status, code = 413, "too_large"


class Unauthorized(SiftError):
    status, code = 401, "unauthorized"


class Forbidden(SiftError):
    status, code = 403, "forbidden"


class RateLimited(SiftError):
    status, code = 429, "rate_limited"


class Unavailable(SiftError):
    status, code = 503, "unavailable"
