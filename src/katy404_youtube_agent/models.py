"""Shared data models for the local YouTube uploader."""

from dataclasses import dataclass, field
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
