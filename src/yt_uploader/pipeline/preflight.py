"""Local preflight: scan the selected folder, build metadata, and prepare job records."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..auth import ChannelRef, ChannelResolutionError
from ..config.profile import ProfileError, validate_upload_profile
from ..jobs.store import JobStateError
from ..media import MediaProbeError, MetadataError, build_metadata, scan_folder
from ..models import (
    BatchReport,
    MediaCandidate,
    MediaFacts,
    ScanIssue,
    UploadItemResult,
    UploadJob,
    UploadProfile,
    VideoMetadata,
)
from .results import build_report, changed_file_status, error_code
from .schedule import format_publish_at, plan_daily_pairs


@dataclass(slots=True)
class PreparedBatch:
    channel: ChannelRef
    jobs: list[UploadJob]
    report_items: list[UploadItemResult]
    effective_privacy: str
    scheduled_times: dict[str, datetime] | None = None
    schedule_plan: dict[Path, datetime] | None = field(default=None, repr=False)


def select_file(
    folder: Path,
    candidates: list[MediaCandidate],
    issues: list[ScanIssue],
    file_name: str | None,
) -> tuple[list[MediaCandidate], list[ScanIssue]]:
    """Narrow a scan to one top-level filename; never accept a path."""
    if file_name is None:
        return candidates, issues
    selected_name = Path(file_name).name
    if not file_name or selected_name != file_name or file_name in {".", ".."}:
        raise ValueError("--file must be a filename in the selected folder, not a path")

    selected_key = selected_name.casefold()
    selected_stem = Path(selected_name).stem.casefold()
    matching_candidates = [item for item in candidates if item.path.name.casefold() == selected_key]
    matching_issues = [
        item
        for item in issues
        if item.path.name.casefold() == selected_key or item.path.stem.casefold() == selected_stem
    ]
    if not matching_candidates and not matching_issues:
        matching_issues = [
            ScanIssue(
                path=Path(folder) / selected_name,
                code="file_not_found",
                message="The selected filename was not found in the selected folder",
            )
        ]
    return matching_candidates, matching_issues


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


class PreflightMixin:
    """Preflight steps shared by ``dry-run``, ``upload``, and failed-job retry.

    Expects ``profile``, ``store``, ``api``, ``probe``, and ``_resolve_owned_channel``
    on the concrete runner.
    """

    profile: UploadProfile
    store: Any
    api: Any
    probe: Callable[[Path], MediaFacts]

    def dry_run(
        self,
        folder: Path,
        requested_channel: str,
        *,
        file_name: str | None = None,
    ) -> BatchReport:
        """Inspect a folder locally without resolving OAuth or making API calls."""
        if not requested_channel or not requested_channel.strip():
            raise ChannelResolutionError("A channel ID, handle, or name is required")
        candidates, issues = scan_folder(Path(folder))
        candidates, issues = select_file(folder, candidates, issues, file_name)
        items = [
            UploadItemResult(status="failed", source_path=issue.path, error_code=issue.code)
            for issue in issues
        ]
        for candidate in candidates:
            try:
                facts = self.probe(candidate.path)
                metadata = build_metadata(candidate, facts, self.profile)
            except (MediaProbeError, MetadataError, ProfileError) as exc:
                items.append(
                    UploadItemResult(status="failed", source_path=candidate.path, error_code=error_code(exc))
                )
            else:
                items.append(UploadItemResult(status="ready", source_path=candidate.path, title=metadata.title))
        return build_report(items)

    def requeue_failed(self, path: Path, channel_id: str) -> UploadJob:
        """Requeue one explicitly named failed file after verifying both paired assets."""
        if not channel_id or not channel_id.strip():
            raise JobStateError("A verified channel ID is required to requeue a failed upload")
        if self.profile.channel_id != channel_id:
            raise JobStateError("Requested channel does not match the channel saved in this profile")
        target = _path_key(Path(path))
        matching = [job for job in self.store.list_jobs(channel_id) if _path_key(job.path) == target]
        if len(matching) != 1:
            raise JobStateError("No unique saved upload job matches the requested file path")
        job = matching[0]
        if job.state != "failed":
            raise JobStateError(f"Only failed uploads can be requeued; current state is {job.state}")
        changed = changed_file_status(job)
        if changed is not None:
            raise JobStateError(f"Cannot retry because the source or paired thumbnail changed ({changed})")
        validate_upload_profile(self.profile, requested_privacy=self.profile.privacy_status)
        candidate = MediaCandidate(
            path=job.path,
            thumbnail_path=job.thumbnail_path,
            sha256=job.sha256,
            thumbnail_sha256=job.thumbnail_sha256,
            size_bytes=job.size_bytes,
            thumbnail_size_bytes=job.thumbnail_path.stat().st_size,
            modified_ns=job.modified_ns,
        )
        metadata = build_metadata(candidate, self.probe(job.path), self.profile)
        self.store.requeue_failed(job.id, metadata)
        return self.store.get_job(job.id)

    def prepare_upload(
        self,
        folder: Path,
        requested_channel: str,
        *,
        limit: int | None = None,
        force_private: bool = False,
        file_name: str | None = None,
        schedule_from: datetime | None = None,
    ) -> PreparedBatch:
        """Validate the request, verify channel ownership, and create or refresh job records."""
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
        candidates, issues = select_file(folder, candidates, issues, file_name)
        report_items = [
            UploadItemResult(status="failed", source_path=issue.path, error_code=issue.code)
            for issue in issues
        ]
        if scheduled_mode and issues:
            raise ProfileError("Scheduled batches require every selected video and thumbnail to pass preflight")

        prepared = self._build_prepared(candidates, report_items, limit, force_private, scheduled_mode)
        if not scheduled_mode:
            jobs = [self._queue_unscheduled(candidate, channel, metadata) for candidate, _, metadata in prepared]
            return PreparedBatch(channel, jobs, report_items, effective_privacy)

        assert schedule_from is not None
        schedule_plan = plan_daily_pairs(
            [(candidate, facts) for candidate, facts, _ in prepared],
            schedule_from,
            allow_past=True,
        )
        jobs, scheduled_times = self._queue_scheduled(prepared, channel, schedule_plan, schedule_from)
        return PreparedBatch(channel, jobs, report_items, effective_privacy, scheduled_times, schedule_plan)

    def _build_prepared(
        self,
        candidates: list[MediaCandidate],
        report_items: list[UploadItemResult],
        limit: int | None,
        force_private: bool,
        scheduled_mode: bool,
    ) -> list[tuple[MediaCandidate, MediaFacts, VideoMetadata]]:
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
                    UploadItemResult(status="failed", source_path=candidate.path, error_code=error_code(exc))
                )
                if scheduled_mode:
                    raise ProfileError("Scheduled batches require every video to pass preflight") from exc
        return prepared

    def _queue_unscheduled(self, candidate: MediaCandidate, channel: ChannelRef, metadata: VideoMetadata) -> UploadJob:
        job = self.store.get_or_create_job(candidate, channel.channel_id, metadata)
        if job.state in {"discovered", "validated"} and (
            job.metadata.title != metadata.title or job.metadata.description != metadata.description
        ):
            # Refresh derived display text for queued jobs before creating a
            # YouTube upload session (for example, remove the `_9x16` marker).
            self.store.update_preupload_metadata(
                job.id,
                replace(job.metadata, title=metadata.title, description=metadata.description),
            )
            job = self.store.get_job(job.id)
        return job

    def _queue_scheduled(
        self,
        prepared: list[tuple[MediaCandidate, MediaFacts, VideoMetadata]],
        channel: ChannelRef,
        schedule_plan: dict[Path, datetime],
        schedule_from: datetime,
    ) -> tuple[list[UploadJob], dict[str, datetime]]:
        existing_by_path = {_path_key(job.path): job for job in self.store.list_jobs(channel.channel_id)}
        now = datetime.now(schedule_from.tzinfo)
        for candidate, _, _ in prepared:
            scheduled_at = schedule_plan[candidate.path]
            existing = existing_by_path.get(_path_key(candidate.path))
            if existing is not None and existing.state == "complete":
                if existing.metadata.publish_at != format_publish_at(scheduled_at):
                    raise ProfileError("Scheduled preflight would change an already completed video's publish time")
            elif scheduled_at <= now:
                raise ProfileError("Scheduled preflight found a past publish time for a video that is not complete")

        jobs: list[UploadJob] = []
        scheduled_times: dict[str, datetime] = {}
        scheduled_job_ids: set[str] = set()
        scheduled_updates: list[tuple[UploadJob, VideoMetadata]] = []
        for candidate, _, metadata in prepared:
            scheduled_at = schedule_plan[candidate.path]
            metadata = replace(metadata, publish_at=format_publish_at(scheduled_at))
            job = self.store.get_or_create_job(candidate, channel.channel_id, metadata)
            changed = changed_file_status(job)
            if changed is not None:
                raise ProfileError(f"Scheduled preflight found a changed source or thumbnail ({changed})")
            if job.state in {"failed", "skipped"}:
                raise ProfileError("Scheduled batches cannot contain failed or skipped local jobs")
            if job.id in scheduled_job_ids:
                raise ProfileError("Scheduled preflight found duplicate video content assigned to multiple daily slots")
            scheduled_job_ids.add(job.id)
            if job.state == "uploading" and (
                job.metadata.publish_at != metadata.publish_at or job.metadata.privacy_status != "private"
            ):
                job = self._reconcile_scheduled_session(job)
            if job.state != "complete":
                scheduled_times[job.id] = scheduled_at
                scheduled_updates.append((job, metadata))
            jobs.append(job)

        # Defer all existing-job schedule changes until duplicate identities and
        # incompatible resumable sessions have been checked for the whole batch.
        for job, metadata in scheduled_updates:
            if job.state in {"discovered", "validated"} and job.metadata != metadata:
                self.store.update_preupload_metadata(job.id, metadata)
        return [self.store.get_job(job.id) for job in jobs], scheduled_times

    def _reconcile_scheduled_session(self, job: UploadJob) -> UploadJob:
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
                "YouTube received all video bytes but has not confirmed completion; "
                "keep the session and retry status reconciliation"
            )
        return job

    def _resolve_owned_channel(self, requested_channel: str) -> ChannelRef:  # pragma: no cover - runner overrides
        raise NotImplementedError
