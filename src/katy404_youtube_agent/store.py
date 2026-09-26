"""Transactional local job state, deduplication, and API-data retention."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping
from urllib.parse import urlparse

from .models import MediaCandidate, UploadJob, VideoMetadata

_STATES = {"discovered", "validated", "uploading", "uploaded", "complete", "failed", "skipped"}
_TERMINAL_STATES = {"complete", "failed", "skipped"}
_API_FIELDS = {"title", "description", "privacy_status", "thumbnail_url", "published_at"}
_API_REFRESH_DUE_DAYS = 29
_API_DATA_EXPIRY_DAYS = 30


class JobStateError(RuntimeError):
    """Raised when a job transition would lose or contradict upload state."""


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[2] / "state.sqlite3"


def _parse_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Timestamp must be ISO 8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime | str) -> str:
    return _parse_utc(value).isoformat(timespec="microseconds")


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_utc(value)


def _metadata_json(metadata: VideoMetadata) -> str:
    data = asdict(metadata)
    data["tags"] = list(metadata.tags)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _metadata_from_json(value: str) -> VideoMetadata:
    data = json.loads(value)
    data["tags"] = tuple(data.get("tags", ()))
    return VideoMetadata(**data)


class JobStore:
    """Project-local SQLite upload state; refresh or expire API data by day 30."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    modified_ns INTEGER NOT NULL,
                    thumbnail_path TEXT NOT NULL,
                    thumbnail_sha256 TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('discovered','validated','uploading','uploaded','complete','failed','skipped')),
                    session_uri TEXT,
                    offset INTEGER NOT NULL DEFAULT 0 CHECK(offset >= 0),
                    video_id TEXT,
                    thumbnail_status TEXT NOT NULL DEFAULT 'pending' CHECK(thumbnail_status IN ('pending','success','failed','not_requested')),
                    api_refreshed_at TEXT,
                    api_fields_json TEXT NOT NULL DEFAULT '{}',
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(sha256, channel_id)
                );
                CREATE INDEX IF NOT EXISTS jobs_channel_created ON jobs(channel_id, created_at, path);
                CREATE INDEX IF NOT EXISTS jobs_api_refresh ON jobs(api_refreshed_at);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("PRAGMA journal_mode = DELETE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_or_create_job(
        self, candidate: MediaCandidate, channel_id: str, metadata: VideoMetadata
    ) -> UploadJob:
        if not channel_id or not channel_id.strip():
            raise ValueError("channel_id is required")
        now = _timestamp(datetime.now(timezone.utc))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    id, path, sha256, size_bytes, modified_ns, thumbnail_path,
                    thumbnail_sha256, channel_id, metadata_json, state, session_uri,
                    offset, video_id, thumbnail_status, api_refreshed_at,
                    api_fields_json, failure_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', NULL, 0, NULL,
                          'pending', NULL, '{}', NULL, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    str(candidate.path),
                    candidate.sha256,
                    candidate.size_bytes,
                    candidate.modified_ns,
                    str(candidate.thumbnail_path),
                    candidate.thumbnail_sha256,
                    channel_id,
                    _metadata_json(metadata),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE sha256 = ? AND channel_id = ?",
                (candidate.sha256, channel_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("Could not create or retrieve upload job")
            return self._job_from_row(row)

    def get_job(self, job_id: str) -> UploadJob:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def mark_validated(self, job_id: str) -> None:
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] == "validated":
                return
            if row["state"] != "discovered":
                raise JobStateError(f"Cannot validate a job in state {row['state']}")
            self._update(connection, job_id, state="validated")

    def set_upload_session(self, job_id: str, session_uri: str, offset: int) -> None:
        parsed = urlparse(session_uri)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Resumable session URI must be HTTPS")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] not in {"validated", "uploading"}:
                raise JobStateError(f"An upload session requires a validated job; current state is {row['state']}")
            self._update(connection, job_id, state="uploading", session_uri=session_uri, offset=offset)

    def mark_video_uploaded(self, job_id: str, video_id: str, confirmed_at: datetime | str) -> None:
        if not video_id or not video_id.strip():
            raise ValueError("video_id is required")
        confirmed = _timestamp(confirmed_at)
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            state = row["state"]
            if state in {"uploaded", "complete"}:
                if row["video_id"] != video_id:
                    raise JobStateError("A different video ID is already recorded for this job")
                return
            if state not in {"discovered", "validated", "uploading"}:
                raise JobStateError(f"Cannot confirm upload from terminal state {state}")
            self._update(
                connection,
                job_id,
                state="uploaded",
                session_uri=None,
                offset=row["size_bytes"],
                video_id=video_id,
                api_refreshed_at=confirmed,
                api_fields_json="{}",
                failure_code=None,
            )

    def mark_thumbnail_result(self, job_id: str, success: bool) -> None:
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            desired = "success" if success else "failed"
            if row["state"] == "complete":
                if row["thumbnail_status"] != desired:
                    raise JobStateError("A successful thumbnail result cannot be overwritten")
                return
            if row["state"] != "uploaded":
                raise JobStateError(f"Thumbnail result requires an uploaded video; current state is {row['state']}")
            # Keep failed thumbnails retryable while the video remains safely marked uploaded.
            new_state = "complete" if success else "uploaded"
            self._update(connection, job_id, state=new_state, thumbnail_status=desired)

    def mark_failed(self, job_id: str, failure_code: str) -> None:
        if not failure_code or not failure_code.strip():
            raise ValueError("failure_code is required")
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] in _TERMINAL_STATES or row["state"] == "uploaded":
                raise JobStateError(f"Cannot fail a terminal job in state {row['state']}")
            self._update(
                connection,
                job_id,
                state="failed",
                session_uri=None,
                failure_code=failure_code[:100],
            )

    def requeue_failed(self, job_id: str, metadata: VideoMetadata) -> None:
        """Requeue one verified failed source while preserving its hash identity."""
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] != "failed":
                raise JobStateError(f"Cannot requeue a job in state {row['state']}")
            if row["video_id"]:
                raise JobStateError("Cannot requeue a job that already has a YouTube video ID")
            self._update(
                connection,
                job_id,
                state="discovered",
                session_uri=None,
                offset=0,
                metadata_json=_metadata_json(metadata),
                thumbnail_status="pending",
                failure_code=None,
            )

    def update_preupload_metadata(self, job_id: str, metadata: VideoMetadata) -> None:
        """Change metadata only before YouTube has an active resumable session."""
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] not in {"discovered", "validated"}:
                raise JobStateError(f"Cannot change metadata for a job in state {row['state']}")
            self._update(connection, job_id, metadata_json=_metadata_json(metadata))

    def mark_skipped(self, job_id: str, reason_code: str = "skipped") -> None:
        if not reason_code or not reason_code.strip():
            raise ValueError("reason_code is required")
        with self._connect() as connection:
            row = self._require_job(connection, job_id)
            if row["state"] in _TERMINAL_STATES or row["state"] == "uploaded":
                raise JobStateError(f"Cannot skip a terminal job in state {row['state']}")
            self._update(
                connection,
                job_id,
                state="skipped",
                session_uri=None,
                failure_code=reason_code[:100],
            )

    def refresh_api_record(
        self, job_id: str, refreshed_at: datetime | str, api_fields: Mapping[str, str]
    ) -> None:
        unknown_fields = set(api_fields) - _API_FIELDS
        if unknown_fields:
            raise ValueError(f"Unsupported API snapshot field: {sorted(unknown_fields)[0]}")
        if not all(isinstance(value, str) for value in api_fields.values()):
            raise ValueError("API snapshot values must be strings")
        encoded = json.dumps(dict(api_fields), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            self._require_job(connection, job_id)
            self._update(
                connection,
                job_id,
                api_refreshed_at=_timestamp(refreshed_at),
                api_fields_json=encoded,
            )

    def list_due_api_records(self, now: datetime | str) -> list[UploadJob]:
        due_before = _timestamp(_parse_utc(now) - timedelta(days=_API_REFRESH_DUE_DAYS))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE api_refreshed_at IS NOT NULL AND api_refreshed_at <= ? ORDER BY channel_id, path",
                (due_before,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def purge_expired_api_records(self, now: datetime | str) -> int:
        expired_before = _timestamp(_parse_utc(now) - timedelta(days=_API_DATA_EXPIRY_DAYS))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET video_id = NULL, api_refreshed_at = NULL,
                    api_fields_json = '{}', updated_at = ?
                WHERE api_refreshed_at IS NOT NULL AND api_refreshed_at <= ?
                """,
                (_timestamp(_parse_utc(now)), expired_before),
            )
            return cursor.rowcount

    def expire_stale_upload_sessions(self, now: datetime | str) -> int:
        """Forget inactive resumable-session URLs after 30 days and allow a clean retry."""
        current = _parse_utc(now)
        stale_before = _timestamp(current - timedelta(days=_API_DATA_EXPIRY_DAYS))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET state = 'validated', session_uri = NULL, offset = 0, updated_at = ?
                WHERE state = 'uploading' AND updated_at <= ?
                """,
                (_timestamp(current), stale_before),
            )
            return cursor.rowcount

    def list_jobs(self, channel_id: str) -> list[UploadJob]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE channel_id = ? ORDER BY created_at, path", (channel_id,)
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def delete_account_data(self, channel_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE channel_id = ?", (channel_id,))
            return cursor.rowcount

    def _require_job(self, connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    def _update(self, connection: sqlite3.Connection, job_id: str, **values: object) -> None:
        allowed = {
            "state", "session_uri", "offset", "video_id", "thumbnail_status", "metadata_json",
            "api_refreshed_at", "api_fields_json", "failure_code",
        }
        if not set(values) <= allowed:
            raise ValueError("Unsupported job field update")
        values["updated_at"] = _timestamp(datetime.now(timezone.utc))
        assignments = ", ".join(f"{name} = ?" for name in values)
        connection.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*values.values(), job_id),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> UploadJob:
        return UploadJob(
            id=row["id"],
            path=Path(row["path"]),
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            modified_ns=row["modified_ns"],
            thumbnail_path=Path(row["thumbnail_path"]),
            thumbnail_sha256=row["thumbnail_sha256"],
            channel_id=row["channel_id"],
            metadata=_metadata_from_json(row["metadata_json"]),
            state=row["state"],
            session_uri=row["session_uri"],
            offset=row["offset"],
            video_id=row["video_id"],
            thumbnail_status=row["thumbnail_status"],
            api_refreshed_at=_datetime(row["api_refreshed_at"]),
            api_fields=json.loads(row["api_fields_json"]),
            failure_code=row["failure_code"],
        )
