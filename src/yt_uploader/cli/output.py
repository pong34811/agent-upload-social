"""Text and JSON rendering of command results; never includes tokens or API bodies."""

from __future__ import annotations

from typing import Any

from ..auth import AuthorizationRequiredError, CredentialStoreError
from ..config.profile import ProfileError
from ..jobs.store import JobStateError
from ..models import BatchReport, UploadItemResult, UploadProfile
from ..youtube.errors import VideoSchedulingError

_LIMIT_MESSAGES = {
    "uploadLimitExceeded": "ช่องถึงขีดจำกัดจำนวนวิดีโอที่อัปโหลดต่อวัน",
    "uploadRateLimitExceeded": "YouTube จำกัดการส่งภาพปกชั่วคราว; รอแล้วสั่ง upload อีกครั้งเพื่อส่งปกที่ค้างและคลิปที่เหลือ",
    "quotaExceeded": "คำขอเกินโควตา API ที่ Google อนุญาต",
    "dailyLimitExceeded": "คำขอเกินขีดจำกัด API รายวัน",
    "dailyLimitExceededUnreg": "คำขอเกินขีดจำกัดรายวันของ client ที่ไม่ลงทะเบียน",
    "userLimitExceeded": "คำขอเกินขีดจำกัดของผู้ใช้",
}


def safe_error(exc: Exception) -> str:
    # Whitelist local validation messages; do not leak API response bodies or OAuth URLs.
    if isinstance(exc, (
        JobStateError, ProfileError, CredentialStoreError, AuthorizationRequiredError,
        VideoSchedulingError, ValueError, OSError,
    )):
        return str(exc)
    return type(exc).__name__


def print_report(report: BatchReport) -> None:
    print(
        "ผลรอบนี้: "
        f"อัปโหลด/วิดีโอสำเร็จ {report.uploaded_count}, "
        f"ข้าม {report.skipped_count}, ผิดพลาด {report.failed_count}, "
        f"รออยู่ {report.pending_count}"
    )
    if report.scheduled_count:
        print(f"ตั้งเวลาเผยแพร่แล้ว: {report.scheduled_count}")
    if report.stopped_reason:
        reason = next((item.error_code for item in report.items if item.error_code in _LIMIT_MESSAGES), None)
        if report.stopped_reason == "quota" and reason:
            print(f"หยุดคิว: {reason} — {_LIMIT_MESSAGES[reason]}")
        else:
            print(f"หยุดคิว: {report.stopped_reason}")
    for item in report.items:
        if item.scheduled_publish_at and item.video_url:
            print(f"{item.status} (Private จนถึง {item.scheduled_publish_at}): {item.video_url}")
        elif item.status.startswith("uploaded") and item.video_url:
            error = f"; error={item.error_code}" if item.error_code else ""
            print(f"{item.status} ({item.actual_visibility or 'unknown'}): {item.video_url}{error}")
            if item.status == "uploaded_thumbnail_pending":
                print("ปกคลิปยังรอ YouTube ประมวลผลเสร็จ; รันคำสั่ง upload สำหรับไฟล์นี้อีกครั้งภายหลังเพื่อส่งปกซ้ำ")
        elif item.status == "failed" or item.status.startswith("pending"):
            print(f"{item.status}: {item.source_path.name} ({item.error_code or 'ไม่มีรหัสข้อผิดพลาด'})")


def item_payload(item: UploadItemResult) -> dict[str, Any]:
    return {
        "file": item.source_path.name,
        "path": str(item.source_path),
        "status": item.status,
        "title": item.title,
        "video_id": item.video_id,
        "video_url": item.video_url,
        "visibility": item.actual_visibility,
        "thumbnail": item.thumbnail_status,
        "publish_at": item.scheduled_publish_at,
        "error_code": item.error_code,
    }


def report_payload(report: BatchReport) -> dict[str, Any]:
    return {
        "summary": {
            "ready": sum(item.status == "ready" for item in report.items),
            "uploaded": report.uploaded_count,
            "scheduled": report.scheduled_count,
            "skipped": report.skipped_count,
            "failed": report.failed_count,
            "pending": report.pending_count,
        },
        "stopped_reason": report.stopped_reason,
        "items": [item_payload(item) for item in report.items],
    }


def profile_payload(profile: UploadProfile) -> dict[str, Any]:
    """Channel settings an agent may report; the OAuth client file is named, never read."""
    return {
        "channel_alias": profile.channel_alias,
        "channel_id": profile.channel_id,
        "oauth_account": profile.oauth_account_key,
        "privacy_status": profile.privacy_status,
        "category_id": profile.category_id,
        "made_for_kids": profile.made_for_kids,
        "contains_synthetic_media": profile.contains_synthetic_media,
        "client_secrets_configured": profile.client_secrets_path is not None,
    }
