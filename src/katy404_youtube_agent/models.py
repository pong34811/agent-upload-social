"""Shared data models for the local YouTube uploader."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UploadProfile:
    """Owner-approved defaults and declarations for one YouTube channel."""

    channel_alias: str
    client_secrets_path: Path | None = None
    oauth_account_key: str = "owner"
    channel_id: str | None = None
    privacy_status: str = "private"
    api_audit_passed: bool = False
    category_id: str | None = None
    description_template: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None
    is_official_artist_channel: bool = False
    shorts_title_suffix: str = " #Shorts"


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    path: Path
    thumbnail_path: Path
    sha256: str
    thumbnail_sha256: str
    size_bytes: int
    thumbnail_size_bytes: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class ScanIssue:
    path: Path
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MediaFacts:
    duration_seconds: float
    width: int
    height: int
    video_codec: str = ""


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    title: str
    description: str
    tags: tuple[str, ...]
    category_id: str
    privacy_status: str
    made_for_kids: bool
    contains_synthetic_media: bool
    short_candidate: bool
    publish_at: str | None = None


@dataclass(frozen=True, slots=True)
class UploadJob:
    id: str
    path: Path
    sha256: str
    size_bytes: int
    modified_ns: int
    thumbnail_path: Path
    thumbnail_sha256: str
    channel_id: str
    metadata: VideoMetadata
    state: str
    session_uri: str | None
    offset: int
    video_id: str | None
    thumbnail_status: str
    api_refreshed_at: datetime | None = field(default=None, compare=False)
    api_fields: dict[str, str] = field(default_factory=dict, compare=False)
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class VideoUploadResult:
    video_id: str
    actual_visibility: str
    video_url: str
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class UploadChunkResult:
    next_offset: int | None = None
    result: VideoUploadResult | None = None


@dataclass(frozen=True, slots=True)
class ThumbnailResult:
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ApiVideoSnapshot:
    video_id: str
    title: str | None
    description: str | None
    privacy_status: str | None
    thumbnail_url: str | None
    published_at: str | None
    channel_id: str | None = None
    publish_at: str | None = None
    embeddable: bool | None = None
    license: str | None = None
    public_stats_viewable: bool | None = None
    self_declared_made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None


@dataclass(frozen=True, slots=True)
class UploadItemResult:
    status: str
    source_path: Path
    video_id: str | None = None
    video_url: str | None = None
    actual_visibility: str | None = None
    thumbnail_status: str | None = None
    error_code: str | None = None
    scheduled_publish_at: str | None = None


@dataclass(frozen=True, slots=True)
class BatchReport:
    items: list[UploadItemResult]
    uploaded_count: int
    skipped_count: int
    failed_count: int
    pending_count: int
    stopped_reason: str | None = None
    scheduled_count: int = 0
