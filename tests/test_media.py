import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from katy404_youtube_agent.media import (
    MediaProbeError,
    MetadataError,
    build_metadata,
    probe_media,
)
from katy404_youtube_agent.models import MediaFacts


def test_metadata_strips_internal_prefix_and_preserves_thai_and_short_suffix(candidate, valid_profile):
    metadata = build_metadata(candidate, MediaFacts(duration_seconds=90, width=1080, height=1920), valid_profile)

    assert metadata.title == "เกมไทย #Shorts"
    assert metadata.privacy_status == "private"
    assert metadata.short_candidate is True


def test_official_artist_channel_profile_does_not_add_standard_shorts_suffix(candidate, valid_profile):
    profile = dataclasses.replace(valid_profile, is_official_artist_channel=True)
    metadata = build_metadata(candidate, MediaFacts(duration_seconds=90, width=1080, height=1920), profile)

    assert "#Shorts" not in metadata.title


def test_long_or_horizontal_video_does_not_get_shorts_suffix(candidate, valid_profile):
    horizontal = build_metadata(candidate, MediaFacts(duration_seconds=120, width=1920, height=1080), valid_profile)
    long_video = build_metadata(candidate, MediaFacts(duration_seconds=181, width=1080, height=1920), valid_profile)

    assert "#Shorts" not in horizontal.title
    assert "#Shorts" not in long_video.title


def test_probe_media_reports_ffprobe_failure(tmp_path, monkeypatch):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"not a real movie")
    monkeypatch.setattr(
        "katy404_youtube_agent.media.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "invalid media"),
    )

    with pytest.raises(MediaProbeError, match="invalid media"):
        probe_media(video, ffprobe=Path("ffprobe.exe"))


def test_probe_media_parses_duration_dimensions_and_codec(tmp_path, monkeypatch):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"video")
    payload = {"format": {"duration": "90.5"}, "streams": [
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
    ]}
    monkeypatch.setattr(
        "katy404_youtube_agent.media.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(payload), ""),
    )

    facts = probe_media(video, ffprobe=Path("ffprobe.exe"))

    assert facts == MediaFacts(90.5, 1080, 1920, "h264")


def test_probe_media_reports_missing_ffprobe(tmp_path, monkeypatch):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"video")
    monkeypatch.setattr("katy404_youtube_agent.media.subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("ffprobe missing")))

    with pytest.raises(MediaProbeError, match="ffprobe"):
        probe_media(video, ffprobe=Path("ffprobe.exe"))


def test_metadata_rejects_description_over_5000_utf8_bytes(candidate, valid_profile):
    profile = dataclasses.replace(valid_profile, description_template="ก" * 2000)

    with pytest.raises(MetadataError, match="5000 bytes"):
        build_metadata(candidate, MediaFacts(duration_seconds=90, width=1080, height=1920), profile)


def test_metadata_rejects_title_over_100_characters(candidate, valid_profile):
    long_video = dataclasses.replace(candidate, path=Path("vdo_" + "ก" * 101 + "_9x16.mov"))

    with pytest.raises(MetadataError, match="100 characters"):
        build_metadata(long_video, MediaFacts(duration_seconds=90, width=1080, height=1920), valid_profile)
