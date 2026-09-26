from dataclasses import replace
from datetime import timedelta

import pytest

from conftest import NOW
from katy404_youtube_agent.store import JobStateError, JobStore


def test_completed_hash_and_channel_are_reused_instead_of_requeued(store, candidate, metadata):
    first = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(first.id, "video-123", confirmed_at=NOW)
    reopened = JobStore(store.db_path)
    second = reopened.get_or_create_job(candidate, "UC123", metadata)

    assert second.id == first.id
    assert second.video_id == "video-123"
    assert second.state == "uploaded"


def test_same_file_to_different_channel_is_a_distinct_job(store, candidate, metadata):
    left = store.get_or_create_job(candidate, "UC123", metadata)
    right = store.get_or_create_job(candidate, "UC456", metadata)

    assert right.id != left.id


def test_api_snapshot_becomes_due_before_the_30_day_limit(store, candidate, metadata):
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.refresh_api_record(job.id, NOW, {"privacy_status": "private"})

    assert store.list_due_api_records(NOW + timedelta(days=30)) == [job]


def test_delete_account_data_removes_only_matching_channel(store, candidate, metadata, completed_and_pending_jobs):
    other_channel_job = store.get_or_create_job(candidate, "UC456", metadata)
    store.record_policy_acceptance("UC123", "https://privacy.example.test/katy404", NOW, "2026-09-26")
    store.record_policy_acceptance("UC456", "https://privacy.example.test/katy404", NOW, "2026-09-26")

    removed = store.delete_account_data("UC123")

    assert removed == 2
    assert store.list_jobs("UC123") == []
    assert store.get_policy_acceptance("UC123") is None
    assert store.list_jobs("UC456") == [other_channel_job]
    assert store.get_policy_acceptance("UC456") is not None


def test_resumable_session_survives_store_reopen(tmp_path, candidate, metadata):
    path = tmp_path / "state.sqlite3"
    first_store = JobStore(path)
    job = first_store.get_or_create_job(candidate, "UC123", metadata)
    first_store.mark_validated(job.id)
    first_store.set_upload_session(job.id, "https://upload.example.test/session-secret", 1234)

    reopened = JobStore(path)
    saved = reopened.list_jobs("UC123")[0]

    assert saved.state == "uploading"
    assert saved.session_uri == "https://upload.example.test/session-secret"
    assert saved.offset == 1234


def test_stale_resumable_session_uri_is_removed_after_30_days(store, candidate, metadata):
    stale = store.get_or_create_job(candidate, "UC123", metadata)
    fresh_candidate = replace(
        candidate,
        path=candidate.path.with_name("fresh.mov"),
        thumbnail_path=candidate.thumbnail_path.with_name("fresh.jpg"),
        sha256="c" * 64,
    )
    fresh = store.get_or_create_job(fresh_candidate, "UC123", metadata)
    for job in (stale, fresh):
        store.mark_validated(job.id)
        store.set_upload_session(job.id, f"https://upload.example.test/{job.id}", 4096)
    with store._connect() as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            ((NOW - timedelta(days=31)).isoformat(), stale.id),
        )

    removed = store.expire_stale_upload_sessions(NOW)
    stale_after = store.get_job(stale.id)
    fresh_after = store.get_job(fresh.id)

    assert removed == 1
    assert stale_after.state == "validated"
    assert stale_after.session_uri is None
    assert stale_after.offset == 0
    assert fresh_after.state == "uploading"
    assert fresh_after.session_uri is not None


def test_expired_api_fields_are_cleared_but_duplicate_guard_remains(store, candidate, metadata):
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(job.id, "video-123", confirmed_at=NOW)
    store.refresh_api_record(job.id, NOW, {"privacy_status": "private", "title": "Game"})

    removed = store.purge_expired_api_records(NOW + timedelta(days=30))
    saved = store.list_jobs("UC123")[0]
    duplicate = store.get_or_create_job(candidate, "UC123", metadata)

    assert removed == 1
    assert saved.video_id is None
    assert saved.api_fields == {}
    assert duplicate.id == job.id
    assert duplicate.state == "uploaded"


def test_invalid_transition_is_rejected(store, candidate, metadata):
    job = store.get_or_create_job(candidate, "UC123", metadata)

    with pytest.raises(JobStateError, match="validated"):
        store.set_upload_session(job.id, "https://upload.example.test/session", 0)


def test_same_hash_in_active_job_keeps_original_metadata(store, candidate, metadata):
    first = store.get_or_create_job(candidate, "UC123", metadata)
    changed = replace(metadata, title="Different title")

    second = store.get_or_create_job(candidate, "UC123", changed)

    assert second.id == first.id
    assert second.metadata.title == first.metadata.title


def test_confirmed_upload_cannot_be_marked_failed_or_skipped(store, candidate, metadata):
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(job.id, "video-123", confirmed_at=NOW)

    with pytest.raises(JobStateError, match="uploaded"):
        store.mark_failed(job.id, "thumbnail_error")
    with pytest.raises(JobStateError, match="uploaded"):
        store.mark_skipped(job.id, "already_uploaded")


def test_failed_thumbnail_stays_retryable_after_video_success(store, candidate, metadata):
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(job.id, "video-123", confirmed_at=NOW)

    store.mark_thumbnail_result(job.id, success=False)
    failed_attempt = store.get_job(job.id)

    assert failed_attempt.state == "uploaded"
    assert failed_attempt.thumbnail_status == "failed"

    store.mark_thumbnail_result(job.id, success=True)
    finished = store.get_job(job.id)
    assert finished.state == "complete"
    assert finished.thumbnail_status == "success"
