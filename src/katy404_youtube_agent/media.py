"""Media probing and deterministic metadata based on filename and owner profile."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import MediaCandidate, MediaFacts, UploadProfile, VideoMetadata

_MAX_TITLE_CHARACTERS = 100
_MAX_DESCRIPTION_BYTES = 5000
_SHORTS_MAX_SECONDS = 180


class MediaProbeError(OSError):
    """Raised when a video cannot be read or inspected safely."""


class MetadataError(ValueError):
    """Raised when deterministic metadata exceeds YouTube limits."""


def probe_media(path: Path, ffprobe: Path | None = None) -> MediaFacts:
    """Read duration, dimensions, and codec using ffprobe without invoking a shell."""
    path = Path(path)
    try:
        if not path.is_file():
            raise MediaProbeError(f"Video file is unavailable: {path}")
        if path.stat().st_size == 0:
            raise MediaProbeError(f"Video file is zero bytes: {path}")
    except OSError as exc:
        if isinstance(exc, MediaProbeError):
            raise
        raise MediaProbeError(f"Could not read video file: {path}") from exc

    executable = str(ffprobe) if ffprobe is not None else shutil.which("ffprobe")
    if not executable:
        raise MediaProbeError("ffprobe was not found; install FFmpeg and ensure ffprobe is on PATH")
    command = [
        executable,
        "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
    except FileNotFoundError as exc:
        raise MediaProbeError("ffprobe executable was not found") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaProbeError(f"Could not run ffprobe: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "ffprobe could not inspect the video"
        raise MediaProbeError(detail)

    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        streams = payload["streams"]
        video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        codec = str(video_stream.get("codec_name") or "")
    except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        raise MediaProbeError("ffprobe returned invalid video metadata or no video stream") from exc
    if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
        raise MediaProbeError("ffprobe returned invalid duration or dimensions")
    return MediaFacts(duration_seconds=duration, width=width, height=height, video_codec=codec)


def _display_stem(path: Path) -> str:
    stem = path.stem
    if stem.casefold().startswith("vdo_"):
        stem = stem[4:]
    if stem.casefold().endswith("_9x16"):
        stem = stem[:-5]
    return stem.strip()


def _format_description(template: str, *, title: str, candidate: MediaCandidate, profile: UploadProfile) -> str:
    values: dict[str, Any] = {
        "title": title,
        "filename": candidate.path.name,
        "channel_alias": profile.channel_alias,
    }
    try:
        return template.format_map(values)
    except (KeyError, ValueError) as exc:
        raise MetadataError("Description template uses an unsupported placeholder") from exc


def build_metadata(candidate: MediaCandidate, facts: MediaFacts, profile: UploadProfile) -> VideoMetadata:
    """Build YouTube fields only from the media filename and configured profile."""
    title = _display_stem(candidate.path)
    is_vertical_or_square = facts.height >= facts.width
    short_candidate = (
        is_vertical_or_square
        and facts.duration_seconds <= _SHORTS_MAX_SECONDS
        and not profile.is_official_artist_channel
    )
    if short_candidate and profile.shorts_title_suffix:
        title = f"{title}{profile.shorts_title_suffix}"
    if len(title) > _MAX_TITLE_CHARACTERS:
        raise MetadataError("YouTube titles cannot exceed 100 characters")

    template = profile.description_template
    if not isinstance(template, str) or not template.strip():
        raise MetadataError("description_template is required")
    description = _format_description(template, title=title, candidate=candidate, profile=profile)
    if len(description.encode("utf-8")) > _MAX_DESCRIPTION_BYTES:
        raise MetadataError("YouTube descriptions cannot exceed 5000 bytes")
    if not isinstance(profile.category_id, str) or not profile.category_id.strip():
        raise MetadataError("category_id is required")
    if not isinstance(profile.made_for_kids, bool) or not isinstance(profile.contains_synthetic_media, bool):
        raise MetadataError("Audience and synthetic media declarations must be set in the profile")

    return VideoMetadata(
        title=title,
        description=description,
        tags=tuple(profile.tags),
        category_id=profile.category_id,
        privacy_status=profile.privacy_status,
        made_for_kids=profile.made_for_kids,
        contains_synthetic_media=profile.contains_synthetic_media,
        short_candidate=short_candidate,
    )
