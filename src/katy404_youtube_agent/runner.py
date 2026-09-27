"""Batch planning, upload gating, preflight checks, and per-file reporting."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .auth import AuthorizationRevokedError, ChannelResolutionError, resolve_channel
from .media import MediaProbeError, MetadataError, build_metadata, probe_media
from .models import (
    BatchReport,
    MediaCandidate,
    MediaFacts,
    ThumbnailResult,
    UploadItemResult,
    UploadJob,
    UploadProfile,
    VideoMetadata,
    VideoUploadResult,
)
from .profile import ProfileError, ProfileStore, validate_upload_profile
from .scanner import scan_folder
from .scheduling import format_publish_at, parse_publish_at, plan_daily_pairs
from .store import JobStateError, JobStore
from .youtube import (
    QuotaExceeded,
    ResumableUploader,
    RetryableUploadError,
    ScheduledPublishTimeExpired,
    ThumbnailError,
    UploadCompletionPending,
    UploadError,
    VideoSchedulingError,
)


class BatchRunner:
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
    ) -> None:
        self.profile = profile
        self.store = store
        self.api = api
        self.profile_store = profile_store
        self.probe = probe
        self.sleep = sleep

    def dry_run(self, folder: Path, requested_channel: str) -> BatchReport:
        """Inspect a folder locally without resolving OAuth or making API calls."""
        if not requested_channel or not requested_channel.strip():
            raise ChannelResolutionError("A channel ID, handle, or name is required")
        candidates, issues = scan_folder(Path(folder))
        items = [
            UploadItemResult(status="failed", source_path=issue.path, error_code=issue.code)
            for issue in issues
        ]
        for candidate in candidates:
            try:
                facts = self.probe(candidate.path)
                build_metadata(candidate, facts, self.profile)
            except (MediaProbeError, MetadataError, ProfileError) as exc:
                items.append(
                    UploadItemResult(
                        status="failed",
                        source_path=candidate.path,
                        error_code=self._error_code(exc),
                    )
                )
            else:
                items.append(UploadItemResult(status="ready", source_path=candidate.path))
        return self._report(items)

    def requeue_failed(self, path: Path, channel_id: str) -> UploadJob:
        """Requeue one explicitly named failed file after verifying both paired assets."""
        if not channel_id or not channel_id.strip():
            raise JobStateError("A verified channel ID is required to requeue a failed upload")
        if self.profile.channel_id != channel_id:
            raise JobStateError("Requested channel does not match the channel saved in this profile")
        target = os.path.normcase(os.path.abspath(Path(path)))
        matching = [
            job for job in self.store.list_jobs(channel_id)
            if os.path.normcase(os.path.abspath(job.path)) == target
        ]
        if len(matching) != 1:
            raise JobStateError("No unique saved upload job matches the requested file path")
        job = matching[0]
        if job.state != "failed":
            raise JobStateError(f"Only failed uploads can be requeued; current state is {job.state}")
        changed = self._changed_file_status(job)
        if changed is not None:
            raise JobStateError(f"Cannot retry because the source or paired thumbnail changed ({changed})")
        effective_privacy = self.profile.privacy_status
        validate_upload_profile(self.profile, requested_privacy=effective_privacy)
        candidate = MediaCandidate(
            path=job.path,
            thumbnail_path=job.thumbnail_path,
            sha256=job.sha256,
            thumbnail_sha256=job.thumbnail_sha256,
            size_bytes=job.size_bytes,
            thumbnail_size_bytes=job.thumbnail_path.stat().st_size,
            modified_ns=job.modified_ns,
        )
        metadata_profile = replace(self.profile, privacy_status=effective_privacy)
        metadata = build_metadata(candidate, self.probe(job.path), metadata_profile)
        self.store.requeue_failed(job.id, metadata)
        return self.store.get_job(job.id)

    def upload(
        self,
        folder: Path,
        requested_channel: str,
        *,
        limit: int | None = None,
        force_private: bool = False,
        on_preflight: Callable[[Any, int, int, str, UploadProfile], None] | None = None,
        schedule_from: datetime | None = None,
        on_schedule_plan: Callable[[dict[Path, datetime]], None] | None = None,
    ) -> BatchReport:
        """Upload a specified folder, optionally as an orientation-paired schedule."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be a positive integer")
        if force_private and limit != 1:
            raise ValueError("force_private is reserved for one-video uploads")
        scheduled_mode = schedule_from is not None
        if scheduled_mode and (limit is not None or force_private):
            raise ValueError("scheduled publishing requires a full batch without --limit or --force-private")
        if not requested_channel or not requested_channel.strip():
            raise ChannelResolutionError("A channel ID, handle, or name is required")

        effective_privacy = "private" if force_private or scheduled_mode else self.profile.privacy_status
        validate_upload_profile(
            self.profile,
            requested_privacy="public" if scheduled_mode else effective_privacy,
        )
        channel = self._resolve_owned_channel(requested_channel)
        candidates, issues = scan_folder(Path(folder))
        report_items = [
            UploadItemResult(status="failed", source_path=issue.path, error_code=issue.code)
            for issue in issues
        ]
        if scheduled_mode and issues:
            raise ProfileError("Scheduled batches require every selected video and thumbnail to pass preflight")

        prepared: list[tuple[MediaCandidate, MediaFacts, VideoMetadata]] = []
        for candidate in candidates:
            if limit is not None and len(prepared) >= limit:
                break
            try:
                facts = self.probe(candidate.path)
                metadata = build_metadata(candidate, facts, self.profile)
                if force_private or scheduled_mode:
                    metadata = replace(metadata, privacy_status="private")
                validate_upload_profile(
                    self.profile,
                    requested_privacy="public" if scheduled_mode else metadata.privacy_status,
                )
                prepared.append((candidate, facts, metadata))
            except (MediaProbeError, MetadataError, ProfileError) as exc:
                report_items.append(
                    UploadItemResult(
                        status="failed",
                        source_path=candidate.path,
                        error_code=self._error_code(exc),
                    )
                )
                if scheduled_mode:
                    raise ProfileError("Scheduled batches require every video to pass preflight") from exc

        schedule_plan: dict[Path, datetime] | None = None
        if scheduled_mode:
            assert schedule_from is not None
            schedule_plan = plan_daily_pairs(
                [(candidate, facts) for candidate, facts, _ in prepared], schedule_from
            )

        jobs: list[UploadJob] = []
        scheduled_times: dict[str, datetime] = {}
        scheduled_updates: list[tuple[UploadJob, VideoMetadata, datetime]] = []
        for candidate, _, metadata in prepared:
            if schedule_plan is not None:
                scheduled_at = schedule_plan[candidate.path]
                metadata = replace(metadata, publish_at=format_publish_at(scheduled_at))
            job = self.store.get_or_create_job(candidate, channel.channel_id, metadata)
            if schedule_plan is not None:
                changed = self._changed_file_status(job)
                if changed is not None:
                    raise ProfileError(
                        f"Scheduled preflight found a changed source or thumbnail ({changed})"
                    )
                if job.state in {"failed", "skipped"}:
                    raise ProfileError("Scheduled batches cannot contain failed or skipped local jobs")
                if job.id in scheduled_times:
                    raise ProfileError(
                        "Scheduled preflight found duplicate video content assigned to multiple daily slots"
                    )
                if job.state == "uploading" and (
                    job.metadata.publish_at != metadata.publish_at
                    or job.metadata.privacy_status != "private"
                ):
                    if job.metadata.publish_at is None or job.metadata.privacy_status != "private":
                        raise ProfileError(
                            "A resumable upload already started without a private publish time; reconcile it manually"
                        )
                    reconcile_session = getattr(self.api, "reconcile_scheduled_upload", None)
                    if not callable(reconcile_session):
                        raise ProfileError("YouTube API cannot safely reconcile a previous scheduled upload")
                    job = reconcile_session(job)
                    if job.state == "uploading":
                        raise ProfileError(
                            "YouTube received all video bytes but has not confirmed completion; keep the session and retry status reconciliation"
                        )
                scheduled_times[job.id] = scheduled_at
                scheduled_updates.append((job, metadata, scheduled_at))
            jobs.append(job)

        # Defer all existing-job schedule changes until duplicate identities and
        # incompatible resumable sessions have been checked for the whole batch.
        for job, metadata, _ in scheduled_updates:
            if job.state in {"discovered", "validated"} and job.metadata != metadata:
                self.store.update_preupload_metadata(job.id, metadata)

        if schedule_plan is not None:
            jobs = [self.store.get_job(job.id) for job in jobs]

        if schedule_plan is not None and on_schedule_plan is not None:
            on_schedule_plan(schedule_plan)

        if on_preflight is not None:
            predicted_skips = sum(job.state in {"complete", "skipped"} for job in jobs)
            on_preflight(
                channel,
                len(jobs),
                len(report_items) + predicted_skips,
                effective_privacy,
                self.profile,
            )

        upload_report = self.upload_prepared(jobs, scheduled_times=scheduled_times if schedule_plan is not None else None)
        report_items.extend(upload_report.items)
        return self._report(report_items, stopped_reason=upload_report.stopped_reason)

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
            if stopped_reason:
                pending_status = "pending_quota" if stopped_reason == "quota" else "pending_batch"
                items.append(UploadItemResult(status=pending_status, source_path=prepared.path))
                continue
            job = self.store.get_job(prepared.id)
            scheduled_at = (scheduled_times or {}).get(job.id)
            if self.profile.channel_id and job.channel_id != self.profile.channel_id:
                items.append(
                    UploadItemResult(status="failed", source_path=job.path, error_code="channel_mismatch")
                )
                continue

            if scheduled_at is None and job.metadata.publish_at is not None and job.state in {
                "discovered", "validated", "uploading"
            }:
                items.append(UploadItemResult(
                    status="failed", source_path=job.path,
                    error_code="scheduled_job_requires_schedule_mode",
                ))
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                stopped_reason = "scheduled_job_requires_schedule_mode"
                break

            if scheduled_at is not None:
                try:
                    parse_publish_at(format_publish_at(scheduled_at))
                except ValueError as exc:
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path,
                        error_code="publish_time_expired",
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "publish_time_expired"
                    break

                changed = self._changed_file_status(job)
                if changed is not None:
                    items.append(UploadItemResult(
                        status=changed, source_path=job.path, error_code=changed,
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = changed
                    break

            if scheduled_at is not None and job.state in {"uploaded", "complete"}:
                try:
                    if not job.video_id:
                        raise VideoSchedulingError("Uploaded job has no YouTube video ID")
                    schedule_video = getattr(self.api, "schedule_video", None)
                    if not callable(schedule_video):
                        raise VideoSchedulingError("YouTube API does not support scheduled publishing")
                    schedule_video(job.video_id, job.channel_id, scheduled_at)
                    publish_value = format_publish_at(scheduled_at)
                    self.store.refresh_api_record(
                        job.id,
                        datetime.now(timezone.utc),
                        {"privacy_status": "private", "publish_at": publish_value},
                    )
                    job = self.store.get_job(job.id)
                except AuthorizationRevokedError:
                    raise
                except QuotaExceeded:
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path, video_id=job.video_id,
                        video_url=self._video_url(job.video_id), error_code="quota",
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_quota", source_path=pending.path))
                    stopped_reason = "quota"
                    break
                except Exception as exc:
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path, video_id=job.video_id,
                        video_url=self._video_url(job.video_id), error_code=self._error_code(exc),
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "scheduled_update_failed"
                    break

            if job.state == "complete":
                if scheduled_at is not None:
                    items.append(self._uploaded_item(job, status="scheduled_existing"))
                    if scheduled_at <= datetime.now(scheduled_at.tzinfo):
                        for pending in jobs[index + 1 :]:
                            items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                        stopped_reason = "publish_time_expired_after_schedule_update"
                        break
                else:
                    items.append(self._uploaded_item(job, status="skipped_already_uploaded"))
                continue
            if job.state in {"failed", "skipped"}:
                status = "failed" if job.state == "failed" else "skipped"
                items.append(
                    UploadItemResult(status=status, source_path=job.path, error_code=job.failure_code)
                )
                continue

            if job.state == "uploaded" and job.video_id:
                thumbnail_item, quota = self._set_thumbnail(job, self._video_result_from_job(job))
                items.append(thumbnail_item)
                if quota:
                    stopped_reason = "quota"
                elif scheduled_at is not None and thumbnail_item.error_code == "changed_thumbnail":
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "skipped_changed_thumbnail"
                    break
                elif scheduled_at is not None and scheduled_at <= datetime.now(scheduled_at.tzinfo):
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "publish_time_expired_after_schedule_update"
                    break
                continue

            try:
                validate_upload_profile(self.profile, requested_privacy=job.metadata.privacy_status)
            except ProfileError as exc:
                items.append(
                    UploadItemResult(status="failed", source_path=job.path, error_code=self._error_code(exc))
                )
                continue

            changed = self._changed_file_status(job)
            if changed is not None and scheduled_at is None:
                self.store.mark_skipped(job.id, changed.removeprefix("skipped_"))
                items.append(UploadItemResult(status=changed, source_path=job.path, error_code=changed))
                continue

            if job.state == "discovered":
                self.store.mark_validated(job.id)
                job = self.store.get_job(job.id)
            try:
                result = self._upload_video(job)
                self.store.mark_video_uploaded(job.id, result.video_id, result.confirmed_at)
                uploaded_job = self.store.get_job(job.id)
            except AuthorizationRevokedError:
                raise
            except QuotaExceeded:
                stopped_reason = "quota"
                current = self.store.get_job(job.id)
                if scheduled_at is not None and current.video_id:
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path,
                        video_id=current.video_id,
                        video_url=self._video_url(current.video_id),
                        error_code="quota",
                    ))
                elif current.state == "uploaded" and current.video_id:
                    self.store.mark_thumbnail_result(job.id, success=False)
                    current = self.store.get_job(job.id)
                    items.append(
                        self._uploaded_item(
                            current,
                            result=self._video_result_from_job(current),
                            status="uploaded_thumbnail_failed",
                            thumbnail_status="failed",
                            error_code="quota",
                        )
                    )
                elif current.state == "complete" and current.video_id:
                    items.append(self._uploaded_item(current, status="uploaded", thumbnail_status="success"))
                else:
                    items.append(UploadItemResult(status="pending_quota", source_path=job.path))
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_quota", source_path=pending.path))
                break
            except VideoSchedulingError as exc:
                current = self.store.get_job(job.id)
                items.append(UploadItemResult(
                    status="failed", source_path=job.path,
                    video_id=current.video_id,
                    video_url=self._video_url(current.video_id),
                    error_code=exc.error_code,
                ))
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                stopped_reason = exc.error_code
                break
            except Exception as exc:
                current = self.store.get_job(job.id)
                if isinstance(exc, (ScheduledPublishTimeExpired, UploadCompletionPending)):
                    error_code = (
                        "publish_time_expired"
                        if isinstance(exc, ScheduledPublishTimeExpired)
                        else "upload_completion_pending"
                    )
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path,
                        video_id=current.video_id,
                        video_url=self._video_url(current.video_id),
                        error_code=error_code,
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = error_code
                    break
                if scheduled_at is not None and current.video_id:
                    items.append(UploadItemResult(
                        status="failed", source_path=job.path,
                        video_id=current.video_id,
                        video_url=self._video_url(current.video_id),
                        error_code="schedule_unconfirmed",
                    ))
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "schedule_unconfirmed"
                    break
                if current.state == "uploaded" and current.video_id:
                    thumbnail_item, quota = self._set_thumbnail(
                        current, self._video_result_from_job(current)
                    )
                    items.append(thumbnail_item)
                    if quota:
                        stopped_reason = "quota"
                        for pending in jobs[index + 1 :]:
                            items.append(UploadItemResult(status="pending_quota", source_path=pending.path))
                        break
                    if scheduled_at is not None and thumbnail_item.error_code == "changed_thumbnail":
                        for pending in jobs[index + 1 :]:
                            items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                        stopped_reason = "skipped_changed_thumbnail"
                        break
                    continue
                if current.state == "complete" and current.video_id:
                    items.append(self._uploaded_item(current, status="uploaded", thumbnail_status="success"))
                    continue
                if isinstance(exc, RetryableUploadError) and current.state in {"validated", "uploading"}:
                    items.append(
                        UploadItemResult(
                            status="pending_retry",
                            source_path=job.path,
                            error_code="retryable_upload_error",
                        )
                    )
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "transient_upload_error"
                    break
                if current.state not in {"failed", "skipped"}:
                    self.store.mark_failed(job.id, self._error_code(exc))
                items.append(
                    UploadItemResult(
                        status="failed",
                        source_path=job.path,
                        video_id=current.video_id,
                        video_url=self._video_url(current.video_id),
                        error_code=self._error_code(exc),
                    )
                )
                if scheduled_at is not None:
                    for pending in jobs[index + 1 :]:
                        items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                    stopped_reason = "scheduled_upload_failed"
                    break
                continue

            if result.actual_visibility in {"private", "unlisted", "public"}:
                api_fields = {"privacy_status": result.actual_visibility}
                if job.metadata.publish_at is not None:
                    api_fields["publish_at"] = job.metadata.publish_at
                self.store.refresh_api_record(
                    job.id,
                    result.confirmed_at,
                    api_fields,
                )
                uploaded_job = self.store.get_job(job.id)
            thumbnail_item, quota = self._set_thumbnail(uploaded_job, result)
            items.append(thumbnail_item)
            if quota:
                stopped_reason = "quota"
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_quota", source_path=pending.path))
                break
            if scheduled_at is not None and thumbnail_item.error_code == "changed_thumbnail":
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                stopped_reason = "skipped_changed_thumbnail"
                break
            if scheduled_at is not None and scheduled_at <= datetime.now(scheduled_at.tzinfo):
                for pending in jobs[index + 1 :]:
                    items.append(UploadItemResult(status="pending_batch", source_path=pending.path))
                stopped_reason = "publish_time_expired_after_upload"
                break
        return self._report(items, stopped_reason=stopped_reason)

    def _resolve_owned_channel(self, requested_channel: str):
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

    def _set_thumbnail(
        self, job: UploadJob, result: VideoUploadResult
    ) -> tuple[UploadItemResult, bool]:
        try:
            current_hash = self._file_hash(job.thumbnail_path)
        except OSError:
            current_hash = None
        if current_hash != job.thumbnail_sha256:
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
            response = self.api.set_thumbnail(result.video_id, job.thumbnail_path)
            if isinstance(response, ThumbnailResult) and not response.success:
                self.store.mark_thumbnail_result(job.id, success=False)
                return (
                    self._uploaded_item(
                        job,
                        result=result,
                        status="uploaded_thumbnail_failed",
                        thumbnail_status="failed",
                        error_code="thumbnail_rejected",
                    ),
                    False,
                )
        except AuthorizationRevokedError:
            raise
        except QuotaExceeded:
            self.store.mark_thumbnail_result(job.id, success=False)
            return (
                self._uploaded_item(
                    job,
                    result=result,
                    status="uploaded_thumbnail_failed",
                    thumbnail_status="failed",
                    error_code="quota",
                ),
                True,
            )
        except ThumbnailError as exc:
            self.store.mark_thumbnail_result(job.id, success=False)
            return (
                self._uploaded_item(
                    job,
                    result=result,
                    status="uploaded_thumbnail_failed",
                    thumbnail_status="failed",
                    error_code=exc.error_code or "thumbnail_error",
                ),
                False,
            )
        except Exception as exc:
            self.store.mark_thumbnail_result(job.id, success=False)
            return (
                self._uploaded_item(
                    job,
                    result=result,
                    status="uploaded_thumbnail_failed",
                    thumbnail_status="failed",
                    error_code=self._error_code(exc),
                ),
                False,
            )

        self.store.mark_thumbnail_result(job.id, success=True)
        return (
            self._uploaded_item(job, result=result, status="uploaded", thumbnail_status="success"),
            False,
        )

    def _changed_file_status(self, job: UploadJob) -> str | None:
        try:
            video_hash = self._file_hash(job.path)
        except OSError:
            return "skipped_changed_file"
        if video_hash != job.sha256:
            return "skipped_changed_file"
        try:
            thumbnail_hash = self._file_hash(job.thumbnail_path)
        except OSError:
            return "skipped_changed_thumbnail"
        if thumbnail_hash != job.thumbnail_sha256:
            return "skipped_changed_thumbnail"
        return None

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _video_result_from_job(job: UploadJob) -> VideoUploadResult:
        if not job.video_id:
            raise UploadError("Uploaded job has no YouTube video ID")
        return VideoUploadResult(
            video_id=job.video_id,
            actual_visibility=job.api_fields.get("privacy_status", "unknown"),
            video_url=BatchRunner._video_url(job.video_id) or "",
            confirmed_at=job.api_refreshed_at or NOW_UTC,
        )

    @staticmethod
    def _uploaded_item(
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
            video_url=result.video_url if result else BatchRunner._video_url(video_id),
            actual_visibility=(result.actual_visibility if result else job.api_fields.get("privacy_status", "unknown")),
            thumbnail_status=thumbnail_status or job.thumbnail_status,
            error_code=error_code,
            scheduled_publish_at=job.api_fields.get("publish_at") or job.metadata.publish_at,
        )

    @staticmethod
    def _video_url(video_id: str | None) -> str | None:
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else None

    @staticmethod
    def _error_code(exc: Exception) -> str:
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

    @staticmethod
    def _report(items: list[UploadItemResult], *, stopped_reason: str | None = None) -> BatchReport:
        return BatchReport(
            items=items,
            uploaded_count=sum(item.status.startswith("uploaded") for item in items),
            skipped_count=sum(item.status.startswith("skipped") for item in items),
            failed_count=sum(item.status == "failed" for item in items),
            pending_count=sum(item.status.startswith("pending") for item in items),
            stopped_reason=stopped_reason,
            scheduled_count=sum(item.scheduled_publish_at is not None for item in items),
        )


NOW_UTC = datetime.now(timezone.utc)
