"""YouTube upload, quota, thumbnail, and scheduling errors."""

from __future__ import annotations

import json

from googleapiclient.errors import HttpError

_QUOTA_REASONS = {
    "quotaexceeded", "dailylimitexceeded", "dailylimitexceededunreg",
    "uploadlimitexceeded", "uploadratelimitexceeded", "userlimitexceeded", "ratelimitexceeded",
}


class UploadError(RuntimeError):
    """Raised when an upload cannot be safely continued."""


class RetryableUploadError(UploadError):
    """A network or server failure that can be retried after checking status."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UploadSessionExpired(UploadError):
    """Raised when Google has expired a resumable upload session."""


class ScheduledPublishTimeExpired(UploadError):
    """Raised before another request when a scheduled upload's time has passed."""


class UploadCompletionPending(UploadError):
    """Raised when all bytes arrived but YouTube has not returned the video ID yet."""


class QuotaExceeded(RuntimeError):
    """Raised for a daily or upload quota limit; the rest of the queue must stop."""

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        # Only known API codes may leave the transport; never expose response text.
        self.error_code = {
            "quotaexceeded": "quotaExceeded",
            "dailylimitexceeded": "dailyLimitExceeded",
            "dailylimitexceededunreg": "dailyLimitExceededUnreg",
            "uploadlimitexceeded": "uploadLimitExceeded",
            "uploadratelimitexceeded": "uploadRateLimitExceeded",
            "userlimitexceeded": "userLimitExceeded",
        }.get(reason, "quota")


class ThumbnailError(RuntimeError):
    """A custom thumbnail failed independently from the uploaded video."""

    def __init__(self, message: str, *, retryable: bool = True, error_code: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_code = error_code


class VideoSchedulingError(RuntimeError):
    """A video could not be safely scheduled for future publication."""

    def __init__(self, message: str, error_code: str = "video_scheduling_error") -> None:
        super().__init__(message)
        self.error_code = error_code


def _http_error_reason(exc: HttpError) -> str | None:
    try:
        content = exc.content.decode("utf-8") if isinstance(exc.content, bytes) else str(exc.content)
        payload = json.loads(content)
        errors = payload.get("error", {}).get("errors", [])
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason", "")).casefold() or None
    except (AttributeError, ValueError, TypeError):
        return None
    return None
