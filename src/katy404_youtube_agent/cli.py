"""Local command line and AI-agent entry point for the Katy404 YouTube uploader."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .auth import (
    OWNER_ACCOUNT_KEY,
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    ChannelRef,
    CredentialRevocationError,
    CredentialStore,
    CredentialStoreError,
    resolve_channel,
)
from .models import BatchReport, UploadProfile
from .profile import POLICY_VERSION, ProfileError, ProfileStore, validate_upload_profile
from .runner import BatchRunner, PilotApprovalRequired
from .store import JobStore
from .youtube import YouTubeApi


YOUTUBE_TERMS_URL = "https://www.youtube.com/t/terms"
GOOGLE_SECURITY_URL = "https://security.google.com/settings/security/permissions"


class OAuthService:
    """Indirection point so command behavior can be exercised without OAuth/network access."""

    def authorize(self, client_secrets_path: Path, credential_store: CredentialStore) -> Any:
        from .auth import authorize_desktop

        return authorize_desktop(client_secrets_path, credential_store)

    def refresh(self, account_key: str, credential_store: CredentialStore, credentials: Any) -> Any:
        from .auth import refresh_credentials

        return refresh_credentials(account_key, credential_store, credentials)

    def build_api(self, credentials: Any, store: JobStore) -> Any:
        return YouTubeApi(credentials, store=store)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kt404-youtube",
        description="ตัวช่วยอัปโหลดวิดีโอ YouTube ในเครื่องสำหรับช่อง Katy404",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="ตั้งค่าและจัดการโปรไฟล์ช่อง")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("setup", help="สร้างโปรไฟล์ครั้งแรก")
    profile_commands.add_parser("accept-policy", help="อ่านและยอมรับ privacy policy")
    profile_commands.add_parser("show", help="แสดงค่าที่ตั้งไว้โดยไม่แสดง token")
    privacy = profile_commands.add_parser("set-privacy", help="เปลี่ยนความเป็นส่วนตัวเริ่มต้น")
    privacy.add_argument("status", choices=("private", "unlisted", "public"))
    audit = profile_commands.add_parser("set-api-audit-status", help="บันทึกผล YouTube API audit")
    audit.add_argument("status", choices=("passed", "not-passed"))
    rights = profile_commands.add_parser("set-asset-rights-status", help="แก้ไขการรับรองสิทธิ์ assets")
    rights.add_argument("status", choices=("confirmed", "not-confirmed"))
    pilot = profile_commands.add_parser("approve-pilot", help="อนุมัติคลิปนำร่องหลังตรวจใน Studio")
    pilot.add_argument("--video-id", required=True)
    delete_data = profile_commands.add_parser("delete-account-data", help="ลบข้อมูล API ของช่องในเครื่อง")
    delete_data.add_argument("--channel-id")
    revoke = profile_commands.add_parser("revoke-authorization", help="ยกเลิกสิทธิ์ OAuth และลบข้อมูลช่อง")
    revoke.add_argument("--channel-id")

    for name in ("dry-run", "upload"):
        command = commands.add_parser(name, help="ตรวจไฟล์ในโฟลเดอร์ที่ระบุ" if name == "dry-run" else "อัปโหลดโฟลเดอร์ที่ระบุ")
        command.add_argument("--folder", required=True, type=Path)
        command.add_argument("--channel", required=True)
        if name == "upload":
            command.add_argument("--limit", type=int)
            command.add_argument("--force-private", action="store_true")

    maintenance = commands.add_parser("maintenance", help="ดูแลการเชื่อมต่อและข้อมูล API")
    maintenance_commands = maintenance.add_subparsers(dest="maintenance_command", required=True)
    maintenance_commands.add_parser("refresh", help="ตรวจสิทธิ์ช่องและปรับปรุงข้อมูลตามรอบเก็บรักษา")
    return parser


class CliApp:
    """Command dispatcher with all side-effecting services injectable for offline tests."""

    def __init__(
        self,
        *,
        runner: BatchRunner,
        profile_store: ProfileStore,
        credential_store: CredentialStore | None,
        oauth_service: Any,
        store: JobStore | None = None,
        credential_store_factory: Callable[[], CredentialStore] = CredentialStore,
    ) -> None:
        self.runner = runner
        self.profile_store = profile_store
        self.credential_store = credential_store
        self.oauth = oauth_service
        self.store = store if store is not None else runner.store
        self._credential_store_factory = credential_store_factory

    def run(self, argv: list[str]) -> int:
        parser = _build_parser()
        try:
            args = parser.parse_args(argv)
            if args.command == "profile":
                return self._run_profile(args)
            if args.command == "dry-run":
                return self._dry_run(args.folder, args.channel)
            if args.command == "upload":
                return self._upload(args)
            if args.command == "maintenance" and args.maintenance_command == "refresh":
                return self._maintenance_refresh()
            parser.error("unsupported command")
        except SystemExit as exc:
            return int(exc.code or 0)
        except (ProfileError, CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            print(f"ตั้งค่าไม่พร้อม: {self._safe_error(exc)}", file=sys.stderr)
            return 2
        except Exception as exc:
            # Do not print exception bodies from HTTP/OAuth libraries: they can contain URLs or API data.
            print(f"คำสั่งทำงานไม่สำเร็จ ({type(exc).__name__})", file=sys.stderr)
            return 1
        return 2

    def _run_profile(self, args: argparse.Namespace) -> int:
        action = args.profile_command
        if action == "setup":
            return self._setup_profile()
        profile = self._load_profile()
        if profile is None:
            return 2
        if action == "show":
            self._show_profile(profile)
            return 0
        if action == "accept-policy":
            policy_url = (profile.privacy_policy_url or "").strip()
            parsed_policy_url = urlparse(policy_url)
            if parsed_policy_url.scheme != "https" or not parsed_policy_url.netloc:
                print("ตั้งค่า privacy policy URL แบบ HTTPS ที่เผยแพร่แล้วก่อนยอมรับนโยบาย", file=sys.stderr)
                return 2
            print(f"Privacy policy: {policy_url}")
            print(f"YouTube Terms of Service: {YOUTUBE_TERMS_URL}")
            print("โปรแกรมจะเก็บข้อมูล API ในเครื่องและต้องลบ/ปรับปรุงตามกำหนดในนโยบายความเป็นส่วนตัว")
            if input("พิมพ์ ยอมรับ เพื่อยืนยันว่าอ่านและยอมรับแล้ว: ").strip() != "ยอมรับ":
                print("ยังไม่ได้บันทึกการยอมรับ")
                return 2
            accepted_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            updated = replace(
                profile,
                policy_accepted_at=accepted_at,
                policy_version_accepted=POLICY_VERSION,
            )
            self._save_profile(updated)
            if updated.channel_id and updated.privacy_policy_url:
                self.store.record_policy_acceptance(
                    updated.channel_id, updated.privacy_policy_url, accepted_at, POLICY_VERSION
                )
            print(f"บันทึกการยอมรับนโยบายรุ่น {POLICY_VERSION} แล้ว")
            return 0
        if action == "set-privacy":
            updated = replace(profile, privacy_status=args.status)
            self._save_profile(updated)
            print(f"ตั้งค่าความเป็นส่วนตัวเริ่มต้นเป็น {args.status}")
            if args.status != "private" and not updated.api_audit_passed:
                print("การอัปโหลด Unlisted/Public ยังถูกปิดจนกว่าจะผ่าน YouTube API audit")
            return 0
        if action == "set-api-audit-status":
            updated = replace(profile, api_audit_passed=(args.status == "passed"))
            self._save_profile(updated)
            print(f"บันทึกสถานะ YouTube API audit: {args.status}")
            return 0
        if action == "set-asset-rights-status":
            updated = replace(profile, asset_rights_confirmed=(args.status == "confirmed"))
            self._save_profile(updated)
            print(f"บันทึกสถานะการรับรองสิทธิ์ assets: {args.status}")
            return 0
        if action == "approve-pilot":
            return self._approve_pilot(profile, args.video_id)
        if action == "delete-account-data":
            channel_id = args.channel_id or profile.channel_id
            if not channel_id:
                print("ระบุ --channel-id หรือกำหนด channel ID ในโปรไฟล์ก่อน", file=sys.stderr)
                return 2
            removed = self.store.delete_account_data(channel_id)
            print(f"ลบระเบียนในเครื่อง {removed} รายการสำหรับช่อง {channel_id} แล้ว")
            print("การทำงานนี้ไม่ได้ลบวิดีโอออกจาก YouTube")
            return 0
        if action == "revoke-authorization":
            channel_id = args.channel_id or profile.channel_id
            if not channel_id:
                print("ระบุ --channel-id หรือกำหนด channel ID ในโปรไฟล์ก่อน", file=sys.stderr)
                return 2
            return self._revoke(profile, channel_id)
        return 2

    def _setup_profile(self) -> int:
        if self.profile_store.path.exists():
            print(f"มีโปรไฟล์อยู่แล้ว: {self.profile_store.path}", file=sys.stderr)
            return 2
        print("สร้างโปรไฟล์ครั้งแรก (ไฟล์จะอยู่ใน LocalAppData ของ Windows)")
        alias = self._prompt_required("ชื่อหรือ handle ของช่อง YouTube")
        description = input("แม่แบบคำอธิบาย โดยใช้ {title} แทนชื่อวิดีโอ [{title}]: ").strip() or "{title}"
        shorts_suffix = input("ข้อความต่อท้ายชื่อ Shorts [ #Shorts]: ").strip() or " #Shorts"
        category_id = self._prompt_required("YouTube category ID")
        privacy = self._prompt_choice("ความเป็นส่วนตัวเริ่มต้น (private/unlisted/public)", {"private", "unlisted", "public"})
        tags = tuple(tag.strip() for tag in input("Tags คั่นด้วย comma (เว้นว่างได้): ").split(",") if tag.strip())
        made_for_kids = self._prompt_bool("เนื้อหานี้ทำเพื่อเด็กโดยเจตนาหรือไม่ (yes/no)")
        synthetic = self._prompt_bool("มีเนื้อหาสังเคราะห์/ดัดแปลงที่ต้องเปิดเผยหรือไม่ (yes/no)")
        official_artist = self._prompt_bool("ช่องนี้เป็น Official Artist Channel หรือไม่ (yes/no)")
        rights_confirmed = self._prompt_bool("คุณมีสิทธิ์ใช้เสียง ภาพ เกม และ overlay ในไฟล์ชุดนี้หรือไม่ (yes/no)")
        client_path = Path(self._prompt_required("พาธ Desktop OAuth JSON ของโปรเจกต์ mfk110 ใหม่"))
        policy_url = self._prompt_required("URL HTTPS ของ privacy policy ที่เผยแพร่แล้ว")

        profile = UploadProfile(
            channel_alias=alias,
            client_secrets_path=client_path,
            privacy_status=privacy,
            category_id=category_id,
            description_template=description,
            tags=tags,
            made_for_kids=made_for_kids,
            contains_synthetic_media=synthetic,
            is_official_artist_channel=official_artist,
            asset_rights_confirmed=rights_confirmed,
            shorts_title_suffix=shorts_suffix,
            privacy_policy_url=policy_url,
        )
        self.profile_store.save(profile)
        self.runner.profile = profile
        print(f"สร้างโปรไฟล์สำหรับ {profile.channel_alias} แล้ว แต่ยังไม่ได้ยอมรับ privacy policy หรือเชื่อม OAuth")
        return 0

    def _dry_run(self, folder: Path, channel: str) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        self.runner.profile = profile
        report = self.runner.dry_run(folder, channel)
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
        first_pilot = not profile.approved_pilot_video_id
        limit = 1 if first_pilot else args.limit
        force_private = True if first_pilot else args.force_private
        requested_privacy = "private" if force_private else profile.privacy_status
        # Consent and configuration are checked before loading OAuth credentials or opening a browser.
        validate_upload_profile(profile, requested_privacy=requested_privacy)
        credential_store = self._get_credential_store()
        credentials = credential_store.load(OWNER_ACCOUNT_KEY)
        if credentials is None:
            credentials = self.oauth.authorize(profile.client_secrets_path, credential_store)
        elif not getattr(credentials, "valid", True):
            credentials = self.oauth.refresh(OWNER_ACCOUNT_KEY, credential_store, credentials)
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
            if current_profile.channel_id and current_profile.privacy_policy_url and current_profile.policy_accepted_at:
                self.store.record_policy_acceptance(
                    channel.channel_id,
                    current_profile.privacy_policy_url,
                    current_profile.policy_accepted_at,
                    current_profile.policy_version_accepted or POLICY_VERSION,
                )
            print(f"ช่อง: {channel.display_name} ({channel.channel_id})")
            print(f"วิดีโอ: {video_count}")
            print(f"ข้าม: {skipped_count}")
            print(f"ความเป็นส่วนตัว: {privacy_status}")
            print(f"โปรไฟล์ revision: {self._profile_revision()}")
            print(f"Privacy policy revision: {current_profile.policy_version_accepted or 'ยังไม่ยอมรับ'}")
            print("คำประกาศของเจ้าของสำหรับ batch นี้:")
            print(f"สิทธิ์ assets: {'ยืนยัน' if current_profile.asset_rights_confirmed else 'ยังไม่ยืนยัน'}")
            print(f"Made for Kids: {'ใช่' if current_profile.made_for_kids else 'ไม่ใช่'}")
            print(f"Synthetic media: {'ใช่' if current_profile.contains_synthetic_media else 'ไม่ใช่'}")
            print(f"Official Artist Channel: {'ใช่' if current_profile.is_official_artist_channel else 'ไม่ใช่'}")
            print(f"โหมด: {'Private pilot' if first_pilot else 'batch'}")

        try:
            report = self.runner.upload(
                args.folder,
                requested_channel,
                limit=limit,
                force_private=force_private,
                on_preflight=report_preflight,
            )
        except Exception as exc:
            from .auth import ChannelResolutionError

            if isinstance(exc, ChannelResolutionError) and "ambiguous" in str(exc).casefold():
                clarified = input("ชื่อช่องซ้ำกัน กรุณาระบุ channel handle หรือ channel ID: ").strip()
                if not clarified:
                    return 2
                try:
                    report = self.runner.upload(
                        args.folder,
                        clarified,
                        limit=limit,
                        force_private=force_private,
                        on_preflight=report_preflight,
                    )
                except (ProfileError, PilotApprovalRequired, ValueError) as retry_exc:
                    print(f"ยกเลิกก่อนเริ่มอัปโหลด: {self._safe_error(retry_exc)}", file=sys.stderr)
                    return 2
                except Exception as retry_exc:
                    print(f"อัปโหลดไม่สำเร็จ ({type(retry_exc).__name__})", file=sys.stderr)
                    return 1
            elif isinstance(exc, (ProfileError, PilotApprovalRequired, ValueError)):
                print(f"ยกเลิกก่อนเริ่มอัปโหลด: {self._safe_error(exc)}", file=sys.stderr)
                return 2
            else:
                print(f"อัปโหลดไม่สำเร็จ ({type(exc).__name__})", file=sys.stderr)
                return 1

        self._print_report(report)
        if first_pilot:
            pilot = next((item for item in report.items if item.video_url and item.status.startswith("uploaded")), None)
            if pilot is not None:
                print(f"คลิปนำร่อง Private: {pilot.video_url}")
                print("ตรวจคลิปใน YouTube Studio แล้วจึงสั่ง profile approve-pilot --video-id <ID>")
        thumbnail_errors = any(item.status == "uploaded_thumbnail_failed" for item in report.items)
        if report.failed_count or report.pending_count or report.stopped_reason or thumbnail_errors:
            return 1
        return 0

    def _approve_pilot(self, profile: UploadProfile, video_id: str) -> int:
        if not profile.channel_id:
            print("ยังไม่มี channel ID ที่ยืนยันจาก OAuth", file=sys.stderr)
            return 2
        matching = [job for job in self.store.list_jobs(profile.channel_id) if job.video_id == video_id]
        if not matching or not any(
            job.state == "complete" and job.api_fields.get("privacy_status") == "private"
            for job in matching
        ):
            print("อนุมัติไม่ได้: ต้องเป็นคลิปที่อัปโหลดครบและยืนยันว่า Private แล้ว", file=sys.stderr)
            return 2
        self._save_profile(replace(profile, approved_pilot_video_id=video_id))
        print(f"บันทึกการตรวจคลิปนำร่อง {video_id} แล้ว คำสั่งอัปโหลดครั้งถัดไปจึงเริ่ม batch ได้")
        return 0

    def _revoke(self, profile: UploadProfile, channel_id: str) -> int:
        try:
            self._get_credential_store().revoke(OWNER_ACCOUNT_KEY)
        except CredentialRevocationError:
            self.store.delete_account_data(channel_id)
            print("ลบ token ในเครื่องและข้อมูล API ของช่องแล้ว แต่ยืนยันการยกเลิกกับ Google ไม่สำเร็จ", file=sys.stderr)
            print(f"กรุณาตรวจและยกเลิกสิทธิ์ที่ {GOOGLE_SECURITY_URL}", file=sys.stderr)
            return 1
        except CredentialStoreError as exc:
            self.store.delete_account_data(channel_id)
            print(f"จัดการ token ในเครื่องไม่สำเร็จ: {self._safe_error(exc)}", file=sys.stderr)
            return 1
        self.store.delete_account_data(channel_id)
        print(f"ยกเลิก OAuth และลบข้อมูล API ในเครื่องของช่อง {channel_id} แล้ว")
        print("การยกเลิก OAuth ไม่ได้ลบวิดีโอออกจาก YouTube")
        return 0

    def _maintenance_refresh(self) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        if not profile.channel_id:
            print("โปรไฟล์ยังไม่มี channel ID ที่ยืนยันแล้ว", file=sys.stderr)
            return 2
        validate_upload_profile(profile, requested_privacy="private")
        credential_store = self._get_credential_store()
        credentials = credential_store.load(OWNER_ACCOUNT_KEY)
        if credentials is None:
            print("ไม่พบ OAuth token; เชื่อมบัญชีใหม่ด้วยคำสั่ง upload หลังตรวจโปรไฟล์แล้ว", file=sys.stderr)
            return 1
        try:
            if not getattr(credentials, "valid", True):
                credentials = self.oauth.refresh(OWNER_ACCOUNT_KEY, credential_store, credentials)
            api = self.oauth.build_api(credentials, self.store)
            self.runner.api = api
            owned = api.list_owned_channels()
            if not any(item.channel_id == profile.channel_id for item in owned):
                self.store.delete_account_data(profile.channel_id)
                self._save_profile(replace(profile, channel_id=None, approved_pilot_video_id=None))
                print("บัญชีนี้ไม่มีสิทธิ์จัดการช่องที่บันทึกไว้แล้ว; ลบข้อมูล API ในเครื่องและหยุด maintenance", file=sys.stderr)
                return 1

            now = datetime.now(timezone.utc)
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
                    }.items()
                    if isinstance(value, str)
                }
                self.store.refresh_api_record(job.id, now, fields)
                refreshed_count += 1
            purged_count = self.store.purge_expired_api_records(now)
            print(f"ปรับปรุงข้อมูล API {refreshed_count} รายการ; ลบข้อมูลที่หมดอายุ {purged_count} รายการ")
            return 0
        except AuthorizationRevokedError as exc:
            self.store.delete_account_data(profile.channel_id)
            print(f"OAuth ถูกยกเลิกหรือหมดอายุ; ลบข้อมูล API และหยุด maintenance: {self._safe_error(exc)}", file=sys.stderr)
            return 1
        except Exception as exc:
            self.store.purge_expired_api_records(datetime.now(timezone.utc))
            print(f"maintenance หยุดโดยไม่ทำงานต่อ ({type(exc).__name__})", file=sys.stderr)
            return 1

    def _load_profile(self) -> UploadProfile | None:
        try:
            profile = self.profile_store.load()
        except ProfileError as exc:
            print(self._safe_error(exc), file=sys.stderr)
            return None
        self.runner.profile = profile
        return profile

    def _save_profile(self, profile: UploadProfile) -> None:
        self.profile_store.save(profile)
        self.runner.profile = profile

    def _get_credential_store(self) -> CredentialStore:
        if self.credential_store is None:
            self.credential_store = self._credential_store_factory()
        return self.credential_store

    @staticmethod
    def _show_profile(profile: UploadProfile) -> None:
        print(f"ช่อง: {profile.channel_alias}")
        print(f"Channel ID: {profile.channel_id or 'ยังไม่ได้ยืนยัน'}")
        print(f"ความเป็นส่วนตัวเริ่มต้น: {profile.privacy_status}")
        print(f"YouTube API audit: {'ผ่าน' if profile.api_audit_passed else 'ยังไม่ผ่าน'}")
        print(f"Policy: {profile.policy_version_accepted or 'ยังไม่ยอมรับ'}")
        print(f"OAuth client path: {profile.client_secrets_path or 'ยังไม่ได้ตั้งค่า'}")
        print(f"สิทธิ์ assets: {'ยืนยัน' if profile.asset_rights_confirmed else 'ยังไม่ยืนยัน'}")
        print("ไม่แสดง OAuth token หรือ client secret")

    def _profile_revision(self) -> str:
        try:
            modified = self.profile_store.path.stat().st_mtime
        except (AttributeError, OSError):
            return "ยังไม่บันทึกบนดิสก์"
        return datetime.fromtimestamp(modified, timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _print_report(report: BatchReport) -> None:
        print(
            "ผลรอบนี้: "
            f"อัปโหลด/วิดีโอสำเร็จ {report.uploaded_count}, "
            f"ข้าม {report.skipped_count}, ผิดพลาด {report.failed_count}, "
            f"รออยู่ {report.pending_count}"
        )
        if report.stopped_reason:
            print(f"หยุดคิว: {report.stopped_reason}")
        for item in report.items:
            if item.status.startswith("uploaded") and item.video_url:
                error = f"; error={item.error_code}" if item.error_code else ""
                print(f"{item.status} ({item.actual_visibility or 'unknown'}): {item.video_url}{error}")
            elif item.status in {"failed", "pending_quota"}:
                print(f"{item.status}: {item.source_path.name} ({item.error_code or 'ไม่มีรหัสข้อผิดพลาด'})")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        # Whitelist local validation messages; do not leak API response bodies or OAuth URLs.
        if isinstance(exc, (ProfileError, CredentialStoreError, AuthorizationRequiredError, ValueError, OSError)):
            return str(exc)
        return type(exc).__name__

    @staticmethod
    def _prompt_required(label: str) -> str:
        while True:
            value = input(f"{label}: ").strip()
            if value:
                return value
            print("กรุณากรอกค่านี้")

    @staticmethod
    def _prompt_choice(label: str, choices: set[str]) -> str:
        while True:
            value = input(f"{label}: ").strip().casefold()
            if value in choices:
                return value
            print(f"เลือกได้เฉพาะ {', '.join(sorted(choices))}")

    @staticmethod
    def _prompt_bool(label: str) -> bool:
        while True:
            value = input(f"{label}: ").strip().casefold()
            if value in {"yes", "y", "ใช่"}:
                return True
            if value in {"no", "n", "ไม่ใช่"}:
                return False
            print("ตอบ yes หรือ no")


def main(argv: list[str] | None = None) -> int:
    profile_store = ProfileStore()
    store = JobStore()
    try:
        profile = profile_store.load()
    except ProfileError:
        profile = UploadProfile(channel_alias="ยังไม่ได้ตั้งค่า")
    runner = BatchRunner(profile, store, None, profile_store=profile_store)
    return CliApp(
        runner=runner,
        profile_store=profile_store,
        credential_store=None,
        oauth_service=OAuthService(),
        store=store,
    ).run(list(sys.argv[1:] if argv is None else argv))
