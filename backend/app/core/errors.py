"""Application error hierarchy, mapped to HTTP responses.

One rule worth stating explicitly: **cross-tenant access returns 404, not
403**. A 403 confirms the resource exists, which tells an attacker that
company X has a project with that id. 404 tells them nothing.

So `NotFoundError` is raised both when a row is genuinely absent and when
it belongs to another company. The caller cannot tell the difference,
which is the point.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"
    default_message: str = "Something went wrong."

    def __init__(self, message: str | None = None, *, detail: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.detail = detail or {}
        super().__init__(self.message)

    def to_problem(self) -> dict[str, Any]:
        """RFC 7807 problem+json body."""
        body: dict[str, Any] = {
            "type": f"/errors/{self.error_code}",
            "title": self.error_code,
            "status": self.status_code,
            "detail": self.message,
        }
        if self.detail:
            body["errors"] = self.detail
        return body


class AuthError(AppError):
    status_code = 401
    error_code = "unauthenticated"
    default_message = "Authentication required."


class InvalidCredentialsError(AuthError):
    error_code = "invalid_credentials"
    # Deliberately vague: saying "no such user" lets an attacker
    # enumerate which email addresses have accounts.
    default_message = "Email or password is incorrect."


class TokenReuseError(AuthError):
    error_code = "token_reuse_detected"
    default_message = "Session ended for security reasons. Please sign in again."


class PermissionDeniedError(AppError):
    status_code = 403
    error_code = "permission_denied"
    default_message = "You do not have permission to do this."


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"
    default_message = "Not found."


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_failed"
    default_message = "The request could not be processed."


class ConflictError(AppError):
    status_code = 409
    error_code = "conflict"
    default_message = "That conflicts with something that already exists."


class LimitReachedError(ConflictError):
    error_code = "limit_reached"
    default_message = "You have reached your plan limit."


class UpstreamError(AppError):
    """A service we call on the company's behalf failed."""

    status_code = 502
    error_code = "upstream_error"
    default_message = "An outside service did not respond properly. Try again."


class RateLimitError(AppError):
    status_code = 429
    error_code = "rate_limited"
    default_message = "Too many requests. Please slow down."
