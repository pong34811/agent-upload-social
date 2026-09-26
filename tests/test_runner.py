import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from conftest import NOW
from katy404_youtube_agent.auth import ChannelRef
from katy404_youtube_agent.media import build_metadata
from katy404_youtube_agent.models import MediaFacts, ThumbnailResult, UploadChunkResult, VideoUploadResult
from katy404_youtube_agent.scanner import scan_folder
from katy404_youtube_agent.runner import BatchRunner, PilotApprovalRequired
from katy404_youtube_agent.profile import ProfileError
from katy404_youtube_agent.youtube import QuotaExceeded, ThumbnailError


class FakeApi:
    def __init__(self):
        self.video_requests = []
        self.thumbnail_paths = []
        self._last_job = None
        self.begin_upload = Mock(side_effect=self._begin_upload)
        self.query_session = Mock(return_value=0)
        self.upload_chunk = Mock(side_effect=self._upload_chunk)
        self.set_thumbnail = Mock(side_effect=self._set_thumbnail)
        self.list_owned_channels = Mock(return_value=[ChannelRef("UC123", "Katy404", "@Katy404")])

    def _begin_upload(self, job, media_path):
        self._last_job = job
        self.video_requests.append(
            SimpleNamespace(privacy_status=job.metadata.privacy_status, source_stem=Path(media_path).stem)
        )
        return "https://upload.example.test/session/runner"

    def _upload_chunk(self, *, session_uri, start, chunk, total_bytes):
        return UploadChunkResult(
            next_offset=total_bytes,
            result=VideoUploadResult(
                video_id=f"video-{len(self.video_requests)}",
                actual_visibility=self._last_job.metadata.privacy_status,
                video_url=f"https://www.youtube.com/watch?v=video-{len(self.video_requests)}",
                confirmed_at=NOW,
            ),
        )

    def _set_thumbnail(self, video_id, thumbnail_path):
        self.thumbnail_paths.append(Path(thumbnail_path))
        return ThumbnailResult(success=True, error=None)


@pytest.fixture
def media_folder(tmp_path):
    (tmp_path / "clip.mov").write_bytes(b"video bytes")
    (tmp_path / "clip.jpg").write_bytes(b"image bytes")
    return tmp_path


@pytest.fixture
def two_media_folder(tmp_path):
    for stem in ("first", "second"):
        (tmp_path / f"{stem}.mov").write_bytes(f"video {stem}".encode())
        (tmp_path / f"{stem}.jpg").write_bytes(f"image {stem}".encode())
    return tmp_path


@pytest.fixture
def fake_api():
    return FakeApi()


@pytest.fixture
def runner(valid_profile, store, fake_api):
    return BatchRunner(
        valid_profile,
        store,
        fake_api,
        probe=lambda _path: MediaFacts(duration_seconds=60, width=1920, height=1080, video_codec="h264"),
        sleep=lambda _: None,
    )


def _prepared_job(folder, store, profile, stem=None):
    candidates, issues = scan_folder(folder)
    assert not issues
    candidate = next(item for item in candidates if stem is None or item.path.stem == stem)
    metadata = build_metadata(candidate, MediaFacts(60, 1920, 1080, "h264"), profile)
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_validated(job.id)
    return store.get_job(job.id)


@pytest.fixture
def prepared_job(media_folder, store, valid_profile):
    return _prepared_job(media_folder, store, valid_profile)


@pytest.fixture
def uploaded_job(prepared_job, store):
    store.mark_video_uploaded(prepared_job.id, "video-123", confirmed_at=NOW)
    store.mark_thumbnail_result(prepared_job.id, success=False)
    return store.get_job(prepared_job.id)


@pytest.fixture
def two_prepared_jobs(two_media_folder, store, valid_profile):
    return [
        _prepared_job(two_media_folder, store, valid_profile, "first"),
        _prepared_job(two_media_folder, store, valid_profile, "second"),
    ]


def test_private_pilot_sets_private_visibility_and_matching_thumbnail(fake_api, runner, media_folder):
    report = runner.upload(media_folder, "Katy404", limit=1, force_private=True)

    assert report.uploaded_count == 1
    assert fake_api.video_requests[0].privacy_status == "private"
    assert fake_api.thumbnail_paths[0].stem == fake_api.video_requests[0].source_stem
    assert report.items[0].actual_visibility == "private"


def test_changed_media_after_dry_run_is_skipped_before_network_upload(fake_api, runner, prepared_job):
    prepared_job.path.write_bytes(b"changed bytes")

    report = runner.upload_prepared([prepared_job])

    assert report.items[0].status == "skipped_changed_file"
    assert fake_api.begin_upload.call_count == 0


def test_changed_thumbnail_after_dry_run_is_not_sent(fake_api, runner, prepared_job):
    prepared_job.thumbnail_path.write_bytes(b"changed image")

    report = runner.upload_prepared([prepared_job])

    assert report.items[0].status == "skipped_changed_thumbnail"
    assert fake_api.begin_upload.call_count == 0
    assert fake_api.set_thumbnail.call_count == 0


def test_retry_after_thumbnail_failure_does_not_insert_video_again(fake_api, runner, uploaded_job):
    fake_api.set_thumbnail.side_effect = [ThumbnailError("temporary"), ThumbnailResult(True, None)]

    runner.upload_prepared([uploaded_job])
    second = runner.upload_prepared([uploaded_job])

    assert fake_api.begin_upload.call_count == 0
    assert fake_api.set_thumbnail.call_count == 2
    assert second.items[0].thumbnail_status == "success"


def test_quota_error_stops_remaining_files_without_retrying_them(fake_api, runner, two_prepared_jobs):
    fake_api.begin_upload.side_effect = QuotaExceeded("daily quota reached")

    report = runner.upload_prepared(two_prepared_jobs)

    assert report.stopped_reason == "quota"
    assert report.pending_count == 2
    assert fake_api.begin_upload.call_count == 1


def test_dry_run_scans_locally_without_calling_upload_api(fake_api, runner, media_folder):
    report = runner.dry_run(media_folder, "Katy404")

    assert report.items[0].status == "ready"
    assert report.uploaded_count == 0
    assert fake_api.begin_upload.call_count == 0
    assert fake_api.list_owned_channels.call_count == 0




def test_full_batch_waits_for_private_pilot_review(runner, fake_api, media_folder):
    with pytest.raises(PilotApprovalRequired, match="Private pilot"):
        runner.upload(media_folder, "Katy404")

    assert fake_api.list_owned_channels.call_count == 0
    assert fake_api.begin_upload.call_count == 0


def test_upload_preflight_callback_runs_before_video_transport(runner, fake_api, media_folder):
    events = []
    original_begin = fake_api.begin_upload.side_effect

    def record_video_insert(*args, **kwargs):
        events.append("video_insert")
        return original_begin(*args, **kwargs)

    fake_api.begin_upload.side_effect = record_video_insert
    report = runner.upload(
        media_folder,
        "Katy404",
        limit=1,
        force_private=True,
        on_preflight=lambda *_args: events.append("preflight"),
    )

    assert events == ["preflight", "video_insert"]
    assert report.uploaded_count == 1


def test_public_visibility_is_blocked_until_api_audit(valid_profile, store, fake_api, media_folder):
    from dataclasses import replace

    profile = replace(
        valid_profile,
        privacy_status="public",
        api_audit_passed=False,
        approved_pilot_video_id="reviewed-pilot-id",
    )
    public_runner = BatchRunner(
        profile,
        store,
        fake_api,
        probe=lambda _path: MediaFacts(60, 1920, 1080, "h264"),
        sleep=lambda _: None,
    )

    with pytest.raises(ProfileError, match="API compliance audit"):
        public_runner.upload(media_folder, "Katy404")

    assert fake_api.list_owned_channels.call_count == 0
    assert fake_api.begin_upload.call_count == 0


def test_quota_after_video_confirmation_preserves_success_and_stops_remaining(
    fake_api, runner, two_prepared_jobs
):
    def confirmed_then_quota(job, _media_path):
        runner.store.mark_video_uploaded(job.id, "video-confirmed", confirmed_at=NOW)
        raise QuotaExceeded("daily quota reached during visibility refresh")

    fake_api.upload_video = Mock(side_effect=confirmed_then_quota)

    report = runner.upload_prepared(two_prepared_jobs)

    assert report.items[0].status == "uploaded_thumbnail_failed"
    assert report.items[0].video_id == "video-confirmed"
    assert report.uploaded_count == 1
    assert report.pending_count == 1
    assert report.stopped_reason == "quota"
    assert fake_api.set_thumbnail.call_count == 0
