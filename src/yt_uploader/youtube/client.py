"""Authenticated YouTube Data API client for one owner account."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from google.auth.exceptions import TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..auth import ChannelRef, execute_api_request
from ..jobs.store import JobStore
from ..models import ApiVideoSnapshot, ThumbnailResult, UploadJob, VideoUploadResult
from ..pipeline.schedule import format_publish_at
from .errors import (
    _QUOTA_REASONS,
    QuotaExceeded,
    ThumbnailError,
    UploadError,
    VideoSchedulingError,
    _http_error_reason,
)
from .transport import ResumableTransport, ResumableTransportProtocol, ResumableUploader

_SCHEDULE_CONFIRM_ATTEMPTS = 4
_SCHEDULE_CONFIRM_DELAY_SECONDS = 0.25


class YouTubeApi:
    """Authenticated API access for owned channels, uploads, thumbnails, and refresh."""

    def __init__(
        self,
        credentials: Any,
        store: JobStore | None = None,
        client: Any | None = None,
        transport: ResumableTransportProtocol | None = None,
    ) -> None:
        self.client = client or build("youtube", "v3", credentials=credentials, cache_discovery=False)
        self.store = store
        self._credentials = credentials
        self._transport = transport

    @property
    def transport(self) -> ResumableTransportProtocol:
        # Created on first upload so channel lookups never open an upload session.
        if self._transport is None:
            self._transport = ResumableTransport(self._credentials)
        return self._transport

    def list_owned_channels(self) -> list[ChannelRef]:
        channels: list[ChannelRef] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"part": "id,snippet", "mine": True, "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            response = execute_api_request(self.client.channels().list(**params))
            for item in response.get("items", []):
                snippet = item.get("snippet") or {}
                channel_id = item.get("id")
                display_name = snippet.get("title")
                if not isinstance(channel_id, str) or not isinstance(display_name, str):
                    continue
                custom_url = snippet.get("customUrl")
                handle = custom_url if isinstance(custom_url, str) and custom_url.startswith("@") else None
                channels.append(ChannelRef(channel_id, display_name, handle))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return channels

    def upload_video(self, job: UploadJob, media_path: Path) -> VideoUploadResult:
        if self.store is None:
            raise UploadError("JobStore is required for resumable uploads")
        result = ResumableUploader(self.transport, self.store).upload(job, media_path)
        if job.metadata.publish_at is not None:
            self._confirm_schedule(result.video_id, job.channel_id, job.metadata.publish_at)
            result = replace(result, actual_visibility="private")
        elif result.actual_visibility == "unknown":
            snapshots = self.refresh_videos([result.video_id])
            if snapshots and snapshots[0].privacy_status:
                result = replace(result, actual_visibility=snapshots[0].privacy_status)
        return result

    def reconcile_scheduled_upload(self, job: UploadJob) -> UploadJob:
        """Reconcile an unfinished prior schedule before a new schedule replaces it."""
        if self.store is None:
            raise UploadError("JobStore is required to reconcile scheduled uploads")
        return ResumableUploader(self.transport, self.store).reconcile_scheduled_session(job)

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> ThumbnailResult:
        thumbnail_path = Path(thumbnail_path)
        suffix = thumbnail_path.suffix.casefold()
        mime_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
        media = MediaFileUpload(str(thumbnail_path), mimetype=mime_type, chunksize=-1, resumable=False)
        try:
            execute_api_request(self.client.thumbnails().set(videoId=video_id, media_body=media))
        except HttpError as exc:
            reason = _http_error_reason(exc)
            if reason in _QUOTA_REASONS:
                raise QuotaExceeded("YouTube thumbnail limit was reached; remaining files were left pending", reason=reason) from exc
            status = int(getattr(exc.resp, "status", 0))
            raise ThumbnailError(
                f"YouTube rejected the custom thumbnail ({reason or status})",
                retryable=status in {408, 429, 500, 502, 503, 504},
                error_code=reason or f"http_{status}",
            ) from exc
        except (requests.RequestException, TransportError, TimeoutError) as exc:
            raise ThumbnailError("Custom thumbnail request was interrupted", retryable=True) from exc
        return ThumbnailResult(success=True)

    def schedule_video(self, video_id: str, channel_id: str, publish_at: datetime) -> bool:
        """Schedule a locally managed private video, preserving mutable status values."""
        if not video_id or not channel_id:
            raise ValueError("video_id and channel_id are required")
        if publish_at.tzinfo is None or publish_at.utcoffset() is None:
            raise ValueError("publish_at must include a UTC offset")
        if publish_at <= datetime.now(publish_at.tzinfo):
            raise ValueError("publish_at must be in the future")
        publish_value = format_publish_at(publish_at)
        snapshot = next(iter(self.refresh_videos([video_id])), None)
        if snapshot is None:
            raise VideoSchedulingError(
                "YouTube video is missing or not accessible to this account", "video_not_found"
            )
        if snapshot.channel_id != channel_id:
            raise VideoSchedulingError("YouTube video does not belong to the configured channel", "channel_mismatch")
        if snapshot.privacy_status != "private":
            raise VideoSchedulingError("Only a currently Private video can be scheduled", "not_private")
        if snapshot.publish_at and _same_instant(snapshot.publish_at, publish_value):
            return False

        if publish_at <= datetime.now(publish_at.tzinfo):
            raise VideoSchedulingError(
                "Publish time expired while checking the current video status", "invalid_publish_at"
            )

        status: dict[str, Any] = {
            "privacyStatus": "private",
            "publishAt": publish_value,
        }
        mutable_status = {
            "embeddable": snapshot.embeddable,
            "license": snapshot.license,
            "publicStatsViewable": snapshot.public_stats_viewable,
            "selfDeclaredMadeForKids": snapshot.self_declared_made_for_kids,
            "containsSyntheticMedia": snapshot.contains_synthetic_media,
        }
        status.update({key: value for key, value in mutable_status.items() if value is not None})
        try:
            execute_api_request(
                self.client.videos().update(
                    part="status",
                    body={"id": video_id, "status": status},
                )
            )
        except HttpError as exc:
            reason = _http_error_reason(exc)
            if reason in _QUOTA_REASONS:
                raise QuotaExceeded("YouTube scheduling limit was reached; remaining files were left pending", reason=reason) from exc
            if reason in {"insufficientpermissions", "forbidden", "forbiddenprivacysetting"}:
                raise VideoSchedulingError(
                    "YouTube rejected scheduling; reauthorize with the metadata-edit permission and check channel access",
                    "insufficient_permissions",
                ) from exc
            if reason == "invalidpublishat":
                raise VideoSchedulingError(
                    "YouTube rejected the time; it must be future and the video must be Private and never previously published",
                    "invalid_publish_at",
                ) from exc
            raise VideoSchedulingError(
                f"YouTube rejected scheduling ({reason or 'API error'})", reason or "youtube_api_error"
            ) from exc
        except (requests.RequestException, TransportError, TimeoutError) as exc:
            raise VideoSchedulingError("YouTube scheduling request was interrupted") from exc
        self._confirm_schedule(video_id, channel_id, publish_value)
        return True

    def _confirm_schedule(self, video_id: str, channel_id: str, publish_at: str) -> None:
        """Confirm the persisted schedule before callers record or report success."""
        for attempt in range(_SCHEDULE_CONFIRM_ATTEMPTS):
            try:
                readback = self.refresh_videos([video_id])
                snapshot = next(
                    (video for video in readback if video.video_id == video_id),
                    None,
                )
            except HttpError as exc:
                reason = _http_error_reason(exc)
                if reason in _QUOTA_REASONS:
                    raise QuotaExceeded("YouTube schedule verification limit was reached", reason=reason) from exc
                raise VideoSchedulingError(
                    "Could not confirm the publish time with YouTube; keep the uploaded video ID and retry",
                    "schedule_unconfirmed",
                ) from exc
            except (requests.RequestException, TransportError, TimeoutError) as exc:
                raise VideoSchedulingError(
                    "YouTube schedule verification was interrupted; keep the uploaded video ID and retry",
                    "schedule_unconfirmed",
                ) from exc
            if (
                snapshot is not None
                and snapshot.channel_id == channel_id
                and snapshot.privacy_status == "private"
                and isinstance(snapshot.publish_at, str)
                and _same_instant(snapshot.publish_at, publish_at)
            ):
                return
            eventually_consistent = (
                not readback
                or (
                    snapshot is not None
                    and snapshot.channel_id == channel_id
                    and snapshot.privacy_status == "private"
                    and snapshot.publish_at is None
                )
            )
            if eventually_consistent and attempt + 1 < _SCHEDULE_CONFIRM_ATTEMPTS:
                time.sleep(_SCHEDULE_CONFIRM_DELAY_SECONDS)
                continue
            raise VideoSchedulingError(
                "YouTube has not confirmed the requested publish time; keep the uploaded video ID and retry",
                "schedule_unconfirmed",
            )

    def get_processing_status(self, video_id: str) -> str | None:
        """Return YouTube's processing status without exposing its API payload."""
        try:
            response = execute_api_request(
                self.client.videos().list(
                    part="processingDetails", id=video_id, maxResults=1
                )
            )
        except HttpError as exc:
            reason = _http_error_reason(exc)
            status = int(getattr(exc.resp, "status", 0))
            if reason in _QUOTA_REASONS or status == 429:
                raise QuotaExceeded("YouTube API quota was reached while checking video processing") from exc
            raise ThumbnailError(
                f"Could not check YouTube video processing ({reason or status})",
                retryable=status in {408, 429, 500, 502, 503, 504},
                error_code=reason or f"http_{status}",
            ) from exc
        except (requests.RequestException, TransportError, TimeoutError) as exc:
            raise ThumbnailError(
                "Could not check YouTube video processing",
                retryable=True,
                error_code="processing_transport",
            ) from exc
        items = response.get("items", [])
        if not items:
            return None
        details = items[0].get("processingDetails") or {}
        value = details.get("processingStatus")
        return value if isinstance(value, str) else None

    def refresh_videos(self, video_ids: list[str]) -> list[ApiVideoSnapshot]:
        snapshots: list[ApiVideoSnapshot] = []
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            if not batch:
                continue
            response = execute_api_request(
                self.client.videos().list(part="id,snippet,status", id=",".join(batch), maxResults=50)
            )
            for item in response.get("items", []):
                snippet = item.get("snippet") or {}
                status = item.get("status") or {}
                thumbs = snippet.get("thumbnails") or {}
                thumb = next(
                    (thumbs[key].get("url") for key in ("maxres", "standard", "high", "medium", "default")
                     if isinstance(thumbs.get(key), dict) and thumbs[key].get("url")),
                    None,
                )
                snapshots.append(
                    ApiVideoSnapshot(
                        video_id=item["id"],
                        title=snippet.get("title"),
                        description=snippet.get("description"),
                        privacy_status=status.get("privacyStatus"),
                        thumbnail_url=thumb,
                        published_at=snippet.get("publishedAt"),
                        channel_id=snippet.get("channelId"),
                        publish_at=status.get("publishAt"),
                        embeddable=status.get("embeddable"),
                        license=status.get("license"),
                        public_stats_viewable=status.get("publicStatsViewable"),
                        self_declared_made_for_kids=status.get("selfDeclaredMadeForKids"),
                        contains_synthetic_media=status.get("containsSyntheticMedia"),
                    )
                )
        return snapshots



def _same_instant(left: str, right: str) -> bool:
    try:
        left_value = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_value = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return False
    if left_value.tzinfo is None or right_value.tzinfo is None:
        return False
    return left_value.astimezone(timezone.utc) == right_value.astimezone(timezone.utc)
