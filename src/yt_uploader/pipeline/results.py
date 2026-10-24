"""Per-file result items, batch reports, error codes, and file-change checks."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ..config.profile import ProfileError
from ..jobs.store import JobStateError
from ..media import MediaProbeError, MetadataError
from ..models import BatchReport, UploadItemResult, UploadJob, VideoUploadResult
from ..youtube.errors import (
    ScheduledPublishTimeExpired,
    UploadCompletionPending,
    UploadError,
    VideoSchedulingError,
)


def video_url(video_id: str | None) -> str | None:
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else None


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_file_status(job: UploadJob) -> str | None:
    """Return the skip status when the video or its paired thumbnail no longer matches its hash."""
    try:
        video_hash = file_hash(job.path)
    except OSError:
        return "skipped_changed_file"
    if video_hash != job.sha256:
        return "skipped_changed_file"
    try:
        thumbnail_hash = file_hash(job.thumbnail_path)
    except OSError:
        return "skipped_changed_thumbnail"
    if thumbnail_hash != job.thumbnail_sha256:
        return "skipped_changed_thumbnail"
    return None


def error_code(exc: Exception) -> str:
    if isinstance(exc, VideoSchedulingError):
        return exc.error_code
    if isinstance(exc, ScheduledPublishTimeExpired):
        return "publish_time_expired"
    if isinstance(exc, UploadCompletionPending):
        return "upload_completion_pending"
    if isinstance(exc, ProfileError):
        return "profile_error"
    if isinstance(exc, MetadataError):
        return "metadata_error"
    if isinstance(exc, MediaProbeError):
        return "media_probe_error"
    if isinstance(exc, JobStateError):
        return "job_state_error"
    return type(exc).__name__.casefold()


def video_result_from_job(job: UploadJob) -> VideoUploadResult:
    if not job.video_id:
        raise UploadError("Uploaded job has no YouTube video ID")
    return VideoUploadResult(
        video_id=job.video_id,
        actual_visibility=job.api_fields.get("privacy_status", "unknown"),
        video_url=video_url(job.video_id) or "",
        confirmed_at=job.api_refreshed_at or datetime.now(timezone.utc),
    )


def uploaded_item(
    job: UploadJob,
    *,
    result: VideoUploadResult | None = None,
    status: str,
    thumbnail_status: str | None = None,
    error_code: str | None = None,
) -> UploadItemResult:
    video_id = result.video_id if result else job.video_id
    return UploadItemResult(
        status=status,
        source_path=job.path,
        video_id=video_id,
        video_url=result.video_url if result else video_url(video_id),
        actual_visibility=(result.actual_visibility if result else job.api_fields.get("privacy_status", "unknown")),
        thumbnail_status=thumbnail_status or job.thumbnail_status,
        error_code=error_code,
        scheduled_publish_at=job.api_fields.get("publish_at") or job.metadata.publish_at,
    )


def failed_item(job: UploadJob, code: str | None, *, video_id: str | None = None) -> UploadItemResult:
    return UploadItemResult(
        status="failed",
        source_path=job.path,
        video_id=video_id,
        video_url=video_url(video_id),
        error_code=code,
    )


def build_report(items: list[UploadItemResult], *, stopped_reason: str | None = None) -> BatchReport:
    return BatchReport(
        items=items,
        uploaded_count=sum(item.status.startswith("uploaded") for item in items),
        skipped_count=sum(item.status.startswith("skipped") for item in items),
        failed_count=sum(item.status == "failed" for item in items),
        pending_count=sum(
            item.status.startswith("pending") or item.status == "uploaded_thumbnail_pending"
            for item in items
        ),
        stopped_reason=stopped_reason,
        scheduled_count=sum(item.scheduled_publish_at is not None for item in items),
    )
