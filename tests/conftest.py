from datetime import datetime, timezone

import pytest

from katy404_youtube_agent.models import MediaCandidate, UploadProfile, VideoMetadata


NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


@pytest.fixture
def valid_profile(tmp_path):
    secrets_path = tmp_path / "client_secrets.json"
    secrets_path.write_text(
        '{"installed":{"project_id":"mfk110-test-upload"}}', encoding="utf-8"
    )
    return UploadProfile(
        channel_alias="Katy404",
        channel_id="UC123",
        client_secrets_path=secrets_path,
        privacy_status="private",
        api_audit_passed=False,
        category_id="20",
        description_template="{title}",
        tags=(),
        made_for_kids=False,
        contains_synthetic_media=False,
        is_official_artist_channel=False,
        asset_rights_confirmed=True,
        shorts_title_suffix=" #Shorts",
        privacy_policy_url="https://privacy.example.test/katy404",
        policy_accepted_at=NOW.isoformat().replace("+00:00", "Z"),
        policy_version_accepted="2026-09-26",
        approved_pilot_video_id=None,
    )


@pytest.fixture
def candidate(tmp_path):
    video = tmp_path / "vdo_เกมไทย_9x16.mov"
    thumbnail = tmp_path / "vdo_เกมไทย_9x16.jpg"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"image")
    return MediaCandidate(
        path=video,
        thumbnail_path=thumbnail,
        sha256="a" * 64,
        thumbnail_sha256="b" * 64,
        size_bytes=5,
        thumbnail_size_bytes=5,
        modified_ns=1_000_000,
    )


@pytest.fixture
def metadata():
    return VideoMetadata(
        title="เกมไทย #Shorts",
        description="เกมไทย #Shorts",
        tags=(),
        category_id="20",
        privacy_status="private",
        made_for_kids=False,
        contains_synthetic_media=False,
        short_candidate=True,
    )


@pytest.fixture
def store(tmp_path):
    from katy404_youtube_agent.store import JobStore

    return JobStore(tmp_path / "state.sqlite3")


@pytest.fixture
def completed_and_pending_jobs(store, candidate, metadata):
    import dataclasses

    completed = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(completed.id, "video-123", confirmed_at=NOW)
    store.mark_thumbnail_result(completed.id, success=True)

    other_candidate = dataclasses.replace(
        candidate,
        path=candidate.path.with_name("other.mov"),
        thumbnail_path=candidate.thumbnail_path.with_name("other.jpg"),
        sha256="c" * 64,
    )
    pending = store.get_or_create_job(other_candidate, "UC123", metadata)
    store.mark_validated(pending.id)
    store.set_upload_session(pending.id, "https://upload.example.test/session-secret", 2)
    return completed, pending
