"""Persistence and validation for the owner's local upload profile."""

from __future__ import annotations

import json
import re
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


_PROFILE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def saved_profile_paths(root: Path) -> list[tuple[str, Path]]:
    """Return valid named profile files under ``root/profiles`` in stable order."""
    directory = Path(root) / "profiles"
    if not directory.is_dir():
        return []
    profiles = [
        (path.stem.casefold(), path)
        for path in directory.glob("*.json")
        if path.is_file() and _PROFILE_KEY.fullmatch(path.stem.casefold())
    ]
    return sorted(profiles, key=lambda item: item[0])


def selectable_profile_paths(root: Path) -> list[tuple[str, Path]]:
    """List named profiles plus a distinct legacy profile, if one is still present."""
    root = Path(root)
    profiles = saved_profile_paths(root)
    legacy_path = root / "profile.json"
    if not legacy_path.is_file():
        return profiles
    try:
        legacy_profile = load_profile(legacy_path)
    except ProfileError:
        return profiles

    for _, path in profiles:
        try:
            candidate = load_profile(path)
        except ProfileError:
            continue
        same_channel = (
            legacy_profile.channel_id is not None
            and legacy_profile.channel_id == candidate.channel_id
        )
        same_legacy_identity = (
            isinstance(legacy_profile.oauth_account_key, str)
            and isinstance(candidate.oauth_account_key, str)
            and legacy_profile.oauth_account_key.casefold() == candidate.oauth_account_key.casefold()
            and legacy_profile.channel_alias.casefold() == candidate.channel_alias.casefold()
            and (
                legacy_profile.channel_id is None
                or candidate.channel_id is None
                or legacy_profile.channel_id == candidate.channel_id
            )
        )
        if same_channel or same_legacy_identity:
            return profiles

    preferred_key = (
        legacy_profile.oauth_account_key.casefold()
        if isinstance(legacy_profile.oauth_account_key, str)
        else "legacy"
    )
    key = preferred_key if _PROFILE_KEY.fullmatch(preferred_key) else "legacy"
    occupied = {name for name, _ in profiles}
    if key in occupied:
        key = "legacy"
        while key in occupied:
            key += "_legacy"
    return sorted([*profiles, (key, legacy_path)], key=lambda item: item[0])


def resolve_profile_path(
    root: Path,
    profile_name: str | None,
    *,
    for_setup: bool = False,
) -> Path:
    """Resolve an explicit named profile, or a safe legacy/single-profile default."""
    root = Path(root)
    named_profiles = saved_profile_paths(root)
    profiles = selectable_profile_paths(root)
    if profile_name is not None:
        key = profile_name.strip().casefold()
        if not _PROFILE_KEY.fullmatch(key):
            raise ProfileError("ชื่อโปรไฟล์ใช้ได้เฉพาะ a-z, 0-9, _ และ - โดยขึ้นต้นด้วยตัวอักษรหรือตัวเลข")
        if not for_setup:
            for name, path in profiles:
                if name == key:
                    return path
        return root / "profiles" / f"{key}.json"
    if for_setup and named_profiles:
        raise ProfileError("เมื่อมีโปรไฟล์แยกแล้ว ให้ระบุ --profile <ชื่อ> เพื่อเลือกไฟล์ที่จะตั้งค่า")
    if len(profiles) > 1:
        names = ", ".join(name for name, _ in profiles)
        raise ProfileError(f"พบหลายโปรไฟล์ ({names}); โปรดระบุ --profile <ชื่อ> เช่น --profile {profiles[0][0]}")
    if profiles:
        return profiles[0][1]
    return root / "profile.json"


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field_name} is required")
    return value.strip()


def validate_upload_profile(
    profile: UploadProfile,
    *,
    requested_privacy: str,
) -> None:
    """Validate the required owner settings before sending requests to YouTube."""
    if not isinstance(profile, UploadProfile):
        raise ProfileError("A valid upload profile is required")

    _require_text(profile.channel_alias, "channel_alias")
    privacy_status = requested_privacy.casefold() if isinstance(requested_privacy, str) else ""
    saved_privacy = profile.privacy_status.casefold() if isinstance(profile.privacy_status, str) else ""
    if privacy_status not in _ALLOWED_PRIVACY or saved_privacy not in _ALLOWED_PRIVACY:
        raise ProfileError("privacy_status must be private, unlisted, or public")

    if not isinstance(profile.api_audit_passed, bool):
        raise ProfileError("api_audit_passed must be a boolean")

    if not isinstance(profile.made_for_kids, bool):
        raise ProfileError("made_for_kids must be declared true or false")
    if not isinstance(profile.contains_synthetic_media, bool):
        raise ProfileError("contains_synthetic_media must be declared true or false")
    if not isinstance(profile.is_official_artist_channel, bool):
        raise ProfileError("is_official_artist_channel must be declared true or false")
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
