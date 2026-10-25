"""Bounded retry and safe user-facing errors for optional OpenAI requests."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    body = getattr(error, "body", None)
    if not code and isinstance(body, dict):
        details = body.get("error")
        if isinstance(details, dict):
            code = details.get("code")
    return str(code or "").casefold()


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, min(10.0, float(raw)))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(raw))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, min(10.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def is_retryable_api_error(error: Exception) -> bool:
    """Retry only transient transport/server errors and non-quota rate limits."""
    kind = type(error).__name__
    if kind in {"APITimeoutError", "APIConnectionError", "InternalServerError"}:
        return True
    if kind == "RateLimitError":
        return _error_code(error) not in {"insufficient_quota", "billing_hard_limit_reached", "quota_exceeded"}
    status = getattr(error, "status_code", None)
    try:
        return int(status) >= 500
    except (TypeError, ValueError):
        return False


def call_with_retries(operation: Callable[[], T], *, attempts: int = 3,
                      sleep: Callable[[float], None] = time.sleep) -> T:
    """Run one operation with at most two bounded transient retries."""
    attempts = max(1, min(int(attempts), 3))
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            if attempt + 1 >= attempts or not is_retryable_api_error(error):
                raise
            delay = _retry_after_seconds(error)
            sleep(delay if delay is not None else 0.5 * (2 ** attempt))
    raise RuntimeError("Retry loop ended unexpectedly.")


def safe_api_error(service: str, error: Exception) -> str:
    """Describe common API failures without echoing request/receipt contents."""
    kind = type(error).__name__
    code = _error_code(error)
    if kind in {"AuthenticationError", "PermissionDeniedError"}:
        return f"{service} access was rejected. Check the API key and project permissions."
    if kind == "RateLimitError" and code in {"insufficient_quota", "billing_hard_limit_reached", "quota_exceeded"}:
        return f"{service} quota or billing limit was reached. Check the API account; PantryPilot did not retry this request."
    if kind == "RateLimitError":
        return f"{service} is rate-limiting requests. Wait a moment and try again."
    if kind in {"APITimeoutError", "APIConnectionError"}:
        return f"{service} could not be reached in time. Check your connection and try again."
    if kind in {"BadRequestError", "UnprocessableEntityError"}:
        return f"{service} rejected this request. Try a different image or simpler recipe selection."
    try:
        status = int(getattr(error, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    if status >= 500 or kind == "InternalServerError":
        return f"{service} is temporarily unavailable. Try again later."
    return f"{service} request failed ({kind}). Check the API key and connection, then try again."
