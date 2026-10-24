"""Batch upload execution: one job at a time, stopping the queue on unsafe outcomes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..auth import AuthorizationRevokedError, ChannelRef, ChannelResolutionError, resolve_channel
from ..config.profile import ProfileError, ProfileStore, validate_upload_profile
from ..jobs.store import JobStore
from ..media import probe_media
from ..models import (
    BatchReport,
    MediaFacts,
    ThumbnailResult,
    UploadItemResult,
    UploadJob,
    UploadProfile,
    VideoUploadResult,
)
from ..youtube.errors import (
    QuotaExceeded,
    RetryableUploadError,
    ScheduledPublishTimeExpired,
    ThumbnailError,
    UploadCompletionPending,
    UploadError,
    VideoSchedulingError,
)
from ..youtube.transport import ResumableUploader
from .preflight import PreflightMixin
from .results import (
    build_report,
    changed_file_status,
    error_code,
    failed_item,
    file_hash,
    uploaded_item,
    video_result_from_job,
)
from .schedule import format_publish_at, parse_publish_at

_SHORTS_PROCESSING_POLL_INTERVAL_SECONDS = 10
_SHORTS_PROCESSING_MAX_POLLS = 60


@dataclass(slots=True)
class JobOutcome:
    """Items produced for one job and, when the queue must stop, why.

    ``rest_status`` is the status given to every later job; by default
    ``pending_quota`` after a quota stop and ``pending_batch`` otherwise.
    """

    items: list[UploadItemResult] = field(default_factory=list)
    stop_reason: str | None = None
    rest_status: str | None = None


def _stop(item: UploadItemResult, reason: str, rest_status: str = "pending_batch") -> JobOutcome:
    return JobOutcome([item], reason, rest_status)


def _is_past(moment: datetime) -> bool:
    return moment <= datetime.now(moment.tzinfo)


class BatchRunner(PreflightMixin):
    """Run local preflight and batch uploads only for an explicitly selected folder."""

    def __init__(
        self,
        profile: UploadProfile,
        store: JobStore,
        api: Any,
        *,
        profile_store: ProfileStore | None = None,
        probe: Callable[[Path], MediaFacts] = probe_media,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ) -> None:
        self.profile = profile
        self.store = store
        self.api = api
        self.profile_store = profile_store
        self.probe = probe
        self.sleep = sleep
        self.log = log

    def upload(
        self,
        folder: Path,
        requested_channel: str,
        *,
        limit: int | None = None,
        force_private: bool = False,
        file_name: str | None = None,
        on_preflight: Callable[[Any, int, int, str, UploadProfile], None] | None = None,
        schedule_from: datetime | None = None,
        on_schedule_plan: Callable[[dict[Path, datetime]], None] | None = None,
    ) -> BatchReport:
        """Upload a specified folder, optionally as an orientation-paired schedule."""
        batch = self.prepare_upload(
            folder,
            requested_channel,
            limit=limit,
            force_private=force_private,
            file_name=file_name,
            schedule_from=schedule_from,
        )
        if batch.schedule_plan is not None and on_schedule_plan is not None:
            on_schedule_plan(batch.schedule_plan)
        if on_preflight is not None:
            predicted_skips = sum(job.state in {"complete", "skipped"} for job in batch.jobs)
            on_preflight(
                batch.channel,
                len(batch.jobs),
                len(batch.report_items) + predicted_skips,
                batch.effective_privacy,
                self.profile,
            )
        upload_report = self.upload_prepared(batch.jobs, scheduled_times=batch.scheduled_times)
        return build_report(
            [*batch.report_items, *upload_report.items], stopped_reason=upload_report.stopped_reason
        )

    def upload_prepared(
        self,
        jobs: Sequence[UploadJob],
        *,
        scheduled_times: Mapping[str, datetime] | None = None,
    ) -> BatchReport:
        """Upload or resume already validated jobs without rescanning a parent folder."""
        items: list[UploadItemResult] = []
        stopped_reason: str | None = None
        for index, prepared in enumerate(jobs):
            job = self.store.get_job(prepared.id)
            outcome = self._process_job(job, (scheduled_times or {}).get(job.id))
            items.extend(outcome.items)
            if outcome.stop_reason:
                stopped_reason = outcome.stop_reason
                rest_status = outcome.rest_status or (
                    "pending_quota" if stopped_reason == "quota" else "pending_batch"
                )
                items.extend(UploadItemResult(status=rest_status, source_path=rest.path) for rest in jobs[index + 1 :])
                break
        return build_report(items, stopped_reason=stopped_reason)

    # -- per-job steps ---------------------------------------------------------------

    def _process_job(self, job: UploadJob, scheduled_at: datetime | None) -> JobOutcome:
        if self.profile.channel_id and job.channel_id != self.profile.channel_id:
            return JobOutcome([failed_item(job, "channel_mismatch")])

        if scheduled_at is None and job.metadata.publish_at is not None and job.state in {
            "discovered", "validated", "uploading"
        }:
            reason = "scheduled_job_requires_schedule_mode"
            return _stop(failed_item(job, reason), reason)

        if scheduled_at is not None:
            guard = self._schedule_guard(job, scheduled_at)
            if guard is not None:
                return guard
            if job.state in {"uploaded", "complete"}:
                job, failure = self._schedule_existing(job, scheduled_at)
                if failure is not None:
                    return failure

        if job.state == "complete":
            if scheduled_at is None:
                return JobOutcome([uploaded_item(job, status="skipped_already_uploaded")])
            item = uploaded_item(job, status="scheduled_existing")
            if _is_past(scheduled_at):
                return _stop(item, "publish_time_expired_after_schedule_update")
            return JobOutcome([item])
        if job.state in {"failed", "skipped"}:
            status = "failed" if job.state == "failed" else "skipped"
            return JobOutcome([UploadItemResult(status=status, source_path=job.path, error_code=job.failure_code)])

        if job.state == "uploaded" and job.video_id:
            thumbnail_item, quota = self._set_thumbnail(job, video_result_from_job(job))
            return self._thumbnail_outcome(
                thumbnail_item, quota, scheduled_at,
                expired_reason="publish_time_expired_after_schedule_update",
            )

        try:
            validate_upload_profile(self.profile, requested_privacy=job.metadata.privacy_status)
        except ProfileError as exc:
            return JobOutcome([failed_item(job, error_code(exc))])

        changed = changed_file_status(job)
        if changed is not None and scheduled_at is None:
            self.store.mark_skipped(job.id, changed.removeprefix("skipped_"))
            return JobOutcome([UploadItemResult(status=changed, source_path=job.path, error_code=changed)])

        if job.state == "discovered":
            self.store.mark_validated(job.id)
            job = self.store.get_job(job.id)
        return self._upload_new(job, scheduled_at)

    def _schedule_guard(self, job: UploadJob, scheduled_at: datetime) -> JobOutcome | None:
        """Stop a scheduled batch before any request when the slot expired or a file changed."""
        try:
            parse_publish_at(format_publish_at(scheduled_at))
        except ValueError:
            return _stop(failed_item(job, "publish_time_expired"), "publish_time_expired")
        changed = changed_file_status(job)
        if changed is not None:
            return _stop(UploadItemResult(status=changed, source_path=job.path, error_code=changed), changed)
        return None

    def _schedule_existing(
        self, job: UploadJob, scheduled_at: datetime
    ) -> tuple[UploadJob, JobOutcome | None]:
        """Apply a schedule to an already uploaded video and record the confirmed readback."""
        try:
            if not job.video_id:
                raise VideoSchedulingError("Uploaded job has no YouTube video ID")
            schedule_video = getattr(self.api, "schedule_video", None)
            if not callable(schedule_video):
                raise VideoSchedulingError("YouTube API does not support scheduled publishing")
            schedule_video(job.video_id, job.channel_id, scheduled_at)
            self.store.refresh_api_record(
                job.id,
                datetime.now(timezone.utc),
                {"privacy_status": "private", "publish_at": format_publish_at(scheduled_at)},
            )
            return self.store.get_job(job.id), None
        except AuthorizationRevokedError:
            raise
        except QuotaExceeded as exc:
            return job, _stop(failed_item(job, exc.error_code, video_id=job.video_id), "quota", "pending_quota")
        except Exception as exc:
            return job, _stop(failed_item(job, error_code(exc), video_id=job.video_id), "scheduled_update_failed")

    def _upload_new(self, job: UploadJob, scheduled_at: datetime | None) -> JobOutcome:
        try:
            result = self._upload_video(job)
            self.store.mark_video_uploaded(job.id, result.video_id, result.confirmed_at)
            uploaded_job = self.store.get_job(job.id)
        except AuthorizationRevokedError:
            raise
        except QuotaExceeded as exc:
            return self._upload_quota_outcome(job, scheduled_at, exc)
        except VideoSchedulingError as exc:
            current = self.store.get_job(job.id)
            return _stop(failed_item(job, exc.error_code, video_id=current.video_id), exc.error_code)
        except Exception as exc:
            return self._upload_error_outcome(job, scheduled_at, exc)

        if result.actual_visibility in {"private", "unlisted", "public"}:
            api_fields = {"privacy_status": result.actual_visibility}
            if job.metadata.publish_at is not None:
                api_fields["publish_at"] = job.metadata.publish_at
            self.store.refresh_api_record(job.id, result.confirmed_at, api_fields)
            uploaded_job = self.store.get_job(job.id)
        thumbnail_item, quota = self._set_thumbnail(uploaded_job, result)
        return self._thumbnail_outcome(
            thumbnail_item, quota, scheduled_at, expired_reason="publish_time_expired_after_upload"
        )

    def _upload_quota_outcome(self, job: UploadJob, scheduled_at: datetime | None, exc: QuotaExceeded) -> JobOutcome:
        current = self.store.get_job(job.id)
        if scheduled_at is not None and current.video_id:
            item = failed_item(job, exc.error_code, video_id=current.video_id)
        elif current.state == "uploaded" and current.video_id:
            self.store.mark_thumbnail_result(job.id, success=False)
            current = self.store.get_job(job.id)
            item = uploaded_item(
                current,
                result=video_result_from_job(current),
                status="uploaded_thumbnail_failed",
                thumbnail_status="failed",
                error_code=exc.error_code,
            )
        elif current.state == "complete" and current.video_id:
            item = uploaded_item(current, status="uploaded", thumbnail_status="success")
        else:
            item = UploadItemResult(status="pending_quota", source_path=job.path, error_code=exc.error_code)
        return _stop(item, "quota", "pending_quota")

    def _upload_error_outcome(self, job: UploadJob, scheduled_at: datetime | None, exc: Exception) -> JobOutcome:
        current = self.store.get_job(job.id)
        if isinstance(exc, (ScheduledPublishTimeExpired, UploadCompletionPending)):
            code = error_code(exc)
            return _stop(failed_item(job, code, video_id=current.video_id), code)
        if scheduled_at is not None and current.video_id:
            return _stop(failed_item(job, "schedule_unconfirmed", video_id=current.video_id), "schedule_unconfirmed")
        if current.state == "uploaded" and current.video_id:
            # The video arrived before the error; finish its thumbnail instead of failing it.
            thumbnail_item, quota = self._set_thumbnail(current, video_result_from_job(current))
            return self._thumbnail_outcome(
                thumbnail_item, quota, scheduled_at, stop_on_failure=False, expired_reason=None
            )
        if current.state == "complete" and current.video_id:
            return JobOutcome([uploaded_item(current, status="uploaded", thumbnail_status="success")])
        if isinstance(exc, RetryableUploadError) and current.state in {"validated", "uploading"}:
            item = UploadItemResult(status="pending_retry", source_path=job.path, error_code="retryable_upload_error")
            return _stop(item, "transient_upload_error")
        if current.state not in {"failed", "skipped"}:
            self.store.mark_failed(job.id, error_code(exc))
        item = failed_item(job, error_code(exc), video_id=current.video_id)
        if scheduled_at is not None:
            return _stop(item, "scheduled_upload_failed")
        return JobOutcome([item])

    @staticmethod
    def _thumbnail_outcome(
        item: UploadItemResult,
        quota: bool,
        scheduled_at: datetime | None,
        *,
        stop_on_failure: bool = True,
        expired_reason: str | None,
    ) -> JobOutcome:
        if quota:
            return _stop(item, "quota", "pending_quota")
        if stop_on_failure and item.status == "uploaded_thumbnail_failed":
            return JobOutcome([item], item.error_code or "thumbnail_failed")
        if scheduled_at is not None and item.error_code == "changed_thumbnail":
            return _stop(item, "skipped_changed_thumbnail")
        if expired_reason and scheduled_at is not None and _is_past(scheduled_at):
            return _stop(item, expired_reason)
        return JobOutcome([item])

    # -- API helpers -----------------------------------------------------------------

    def _resolve_owned_channel(self, requested_channel: str) -> ChannelRef:
        list_owned = getattr(self.api, "list_owned_channels", None)
        if not callable(list_owned):
            raise ChannelResolutionError("YouTube API cannot verify channels owned by the signed-in account")
        lookup = requested_channel
        if (
            self.profile.channel_id
            and isinstance(self.profile.channel_alias, str)
            and requested_channel.strip().casefold() == self.profile.channel_alias.strip().casefold()
        ):
            lookup = self.profile.channel_id
        channel = resolve_channel(lookup, list_owned())
        if self.profile.channel_id and self.profile.channel_id != channel.channel_id:
            raise ChannelResolutionError("Requested channel does not match the channel saved in this profile")
        if not self.profile.channel_id:
            self.profile = replace(self.profile, channel_id=channel.channel_id)
            if self.profile_store is not None:
                self.profile_store.save(self.profile)
        return channel

    def _upload_video(self, job: UploadJob) -> VideoUploadResult:
        upload_video = getattr(self.api, "upload_video", None)
        if callable(upload_video):
            return upload_video(job, job.path)
        transport_methods = ("begin_upload", "query_session", "upload_chunk")
        if all(callable(getattr(self.api, method, None)) for method in transport_methods):
            return ResumableUploader(self.api, self.store, sleep=self.sleep).upload(job, job.path)
        raise UploadError("Upload API does not provide a resumable video transport")

    def _set_thumbnail(self, job: UploadJob, result: VideoUploadResult) -> tuple[UploadItemResult, bool]:
        """Send the paired thumbnail; return the item and whether a quota limit stopped it."""

        def failed(code: str) -> UploadItemResult:
            self.store.mark_thumbnail_result(job.id, success=False)
            return uploaded_item(
                job, result=result, status="uploaded_thumbnail_failed", thumbnail_status="failed", error_code=code
            )

        if not self._thumbnail_unchanged(job):
            self.store.mark_thumbnail_result(job.id, success=False)
            return (
                UploadItemResult(
                    status="uploaded_thumbnail_failed",
                    source_path=job.path,
                    video_id=result.video_id,
                    video_url=result.video_url,
                    actual_visibility=result.actual_visibility,
                    thumbnail_status="failed",
                    error_code="changed_thumbnail",
                ),
                False,
            )

        try:
            self._send_thumbnail(result.video_id, job.thumbnail_path)
            if self._is_vertical_short(job):
                pending = self._resend_after_processing(job, result)
                if pending is not None:
                    return pending, False
        except AuthorizationRevokedError:
            raise
        except QuotaExceeded as exc:
            return failed(exc.error_code), True
        except ThumbnailError as exc:
            return failed(exc.error_code or "thumbnail_error"), False
        except Exception as exc:
            return failed(error_code(exc)), False

        self.store.mark_thumbnail_result(job.id, success=True)
        return uploaded_item(job, result=result, status="uploaded", thumbnail_status="success"), False

    def _resend_after_processing(self, job: UploadJob, result: VideoUploadResult) -> UploadItemResult | None:
        """YouTube may replace a Short's thumbnail while processing; send it again once done."""
        self.log(f"YouTube กำลังประมวลผลคลิปสั้นแนวตั้ง: {job.path.name}")
        processing_status = self._wait_for_video_processing(result.video_id)
        if processing_status == "timeout":
            return uploaded_item(
                job,
                result=result,
                status="uploaded_thumbnail_pending",
                thumbnail_status="pending",
                error_code="processing_timeout",
            )
        if processing_status in {"failed", "terminated"}:
            raise ThumbnailError(
                "YouTube did not finish processing the uploaded Short",
                retryable=processing_status == "failed",
                error_code=f"processing_{processing_status}",
            )
        if not self._thumbnail_unchanged(job):
            raise ThumbnailError(
                "The selected thumbnail changed while YouTube processed the Short",
                retryable=False,
                error_code="changed_thumbnail",
            )
        self.log(f"YouTube ประมวลผลเสร็จแล้ว กำลังส่งปกคลิปซ้ำ: {job.path.name}")
        self._send_thumbnail(result.video_id, job.thumbnail_path)
        return None

    @staticmethod
    def _thumbnail_unchanged(job: UploadJob) -> bool:
        try:
            return file_hash(job.thumbnail_path) == job.thumbnail_sha256
        except OSError:
            return False

    def _send_thumbnail(self, video_id: str, thumbnail_path: Path) -> None:
        response = self.api.set_thumbnail(video_id, thumbnail_path)
        if isinstance(response, ThumbnailResult) and not response.success:
            raise ThumbnailError(
                "YouTube rejected the custom thumbnail",
                retryable=True,
                error_code="thumbnail_rejected",
            )

    def _wait_for_video_processing(self, video_id: str) -> str:
        get_status = getattr(self.api, "get_processing_status", None)
        if not callable(get_status):
            # Preserve support for alternate API adapters while still applying the second set.
            return "succeeded"
        for poll in range(_SHORTS_PROCESSING_MAX_POLLS):
            try:
                status = get_status(video_id)
            except ThumbnailError as exc:
                if not exc.retryable:
                    raise
                status = None
            if status in {"succeeded", "failed", "terminated"}:
                return status
            if poll + 1 < _SHORTS_PROCESSING_MAX_POLLS:
                self.sleep(_SHORTS_PROCESSING_POLL_INTERVAL_SECONDS)
        return "timeout"

    @staticmethod
    def _is_vertical_short(job: UploadJob) -> bool:
        return job.metadata.short_candidate and job.path.stem.casefold().endswith("_9x16")
