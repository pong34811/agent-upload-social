"""ffprobe-based inspection of duration, dimensions, and codec."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from ..models import MediaFacts


class MediaProbeError(OSError):
    """Raised when a video cannot be read or inspected safely."""


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
