"""YouTube resumable upload protocol and the session-persisting uploader."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse

import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession

from ..auth import AuthorizationRevokedError
from ..jobs.store import JobStateError, JobStore
from ..models import UploadChunkResult, UploadJob, VideoUploadResult
from ..pipeline.schedule import parse_publish_at
from .errors import (
    _QUOTA_REASONS,
    QuotaExceeded,
    RetryableUploadError,
    ScheduledPublishTimeExpired,
    UploadCompletionPending,
    UploadError,
    UploadSessionExpired,
)

UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_MIN_CHUNK_BYTES = 256 * 1024
_MAX_RETRIES = 5
_MAX_BACKOFF_SECONDS = 8.0


class ResumableTransportProtocol(Protocol):
    def begin_upload(self, job: UploadJob, media_path: Path) -> str: ...
    def query_session(self, session_uri: str, total_bytes: int) -> int | VideoUploadResult: ...
    def upload_chunk(
        self, session_uri: str, start: int, chunk: bytes, total_bytes: int
    ) -> UploadChunkResult: ...


class ResumableTransport:
    """HTTP implementation of YouTube's resumable upload protocol."""

    def __init__(
        self,
        credentials: Any,
        session: Any | None = None,
        *,
        chunk_size: int = UPLOAD_CHUNK_BYTES,
    ) -> None:
        if chunk_size <= 0 or chunk_size % _MIN_CHUNK_BYTES:
            raise ValueError("chunk_size must be a positive multiple of 256 KiB")
        self.session = session or AuthorizedSession(credentials)
        self.chunk_size = chunk_size

    def begin_upload(self, job: UploadJob, media_path: Path) -> str:
        media_path = Path(media_path)
        total_bytes = media_path.stat().st_size
        if total_bytes <= 0:
            raise UploadError("Video file is empty")
        metadata = job.metadata
        status = {
            "privacyStatus": metadata.privacy_status,
            "selfDeclaredMadeForKids": metadata.made_for_kids,
            "containsSyntheticMedia": metadata.contains_synthetic_media,
        }
        if metadata.publish_at is not None:
            if metadata.privacy_status != "private":
                raise UploadError("A scheduled upload must remain private until its publish time")
            try:
                parse_publish_at(metadata.publish_at)
            except ValueError as exc:
                raise ScheduledPublishTimeExpired("Scheduled publish time expired before upload could start") from exc
            status["publishAt"] = metadata.publish_at
        body = {
            "snippet": {
                "title": metadata.title,
                "description": metadata.description,
                "tags": list(metadata.tags),
                "categoryId": metadata.category_id,
            },
            "status": status,
        }
        query = urlencode({"uploadType": "resumable", "part": "snippet,status"})
        url = f"https://www.googleapis.com/upload/youtube/v3/videos?{query}"
        response = self._request(
            "POST",
            url,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(total_bytes),
            },
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            allow_redirects=False,
        )
        if response.status_code not in {200, 201}:
            self._raise_response_error(response)
        session_uri = response.headers.get("Location")
        if not isinstance(session_uri, str) or urlparse(session_uri).scheme != "https":
            raise UploadError("YouTube did not return a secure resumable session URL")
        return session_uri

    def query_session(self, session_uri: str, total_bytes: int) -> int | VideoUploadResult:
        response = self._request(
            "PUT",
            session_uri,
            headers={"Content-Length": "0", "Content-Range": f"bytes */{total_bytes}"},
            data=b"",
            allow_redirects=False,
        )
        if response.status_code == 308:
            return self._confirmed_offset(response.headers.get("Range"))
        if response.status_code in {200, 201}:
            return self._video_result(self._response_json(response))
        if response.status_code == 404:
            raise UploadSessionExpired("YouTube resumable session expired")
        self._raise_response_error(response)
        raise AssertionError("unreachable")

    def upload_chunk(
        self, session_uri: str, start: int, chunk: bytes, total_bytes: int
    ) -> UploadChunkResult:
        if not chunk or start < 0 or start + len(chunk) > total_bytes:
            raise ValueError("chunk range is outside the video file")
        end = start + len(chunk) - 1
        response = self._request(
            "PUT",
            session_uri,
            headers={
                "Content-Length": str(len(chunk)),
                "Content-Type": "video/*",
                "Content-Range": f"bytes {start}-{end}/{total_bytes}",
            },
            data=chunk,
            allow_redirects=False,
        )
        if response.status_code == 308:
            return UploadChunkResult(next_offset=self._confirmed_offset(response.headers.get("Range")))
        if response.status_code in {200, 201}:
            return UploadChunkResult(result=self._video_result(self._response_json(response)))
        if response.status_code == 404:
            raise UploadSessionExpired("YouTube resumable session expired")
        self._raise_response_error(response)
        raise AssertionError("unreachable")

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            return self.session.request(method, url, timeout=(30, 300), **kwargs)
        except RefreshError as exc:
            if "invalid_grant" in str(exc).casefold():
                raise AuthorizationRevokedError(
                    "Google authorization was revoked or expired; authorize the owner account again"
                ) from exc
            raise
        except (requests.RequestException, TransportError, TimeoutError, OSError) as exc:
            raise RetryableUploadError("YouTube upload transport was interrupted") from exc

    @staticmethod
    def _confirmed_offset(range_header: str | None) -> int:
        if not range_header:
            return 0
        match = re.fullmatch(r"bytes=0-(\d+)", range_header.strip())
        if not match:
            raise UploadError("YouTube returned an invalid upload Range header")
        return int(match.group(1)) + 1

    @staticmethod
    def _response_json(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, AttributeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _raise_response_error(cls, response: Any) -> None:
        payload = cls._response_json(response)
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        reasons = [
            str(item.get("reason", "")).casefold()
            for item in error.get("errors", [])
            if isinstance(item, dict)
        ]
        quota_reason = next((reason for reason in reasons if reason in _QUOTA_REASONS), None)
        if quota_reason:
            raise QuotaExceeded("YouTube upload limit was reached; remaining files were left pending", reason=quota_reason)
        status = int(response.status_code)
        if status in {408, 429, 500, 502, 503, 504}:
            retry_after = response.headers.get("Retry-After")
            try:
                seconds = min(float(retry_after), _MAX_BACKOFF_SECONDS) if retry_after else None
            except (TypeError, ValueError):
                seconds = None
            raise RetryableUploadError(f"Temporary YouTube API error ({status})", seconds)
        message = error.get("message")
        raise UploadError(str(message or f"YouTube API request failed ({status})"))

    @staticmethod
    def _video_result(payload: dict[str, Any]) -> VideoUploadResult:
        video_id = payload.get("id")
        if not isinstance(video_id, str) or not video_id:
            raise UploadError("YouTube completed an upload without returning a video ID")
        status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        visibility = status.get("privacyStatus")
        if visibility not in {"private", "unlisted", "public"}:
            visibility = "unknown"
        return VideoUploadResult(
            video_id=video_id,
            actual_visibility=visibility,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
            confirmed_at=datetime.now(timezone.utc),
        )



class ResumableUploader:
    """Resume the exact stored session and persist every YouTube-confirmed offset."""

    def __init__(
        self,
        transport: ResumableTransportProtocol,
        store: JobStore,
        *,
        chunk_size: int = UPLOAD_CHUNK_BYTES,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if chunk_size <= 0 or chunk_size % _MIN_CHUNK_BYTES:
            raise ValueError("chunk_size must be a positive multiple of 256 KiB")
        self.transport = transport
        self.store = store
        self.chunk_size = chunk_size
        self.sleep = sleep
        self.max_retries = max_retries

    def _retry_call(self, operation: Callable[[], Any]) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except (QuotaExceeded, UploadSessionExpired):
                raise
            except RetryableUploadError as exc:
                if attempt >= self.max_retries:
                    raise
                wait = exc.retry_after or min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS)
                self.sleep(min(wait, _MAX_BACKOFF_SECONDS))
        raise AssertionError("unreachable")

    def _start_session(self, job: UploadJob, media_path: Path) -> str:
        session_uri = self._retry_call(
            lambda: (self._ensure_future_publish_time(job), self.transport.begin_upload(job, media_path))[1]
        )
        self.store.set_upload_session(job.id, session_uri, 0)
        return session_uri

    def _query(self, session_uri: str, total_bytes: int) -> int | VideoUploadResult:
        # A status query is safe after the deadline and may recover a video ID
        # whose final upload response was lost. The byte-send path checks time.
        result = self._retry_call(lambda: self.transport.query_session(session_uri, total_bytes))
        if isinstance(result, VideoUploadResult):
            return result
        if not isinstance(result, int) or result < 0 or result > total_bytes:
            raise UploadError("YouTube returned an invalid resumable upload offset")
        return result

    def _finish(self, job_id: str, result: VideoUploadResult) -> VideoUploadResult:
        self.store.mark_video_uploaded(job_id, result.video_id, result.confirmed_at)
        return result

    def reconcile_scheduled_session(self, job: UploadJob) -> UploadJob:
        """Check an old schedule session before replacing its publish time.

        A completed remote session is recorded locally. An incomplete or expired
        session is retired so a new explicit schedule can start from byte zero.
        The opaque session URI is never returned or logged.
        """
        current = self.store.get_job(job.id)
        if current.state != "uploading" or not current.session_uri or current.metadata.publish_at is None:
            raise UploadError("Scheduled upload has no resumable session to reconcile")
        try:
            outcome = self._retry_call(
                lambda: self.transport.query_session(current.session_uri, current.size_bytes)
            )
        except UploadSessionExpired:
            self.store.retire_upload_session(current.id)
            return self.store.get_job(current.id)
        if isinstance(outcome, VideoUploadResult):
            self.store.mark_video_uploaded(current.id, outcome.video_id, outcome.confirmed_at)
            return self.store.get_job(current.id)
        if not isinstance(outcome, int) or outcome < 0 or outcome > current.size_bytes:
            raise UploadError("YouTube returned an invalid resumable upload offset")
        if outcome == current.size_bytes:
            # Every byte may have arrived while YouTube is still finalizing the
            # video. Keep this session so a later status query can recover its ID.
            self.store.set_upload_session(current.id, current.session_uri, outcome)
            return self.store.get_job(current.id)
        self.store.retire_upload_session(current.id)
        return self.store.get_job(current.id)

    @staticmethod
    def _ensure_future_publish_time(job: UploadJob) -> None:
        if job.metadata.publish_at is None:
            return
        try:
            parse_publish_at(job.metadata.publish_at)
        except ValueError as exc:
            raise ScheduledPublishTimeExpired(
                "Scheduled publish time expired; upload was stopped before sending more data"
            ) from exc

    def upload(self, job: UploadJob, media_path: Path) -> VideoUploadResult:
        media_path = Path(media_path)
        job = self.store.get_job(job.id)
        if job.state in {"uploaded", "complete"}:
            if not job.video_id:
                raise UploadError("Uploaded job has no recorded video ID")
            return VideoUploadResult(
                video_id=job.video_id,
                actual_visibility=job.api_fields.get("privacy_status", "unknown"),
                video_url=f"https://www.youtube.com/watch?v={job.video_id}",
                confirmed_at=job.api_refreshed_at or datetime.now(timezone.utc),
            )
        if job.state in {"failed", "skipped"}:
            raise JobStateError(f"Cannot upload a terminal job in state {job.state}")
        if job.state == "discovered":
            self.store.mark_validated(job.id)
            job = self.store.get_job(job.id)
        try:
            total_bytes = media_path.stat().st_size
        except OSError as exc:
            raise UploadError("Video file is not readable") from exc
        if total_bytes <= 0:
            raise UploadError("Video file is empty")
        if total_bytes != job.size_bytes:
            raise UploadError("Video file size changed after preparation")

        session_uri = job.session_uri
        if session_uri:
            try:
                response = self._query(session_uri, total_bytes)
            except UploadSessionExpired:
                session_uri = self._start_session(job, media_path)
                offset = 0
            else:
                if isinstance(response, VideoUploadResult):
                    return self._finish(job.id, response)
                offset = response
                self.store.set_upload_session(job.id, session_uri, offset)
        else:
            session_uri = self._start_session(job, media_path)
            offset = 0

        restarts = 0
        no_progress = 0
        retries_at_offset = 0
        while offset < total_bytes:
            self._ensure_future_publish_time(job)
            with media_path.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read(min(self.chunk_size, total_bytes - offset))
            if not chunk:
                raise UploadError("Video file ended before the upload was complete")
            try:
                outcome = self.transport.upload_chunk(
                    session_uri=session_uri,
                    start=offset,
                    chunk=chunk,
                    total_bytes=total_bytes,
                )
            except UploadSessionExpired:
                if restarts >= 2:
                    raise UploadError("YouTube repeatedly expired the upload session")
                restarts += 1
                session_uri = self._start_session(job, media_path)
                offset = 0
                continue
            except RetryableUploadError as exc:
                try:
                    confirmed = self._query(session_uri, total_bytes)
                except UploadSessionExpired:
                    if restarts >= 2:
                        raise UploadError("YouTube repeatedly expired the upload session")
                    restarts += 1
                    session_uri = self._start_session(job, media_path)
                    offset = 0
                    continue
                if isinstance(confirmed, VideoUploadResult):
                    return self._finish(job.id, confirmed)
                if confirmed == offset:
                    if retries_at_offset >= self.max_retries:
                        raise
                    wait = exc.retry_after or min(0.5 * (2**retries_at_offset), _MAX_BACKOFF_SECONDS)
                    self.sleep(min(wait, _MAX_BACKOFF_SECONDS))
                    retries_at_offset += 1
                else:
                    retries_at_offset = 0
                offset = confirmed
                self.store.set_upload_session(job.id, session_uri, offset)
                continue
            if outcome.result is not None:
                return self._finish(job.id, outcome.result)
            self._ensure_future_publish_time(job)
            if outcome.next_offset is None or outcome.next_offset < offset or outcome.next_offset > total_bytes:
                raise UploadError("YouTube returned an invalid next upload offset")
            if outcome.next_offset == offset:
                no_progress += 1
                if no_progress > self.max_retries:
                    raise RetryableUploadError("YouTube made no progress on the upload")
                confirmed = self._query(session_uri, total_bytes)
                if isinstance(confirmed, VideoUploadResult):
                    return self._finish(job.id, confirmed)
                if confirmed != offset:
                    retries_at_offset = 0
                offset = confirmed
            else:
                no_progress = 0
                retries_at_offset = 0
                offset = outcome.next_offset
            self.store.set_upload_session(job.id, session_uri, offset)

        completed = self._query(session_uri, total_bytes)
        if isinstance(completed, VideoUploadResult):
            return self._finish(job.id, completed)
        raise UploadCompletionPending("YouTube received all bytes but has not confirmed video completion yet")
