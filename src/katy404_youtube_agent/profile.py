"""Persistence and validation for the owner's local upload profile."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from .models import UploadProfile

_ALLOWED_PRIVACY = {"private", "unlisted", "public"}


class ProfileError(ValueError):
    """Raised when profile data is missing or cannot safely authorize an upload."""


def _profile_path_default() -> Path:
    return Path(__file__).resolve().parents[2] / "profile.json"


def load_profile(path: Path) -> UploadProfile:
    """Read a JSON profile without silently accepting misspelled fields."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"Upload profile was not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"Could not read upload profile: {path}") from exc

    if not isinstance(data, dict):
        raise ProfileError("Upload profile must be a JSON object")
    if not isinstance(data.get("channel_alias"), str) or not data["channel_alias"].strip():
        raise ProfileError("channel_alias is required")

    allowed_fields = {item.name for item in fields(UploadProfile)}
    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        raise ProfileError(f"Unknown profile field: {sorted(unknown_fields)[0]}")

    secrets_path = data.get("client_secrets_path")
    if secrets_path is not None and not isinstance(secrets_path, str):
        raise ProfileError("client_secrets_path must be a path string")
    if secrets_path:
        data["client_secrets_path"] = Path(secrets_path)
    pilot_rights_video_id = data.get("pilot_asset_rights_confirmed_video_id")
    if pilot_rights_video_id is not None and (
        not isinstance(pilot_rights_video_id, str) or not pilot_rights_video_id.strip()
    ):
        raise ProfileError("pilot_asset_rights_confirmed_video_id must be a non-empty string")
    tags = data.get("tags", ())
    if not isinstance(tags, (list, tuple)) or not all(isinstance(tag, str) for tag in tags):
        raise ProfileError("tags must be a list of strings")
    data["tags"] = tuple(tags)

    try:
        return UploadProfile(**data)
    except TypeError as exc:
        raise ProfileError("Upload profile has invalid or missing fields") from exc


def save_profile(path: Path, profile: UploadProfile) -> None:
    """Atomically save a profile to the requested path."""
    if not isinstance(profile, UploadProfile):
        raise TypeError("profile must be an UploadProfile")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(profile)
    payload["client_secrets_path"] = (
        str(profile.client_secrets_path) if profile.client_secrets_path is not None else None
    )
    payload["tags"] = list(profile.tags)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as temporary_file:
            temporary_file.write(encoded)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class ProfileStore:
    """Profile storage backed by the project root by default."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _profile_path_default()

    def load(self) -> UploadProfile:
        return load_profile(self.path)

    def save(self, profile: UploadProfile) -> None:
        save_profile(self.path, profile)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field_name} is required")
    return value.strip()


def validate_upload_profile(
    profile: UploadProfile,
    *,
    requested_privacy: str,
    asset_rights_confirmed: bool | None = None,
) -> None:
    """Fail closed unless required owner settings and visibility gates are met."""
    if not isinstance(profile, UploadProfile):
        raise ProfileError("A valid upload profile is required")

    _require_text(profile.channel_alias, "channel_alias")
    privacy_status = requested_privacy.casefold() if isinstance(requested_privacy, str) else ""
    saved_privacy = profile.privacy_status.casefold() if isinstance(profile.privacy_status, str) else ""
    if privacy_status not in _ALLOWED_PRIVACY or saved_privacy not in _ALLOWED_PRIVACY:
        raise ProfileError("privacy_status must be private, unlisted, or public")

    if privacy_status != "private" and not profile.api_audit_passed:
        raise ProfileError("Unlisted/Public publishing requires a completed YouTube API compliance audit")
    if not isinstance(profile.api_audit_passed, bool):
        raise ProfileError("api_audit_passed must be a boolean")

    if not isinstance(profile.made_for_kids, bool):
        raise ProfileError("made_for_kids must be declared true or false")
    if not isinstance(profile.contains_synthetic_media, bool):
        raise ProfileError("contains_synthetic_media must be declared true or false")
    if not isinstance(profile.is_official_artist_channel, bool):
        raise ProfileError("is_official_artist_channel must be declared true or false")
    rights_confirmed = profile.asset_rights_confirmed if asset_rights_confirmed is None else asset_rights_confirmed
    if rights_confirmed is not True:
        raise ProfileError(
            "Confirm rights to the video's audio, visuals, game footage, and overlays"
        )
    _require_text(profile.category_id, "category_id")
    _require_text(profile.description_template, "description_template")
    if not isinstance(profile.tags, tuple) or not all(isinstance(tag, str) for tag in profile.tags):
        raise ProfileError("tags must be a tuple of strings")

    if profile.client_secrets_path is None:
        raise ProfileError("client_secrets_path is required")
    secrets_path = Path(profile.client_secrets_path)
    try:
        oauth_data = json.loads(secrets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError("Could not read Desktop OAuth client file") from exc
    installed = oauth_data.get("installed") if isinstance(oauth_data, dict) else None
    if not isinstance(installed, dict):
        raise ProfileError("Desktop OAuth client must use the installed-app format")
