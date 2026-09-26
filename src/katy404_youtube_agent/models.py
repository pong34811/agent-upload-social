"""Shared data models for the local YouTube uploader."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UploadProfile:
    """Owner-approved defaults and declarations for one YouTube channel."""

    channel_alias: str
    client_secrets_path: Path | None = None
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
    privacy_policy_url: str | None = None
    policy_accepted_at: str | None = None
    policy_version_accepted: str | None = None
    approved_pilot_video_id: str | None = None


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
