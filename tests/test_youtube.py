import dataclasses
import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from katy404_youtube_agent.models import UploadChunkResult, VideoUploadResult
from katy404_youtube_agent.youtube import (
    QuotaExceeded,
    ResumableTransport,
    ResumableUploader,
    RetryableUploadError,
    UploadSessionExpired,
)

CHUNK = 8 * 1024 * 1024


@pytest.fixture
def media_file(tmp_path):
    path = tmp_path / "resume.mov"
    path.write_bytes(b"x" * (CHUNK + 17))
    return path


@pytest.fixture
def upload_job(store, candidate, metadata, media_file):
    updated = dataclasses.replace(
        candidate,
        path=media_file,
        sha256=hashlib.sha256(media_file.read_bytes()).hexdigest(),
        size_bytes=media_file.stat().st_size,
        modified_ns=media_file.stat().st_mtime_ns,
    )
    job = store.get_or_create_job(updated, "UC123", metadata)
    store.mark_validated(job.id)
    return store.get_job(job.id)


@pytest.fixture
def upload_result():
    return VideoUploadResult(
        video_id="video-123",
        actual_visibility="private",
        video_url="https://www.youtube.com/watch?v=video-123",
        confirmed_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )


@pytest.fixture
def fake_api(media_file, upload_result):
    transport = Mock()
    transport.begin_upload.return_value = "https://upload.example.test/session/one"
    transport.query_session.return_value = 0
    transport.upload_chunk.return_value = UploadChunkResult(
        next_offset=media_file.stat().st_size,
        result=upload_result,
    )
    return transport


def test_interrupted_upload_queries_server_offset_and_resumes_same_session(
    fake_api, store, upload_job, media_file, upload_result
):
    store.set_upload_session(upload_job.id, "https://upload.invalid/session/one", offset=0)
    fake_api.query_session.return_value = CHUNK
    fake_api.upload_chunk.return_value = UploadChunkResult(
        next_offset=media_file.stat().st_size,
        result=upload_result,
    )

    result = ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert fake_api.upload_chunk.call_args_list[0].kwargs["start"] == CHUNK
    assert fake_api.begin_upload.call_count == 0
    assert result.video_id == "video-123"
    assert store.get_job(upload_job.id).state == "uploaded"


def test_new_upload_persists_resumable_session_before_chunks(fake_api, store, upload_job, media_file):
    result = ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert result.video_id == "video-123"
    assert fake_api.begin_upload.call_count == 1
    assert fake_api.upload_chunk.call_count == 1
    assert store.get_job(upload_job.id).session_uri is None


def test_transient_chunk_failure_queries_confirmed_offset_before_retry(
    fake_api, store, upload_job, media_file, upload_result
):
    fake_api.upload_chunk.side_effect = [
        RetryableUploadError("connection interrupted"),
        UploadChunkResult(next_offset=media_file.stat().st_size, result=upload_result),
    ]
    fake_api.query_session.return_value = 0

    result = ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert result.video_id == "video-123"
    assert fake_api.query_session.call_count == 1
    assert [call.kwargs["start"] for call in fake_api.upload_chunk.call_args_list] == [0, 0]


def test_repeated_transient_chunk_failures_are_bounded_and_keep_session_resumable(
    fake_api, store, upload_job, media_file
):
    sleep = Mock()
    fake_api.upload_chunk.side_effect = RetryableUploadError("connection interrupted")
    fake_api.query_session.return_value = 0

    with pytest.raises(RetryableUploadError):
        ResumableUploader(fake_api, store, sleep=sleep, max_retries=2).upload(upload_job, media_file)

    assert fake_api.upload_chunk.call_count == 3
    assert fake_api.query_session.call_count == 3
    assert sleep.call_count == 2
    saved = store.get_job(upload_job.id)
    assert saved.state == "uploading"
    assert saved.session_uri == "https://upload.example.test/session/one"


def test_completed_resumable_session_is_not_uploaded_again(fake_api, store, upload_job, media_file, upload_result):
    store.set_upload_session(upload_job.id, "https://upload.example.test/session/one", 0)
    fake_api.query_session.return_value = upload_result

    result = ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert result == upload_result
    assert fake_api.begin_upload.call_count == 0
    assert fake_api.upload_chunk.call_count == 0


def test_expired_session_restarts_once_from_zero(fake_api, store, upload_job, media_file, upload_result):
    store.set_upload_session(upload_job.id, "https://upload.example.test/session/expired", 0)
    fake_api.query_session.side_effect = [UploadSessionExpired("expired"), 0]

    result = ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert result.video_id == "video-123"
    assert fake_api.begin_upload.call_count == 1
    assert fake_api.upload_chunk.call_args_list[0].kwargs["start"] == 0


def test_quota_error_is_not_retried(fake_api, store, upload_job, media_file):
    fake_api.begin_upload.side_effect = QuotaExceeded("daily quota reached")

    with pytest.raises(QuotaExceeded):
        ResumableUploader(fake_api, store, sleep=lambda _: None).upload(upload_job, media_file)

    assert fake_api.begin_upload.call_count == 1


class FakeResponse:
    def __init__(self, status_code, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {}
        self.text = text

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_transport_starts_video_insert_with_profile_visibility(upload_job, media_file):
    session = FakeSession(FakeResponse(200, {"Location": "https://upload.example.test/session/created"}))
    transport = ResumableTransport(credentials=None, session=session)

    uri = transport.begin_upload(upload_job, media_file)

    method, url, kwargs = session.calls[0]
    body = json.loads(kwargs["data"])
    assert uri == "https://upload.example.test/session/created"
    assert method == "POST"
    assert "part=snippet%2Cstatus" in url
    assert body["snippet"]["title"] == upload_job.metadata.title
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["status"]["containsSyntheticMedia"] is False


def test_transport_query_uses_youtube_confirmed_range_offset(upload_job):
    session = FakeSession(FakeResponse(308, {"Range": "bytes=0-8388607"}))
    transport = ResumableTransport(credentials=None, session=session)

    offset = transport.query_session("https://upload.example.test/session", 10000000)

    assert offset == CHUNK
    assert session.calls[0][2]["headers"]["Content-Range"] == "bytes */10000000"


def test_transport_upload_chunk_parses_final_video_response(upload_job):
    session = FakeSession(FakeResponse(
        201,
        payload={"id": "video-123", "status": {"privacyStatus": "private"}},
    ))
    transport = ResumableTransport(credentials=None, session=session)

    outcome = transport.upload_chunk("https://upload.example.test/session", 0, b"12345", 5)

    assert outcome.result.video_id == "video-123"
    assert outcome.result.actual_visibility == "private"
    assert session.calls[0][2]["headers"]["Content-Range"] == "bytes 0-4/5"


def test_transport_maps_daily_quota_to_queue_stopping_error():
    session = FakeSession(FakeResponse(403, payload={
        "error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}
    }))
    transport = ResumableTransport(credentials=None, session=session)

    with pytest.raises(QuotaExceeded):
        transport.query_session("https://upload.example.test/session", 5)


def test_transport_marks_server_failures_retryable():
    session = FakeSession(FakeResponse(503, text="temporarily unavailable"))
    transport = ResumableTransport(credentials=None, session=session)

    with pytest.raises(RetryableUploadError):
        transport.query_session("https://upload.example.test/session", 5)
