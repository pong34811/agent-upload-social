"""``dry-run``, ``upload``, and ``schedule`` commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from ...auth import (
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    ChannelRef,
    ChannelResolutionError,
    CredentialStoreError,
    resolve_channel,
)
from ...config.profile import ProfileError, validate_upload_profile
from ...jobs.store import JobStateError
from ...models import UploadProfile
from ...pipeline.schedule import format_publish_at, parse_publish_at, parse_schedule_start
from ...youtube.errors import QuotaExceeded, VideoSchedulingError
from ..output import report_payload


class UploadCommands:
    def _dry_run(self, folder: Path, channel: str, file_name: str | None = None) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        self.runner.profile = profile
        report = self.runner.dry_run(folder, channel, file_name=file_name)
        self.result["folder"] = str(folder)
        self.result.update(report_payload(report))
        ready_count = sum(item.status == "ready" for item in report.items)
        print(f"ตรวจโฟลเดอร์ระดับบนสุด: {folder}")
        print(f"วิดีโอที่พร้อม: {ready_count}")
        print(f"ข้าม/ต้องแก้ก่อนอัปโหลด: {report.failed_count}")
        for item in report.items:
            if item.status != "ready":
                print(f"  {item.source_path.name}: {item.error_code or item.status}")
        return 0

    def _upload(self, args: argparse.Namespace) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        schedule_start = parse_schedule_start(args.schedule_from) if args.schedule_from else None
        limit = args.limit
        force_private = args.force_private
        if schedule_start is not None:
            if args.limit is not None or args.force_private:
                self._err("โหมดตั้งเวลาใช้กับ batch เต็มเท่านั้น ห้ามใช้ --limit หรือ --force-private")
                return 2
            requested_privacy = "public"
        else:
            requested_privacy = "private" if force_private else profile.privacy_status
        # Consent and configuration are checked before loading OAuth credentials or opening a browser.
        validate_upload_profile(profile, requested_privacy=requested_privacy)
        credential_store = self._get_credential_store()
        try:
            if schedule_start is not None and not credential_store.has_required_scopes(profile.oauth_account_key):
                print("การตั้งเวลาต้องยืนยัน OAuth เพิ่ม; กำลังเปิด Google OAuth")
                credentials = self._authorize_for_account(
                    profile.client_secrets_path, credential_store, profile.oauth_account_key
                )
            else:
                credentials = credential_store.load(profile.oauth_account_key)
            if credentials is None:
                credentials = self._authorize_for_account(
                    profile.client_secrets_path, credential_store, profile.oauth_account_key
                )
            elif not getattr(credentials, "valid", True):
                credentials = self.oauth.refresh(profile.oauth_account_key, credential_store, credentials)
        except AuthorizationRevokedError as exc:
            self._handle_revoked_authorization(profile)
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ; ลบข้อมูล API ในเครื่องและหยุด upload: {self._safe_error(exc)}")
            return 1
        api = self.oauth.build_api(credentials, self.store)
        self.runner.api = api
        self.runner.profile = profile

        requested_channel = args.channel

        def report_preflight(
            channel: ChannelRef,
            video_count: int,
            skipped_count: int,
            privacy_status: str,
            current_profile: UploadProfile,
        ) -> None:
            self.result["channel"] = {"id": channel.channel_id, "name": channel.display_name}
            self.result["privacy_status"] = privacy_status
            print(f"ช่อง: {channel.display_name} ({channel.channel_id})")
            print(f"วิดีโอ: {video_count}")
            print(f"ข้าม: {skipped_count}")
            print(f"ความเป็นส่วนตัว: {privacy_status}")
            print(f"โปรไฟล์ revision: {self._profile_revision()}")
            print(f"Made for Kids: {'ใช่' if current_profile.made_for_kids else 'ไม่ใช่'}")
            print(f"Synthetic media: {'ใช่' if current_profile.contains_synthetic_media else 'ไม่ใช่'}")
            print(f"Official Artist Channel: {'ใช่' if current_profile.is_official_artist_channel else 'ไม่ใช่'}")

        def report_schedule_plan(schedule_plan: dict[Path, datetime]) -> None:
            if not schedule_plan:
                return
            slots = sorted(set(schedule_plan.values()))
            self.result["schedule"] = {
                "videos": len(schedule_plan),
                "days": len(slots),
                "first": format_publish_at(slots[0]),
                "last": format_publish_at(slots[-1]),
            }
            print(f"ตารางเผยแพร่: {len(schedule_plan)} คลิป, {len(slots)} วัน, วันละแนวนอน 1 + แนวตั้ง 1")
            print(f"เวลาแรก: {format_publish_at(slots[0])}; เวลาสุดท้าย: {format_publish_at(slots[-1])}")

        def run_upload(channel: str):
            return self.runner.upload(
                args.folder,
                channel,
                limit=limit,
                force_private=force_private,
                file_name=args.file,
                on_preflight=report_preflight,
                schedule_from=schedule_start,
                on_schedule_plan=report_schedule_plan if schedule_start is not None else None,
            )

        try:
            try:
                report = run_upload(requested_channel)
            except ChannelResolutionError as exc:
                if "ambiguous" not in str(exc).casefold():
                    raise
                if self.json_mode:
                    # Agents must not guess; ask the user for the handle or channel ID instead.
                    self._err(f"ยกเลิกก่อนเริ่มอัปโหลด: {self._safe_error(exc)}; ระบุ channel handle หรือ channel ID")
                    return 2
                clarified = input("ชื่อช่องซ้ำกัน กรุณาระบุ channel handle หรือ channel ID: ").strip()
                if not clarified:
                    return 2
                report = run_upload(clarified)
        except (ProfileError, ValueError) as exc:
            self._err(f"ยกเลิกก่อนเริ่มอัปโหลด: {self._safe_error(exc)}")
            return 2
        except AuthorizationRevokedError as exc:
            self._handle_revoked_authorization(profile)
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ; ลบข้อมูล API ในเครื่องและหยุด upload: {self._safe_error(exc)}")
            return 1
        except VideoSchedulingError as exc:
            self._err(f"ตั้งเวลาไม่ได้: {self._safe_error(exc)}")
            return 1
        except Exception as exc:
            self._err(f"อัปโหลดไม่สำเร็จ ({type(exc).__name__})")
            return 1

        self._print_report(report)
        self.result.update(report_payload(report))
        thumbnail_errors = any(item.status == "uploaded_thumbnail_failed" for item in report.items)
        if report.failed_count or report.pending_count or report.stopped_reason or thumbnail_errors:
            return 1
        return 0

    def _schedule_video(self, video_id: str, publish_at_text: str) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        publish_at = parse_publish_at(publish_at_text)
        try:
            validate_upload_profile(
                profile,
                requested_privacy="public",
            )
        except ProfileError as exc:
            self._err(f"ยังตั้งเวลาเผยแพร่ไม่ได้: {self._safe_error(exc)}")
            return 2
        if not profile.channel_id:
            self._err("โปรไฟล์ยังไม่มี channel ID ที่ยืนยันแล้ว")
            return 2

        credential_store = self._get_credential_store()
        if not credential_store.has_required_scopes(profile.oauth_account_key):
            self._err("OAuth ยังไม่มีสิทธิ์แก้ metadata; รัน yt-upload auth reauthorize ก่อนตั้งเวลา")
            return 2
        try:
            credentials = credential_store.load(profile.oauth_account_key)
            if credentials is None:
                self._err("ไม่พบ OAuth credential; รัน yt-upload auth reauthorize ก่อนตั้งเวลา")
                return 2
            if not getattr(credentials, "valid", True):
                credentials = self.oauth.refresh(profile.oauth_account_key, credential_store, credentials)
            job = self.store.get_job_by_video_id(video_id, profile.channel_id)
            if job is None or job.state not in {"uploaded", "complete"}:
                self._err("video ID นี้ไม่มีงานอัปโหลดที่ยืนยันไว้ในช่องของโปรไฟล์")
                return 2
            api = self.oauth.build_api(credentials, self.store)
            channel = resolve_channel(profile.channel_id, api.list_owned_channels())
            if channel.channel_id != profile.channel_id:
                self._err("OAuth account ไม่ได้ยืนยันช่องตามโปรไฟล์; หยุดตั้งเวลา")
                return 2
            api.schedule_video(video_id, profile.channel_id, publish_at)
            self.store.refresh_api_record(
                job.id,
                datetime.now(timezone.utc),
                {"privacy_status": "private", "publish_at": format_publish_at(publish_at)},
            )
        except AuthorizationRevokedError as exc:
            self._handle_revoked_authorization(profile)
            self._err(f"OAuth ใช้งานไม่ได้; หยุดตั้งเวลา: {self._safe_error(exc)}")
            return 1
        except (ProfileError, CredentialStoreError, AuthorizationRequiredError, JobStateError, ValueError, OSError) as exc:
            self._err(f"ตั้งเวลาไม่ได้: {self._safe_error(exc)}")
            return 2
        except VideoSchedulingError as exc:
            self._err(f"ตั้งเวลาไม่ได้: {self._safe_error(exc)}")
            return 1
        except QuotaExceeded as exc:
            self._err(f"YouTube หยุดการตั้งเวลา: {exc.error_code}")
            return 1
        except Exception as exc:
            self._err(f"ตั้งเวลาไม่สำเร็จ ({type(exc).__name__})")
            return 1
        self.result["video"] = {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "privacy_status": "private",
            "publish_at": format_publish_at(publish_at),
        }
        print(f"ตั้งเวลาเผยแพร่สำเร็จ: https://www.youtube.com/watch?v={video_id}")
        print(f"YouTube คงวิดีโอเป็น Private จนถึง {format_publish_at(publish_at)}")
        return 0
