"""``maintenance refresh``: re-check channel access and refresh retained API data."""

from __future__ import annotations

from datetime import datetime, timezone

from ...auth import AuthorizationRevokedError
from ...config.profile import validate_upload_profile


class MaintenanceCommands:
    def _maintenance_refresh(self) -> int:
        now = datetime.now(timezone.utc)
        expired_sessions = self.store.expire_stale_upload_sessions(now)
        purged_count = self.store.purge_expired_api_records(now)
        profile = self._load_profile()
        if profile is None:
            return 2
        if not profile.channel_id:
            self._err("โปรไฟล์ยังไม่มี channel ID ที่ยืนยันแล้ว")
            return 2
        validate_upload_profile(profile, requested_privacy="private")
        credential_store = self._get_credential_store()
        credentials = credential_store.load(profile.oauth_account_key)
        if credentials is None:
            self._err("ไม่พบ OAuth token; เชื่อมบัญชีใหม่ด้วยคำสั่ง upload หลังตรวจโปรไฟล์แล้ว")
            return 1
        try:
            if not getattr(credentials, "valid", True):
                credentials = self.oauth.refresh(profile.oauth_account_key, credential_store, credentials)
            api = self.oauth.build_api(credentials, self.store)
            self.runner.api = api
            owned = api.list_owned_channels()
            if not any(item.channel_id == profile.channel_id for item in owned):
                self._delete_account_data(profile, profile.channel_id)
                self._err("บัญชีนี้ไม่มีสิทธิ์จัดการช่องที่บันทึกไว้แล้ว; ลบข้อมูล API ในเครื่องและหยุด maintenance")
                return 1

            due = [job for job in self.store.list_due_api_records(now) if job.channel_id == profile.channel_id and job.video_id]
            snapshots = api.refresh_videos([job.video_id for job in due if job.video_id]) if due else []
            snapshots_by_id = {snapshot.video_id: snapshot for snapshot in snapshots}
            refreshed_count = 0
            for job in due:
                snapshot = snapshots_by_id.get(job.video_id)
                if snapshot is None:
                    continue
                fields = {
                    name: value
                    for name, value in {
                        "title": snapshot.title,
                        "description": snapshot.description,
                        "privacy_status": snapshot.privacy_status,
                        "thumbnail_url": snapshot.thumbnail_url,
                        "published_at": snapshot.published_at,
                        "publish_at": snapshot.publish_at,
                    }.items()
                    if isinstance(value, str)
                }
                self.store.refresh_api_record(job.id, now, fields)
                refreshed_count += 1
            purged_count += self.store.purge_expired_api_records(now)
            self.result.update(
                refreshed=refreshed_count, purged=purged_count, expired_sessions=expired_sessions
            )
            print(
                f"ปรับปรุงข้อมูล API {refreshed_count} รายการ; "
                f"ลบข้อมูล API ที่หมดอายุ {purged_count} รายการ; "
                f"ล้าง resumable session ที่ไม่ใช้งาน {expired_sessions} รายการ"
            )
            return 0
        except AuthorizationRevokedError as exc:
            self._handle_revoked_authorization(profile)
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ; ลบข้อมูล API และหยุด maintenance: {self._safe_error(exc)}")
            return 1
        except Exception as exc:
            self.store.purge_expired_api_records(datetime.now(timezone.utc))
            self._err(f"maintenance หยุดโดยไม่ทำงานต่อ ({type(exc).__name__})")
            return 1
