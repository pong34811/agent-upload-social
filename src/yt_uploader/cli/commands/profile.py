"""``profile`` commands: list, setup, show, privacy, retry, and data/OAuth removal."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ...auth import (
    OWNER_ACCOUNT_KEY,
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    CredentialRevocationError,
    CredentialStoreError,
)
from ...config.profile import ProfileError, ProfileStore, selectable_profile_paths
from ...jobs.store import JobStateError
from ...models import UploadProfile
from ...paths import CLIENT_SECRETS_PATH
from ..output import profile_payload

GOOGLE_SECURITY_URL = "https://security.google.com/settings/security/permissions"


class ProfileCommands:
    def _list_profiles(self) -> int:
        root = self.profile_root
        profiles = selectable_profile_paths(root)
        if not profiles:
            if (root / "profile.json").exists():
                self._err("อ่านโปรไฟล์ profile.json ไม่ได้")
                return 2
            print("ยังไม่มีโปรไฟล์ที่บันทึกไว้")
            self.result["profiles"] = []
            return 0

        print("โปรไฟล์ที่บันทึกไว้:")
        listed: list[dict] = []
        self.result["profiles"] = listed
        for name, path in profiles:
            try:
                profile = ProfileStore(path).load()
            except ProfileError:
                print(f"  {name}: ไฟล์โปรไฟล์อ่านไม่ได้")
                listed.append({"name": name, "readable": False})
                continue
            listed.append({"name": name, "readable": True, **profile_payload(profile)})
            print(
                f"  {name}: {profile.channel_alias} | "
                f"Channel ID: {profile.channel_id or 'ยังไม่ได้ยืนยัน'} | "
                f"OAuth account: {profile.oauth_account_key}"
            )
        return 0

    def _run_profile(self, args: argparse.Namespace) -> int:
        action = args.profile_command
        if action == "setup":
            return self._setup_profile(args.client_secrets, args.oauth_account, args.replace_existing)
        profile = self._load_profile()
        if profile is None:
            return 2
        if action == "show":
            self._show_profile(profile)
            self.result["settings"] = profile_payload(profile)
            return 0
        if action == "set-privacy":
            updated = replace(profile, privacy_status=args.status)
            self._save_profile(updated)
            print(f"ตั้งค่าความเป็นส่วนตัวเริ่มต้นเป็น {args.status}")
            return 0
        if action == "set-api-audit-status":
            updated = replace(profile, api_audit_passed=(args.status == "passed"))
            self._save_profile(updated)
            print(f"บันทึกข้อมูล audit เดิม: {args.status} (ไม่มีผลต่อการเรียก API)")
            return 0
        if action == "delete-account-data":
            channel_id = args.channel_id or profile.channel_id
            if not channel_id:
                self._err("ระบุ --channel-id หรือกำหนด channel ID ในโปรไฟล์ก่อน")
                return 2
            removed = self._delete_account_data(profile, channel_id)
            print(f"ลบระเบียนในเครื่อง {removed} รายการสำหรับช่อง {channel_id} แล้ว")
            print("ลบ channel ID ที่เก็บไว้ในโปรไฟล์ของช่องนี้แล้ว")
            print("การทำงานนี้ไม่ได้ลบวิดีโอออกจาก YouTube")
            return 0
        if action == "retry-failed":
            return self._retry_failed(profile, args.path)
        if action == "revoke-authorization":
            channel_id = args.channel_id or profile.channel_id
            if not channel_id:
                self._err("ระบุ --channel-id หรือกำหนด channel ID ในโปรไฟล์ก่อน")
                return 2
            return self._revoke(profile, channel_id)
        return 2

    def _setup_profile(
        self,
        client_secrets_path: Path | None = None,
        oauth_account_key: str = OWNER_ACCOUNT_KEY,
        replace_existing: bool = False,
    ) -> int:
        client_path = Path(client_secrets_path or CLIENT_SECRETS_PATH).expanduser().resolve()
        if not client_path.is_file():
            self._err(f"ไม่พบ Desktop OAuth JSON: {client_path}")
            return 2

        if self.profile_store.path.exists():
            if not replace_existing:
                self._err(f"มีโปรไฟล์อยู่แล้ว: {self.profile_store.path}; ใช้ --replace-existing หากต้องการตั้งค่าช่องใหม่")
                return 2
            backup_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = self.profile_store.path.with_name(
                f"{self.profile_store.path.name}.backup-{backup_stamp}"
            )
            try:
                shutil.copy2(self.profile_store.path, backup_path)
            except OSError as exc:
                self._err(f"สำรองโปรไฟล์เดิมไม่ได้: {self._safe_error(exc)}")
                return 2
            print(f"เก็บสำเนาโปรไฟล์เดิมไว้ที่ {backup_path}")

        print("ตั้งค่า OAuth และโปรไฟล์สำหรับอัปโหลด (คำสั่งนี้จะไม่อัปโหลดวิดีโอ)")
        credential_store = self._get_credential_store()
        try:
            credentials = credential_store.load(oauth_account_key)
            if credentials is None:
                print(f"ยังไม่มี OAuth credential '{oauth_account_key}'; กำลังเปิด Google OAuth")
                credentials = self._authorize_for_account(client_path, credential_store, oauth_account_key)
            elif not getattr(credentials, "valid", True):
                print("กำลังต่ออายุ OAuth credential ที่บันทึกไว้")
                credentials = self.oauth.refresh(oauth_account_key, credential_store, credentials)
            else:
                print("ใช้ OAuth credential ที่บันทึกไว้แล้ว")
        except AuthorizationRevokedError as exc:
            self._err(f"OAuth ใช้ต่อไม่ได้: {self._safe_error(exc)}")
            return 1
        except (CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"เตรียม OAuth ไม่สำเร็จ: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            self._err(f"เตรียม OAuth ไม่สำเร็จ ({type(exc).__name__})")
            return 1

        try:
            api = self.oauth.build_api(credentials, self.store)
            channels = api.list_owned_channels()
        except AuthorizationRevokedError as exc:
            try:
                credential_store.delete(oauth_account_key)
            except CredentialStoreError:
                pass
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ: {self._safe_error(exc)}")
            return 1
        except (CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"อ่านรายชื่อช่องไม่ได้: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            self._err(f"อ่านรายชื่อช่องไม่ได้ ({type(exc).__name__})")
            return 1

        if not channels:
            self._err("ไม่พบบัญชี YouTube channel ที่บัญชี Google นี้จัดการได้")
            return 2

        print("เลือกช่องที่จะตั้งค่า:")
        for index, channel in enumerate(channels, start=1):
            identity = channel.handle or channel.channel_id
            print(f"  {index}. {channel.display_name} ({identity})")
        selected_channel = channels[self._prompt_index("หมายเลขช่อง", len(channels))]

        description = input("แม่แบบคำอธิบาย โดยใช้ {title} แทนชื่อวิดีโอ [{title}]: ").strip() or "{title}"
        shorts_suffix = input("ข้อความต่อท้ายชื่อ Shorts [ #Shorts]: ").strip() or " #Shorts"
        category_id = self._prompt_required("YouTube category ID")
        privacy = self._prompt_choice("ความเป็นส่วนตัวเริ่มต้น (private/unlisted/public)", {"private", "unlisted", "public"})
        tags = tuple(tag.strip() for tag in input("Tags คั่นด้วย comma (เว้นว่างได้): ").split(",") if tag.strip())
        made_for_kids = self._prompt_bool("เนื้อหานี้ทำเพื่อเด็กโดยเจตนาหรือไม่ (yes/no)")
        synthetic = self._prompt_bool("มีเนื้อหาสังเคราะห์/ดัดแปลงที่ต้องเปิดเผยหรือไม่ (yes/no)")
        official_artist = self._prompt_bool("ช่องนี้เป็น Official Artist Channel หรือไม่ (yes/no)")
        profile = UploadProfile(
            channel_alias=selected_channel.display_name,
            client_secrets_path=client_path,
            oauth_account_key=oauth_account_key,
            channel_id=selected_channel.channel_id,
            privacy_status=privacy,
            category_id=category_id,
            description_template=description,
            tags=tags,
            made_for_kids=made_for_kids,
            contains_synthetic_media=synthetic,
            is_official_artist_channel=official_artist,
            shorts_title_suffix=shorts_suffix,
        )
        self.profile_store.save(profile)
        self.runner.profile = profile
        print(f"ตั้งค่าโปรไฟล์สำหรับ {selected_channel.display_name} แล้ว; พร้อมอัปโหลด")
        print("ยังไม่ได้อัปโหลดวิดีโอ; สั่ง upload เมื่อพร้อม")
        return 0

    def _revoke(self, profile: UploadProfile, channel_id: str) -> int:
        if profile.channel_id and profile.channel_id != channel_id:
            self._err(f"Channel ID ไม่ตรงกับโปรไฟล์ ({profile.channel_id}); ยกเลิกก่อนแตะ OAuth หรือข้อมูลในเครื่อง")
            return 2
        try:
            self._get_credential_store().revoke(profile.oauth_account_key)
        except CredentialRevocationError:
            self._delete_account_data(profile, channel_id)
            self._err("ลบ token ในเครื่องและข้อมูล API ของช่องแล้ว แต่ยืนยันการยกเลิกกับ Google ไม่สำเร็จ")
            self._err(f"กรุณาตรวจและยกเลิกสิทธิ์ที่ {GOOGLE_SECURITY_URL}")
            return 1
        except CredentialStoreError as exc:
            self._delete_account_data(profile, channel_id)
            self._err(f"จัดการ token ในเครื่องไม่สำเร็จ: {self._safe_error(exc)}")
            return 1
        self._delete_account_data(profile, channel_id)
        print(f"ยกเลิก OAuth และลบข้อมูล API ในเครื่องของช่อง {channel_id} แล้ว")
        print("การยกเลิก OAuth ไม่ได้ลบวิดีโอออกจาก YouTube")
        return 0

    def _delete_account_data(self, profile: UploadProfile, channel_id: str) -> int:
        removed = self.store.delete_account_data(channel_id)
        if profile.channel_id == channel_id:
            self._save_profile(replace(
                profile,
                channel_id=None,
            ))
        return removed

    def _retry_failed(self, profile: UploadProfile, path: Path) -> int:
        if not profile.channel_id:
            self._err("โปรไฟล์ยังไม่มี channel ID ที่ยืนยันแล้ว")
            return 2
        try:
            job = self.runner.requeue_failed(path, profile.channel_id)
        except (JobStateError, ProfileError, ValueError, OSError) as exc:
            self._err(f"เตรียมลองใหม่ไม่ได้: {self._safe_error(exc)}")
            return 2
        print(f"ไฟล์ {job.path.name} พร้อมลองใหม่ โดยคงตัวตน hash/channel เดิมไว้")
        print("รันคำสั่ง upload สำหรับโฟลเดอร์เดิมเพื่อส่งต่อจากงานที่เตรียมไว้นี้")
        return 0

    @staticmethod
    def _show_profile(profile: UploadProfile) -> None:
        print(f"ช่อง: {profile.channel_alias}")
        print(f"Channel ID: {profile.channel_id or 'ยังไม่ได้ยืนยัน'}")
        print(f"OAuth account: {profile.oauth_account_key}")
        print(f"ความเป็นส่วนตัวเริ่มต้น: {profile.privacy_status}")
        print(f"OAuth client path: {profile.client_secrets_path or 'ยังไม่ได้ตั้งค่า'}")
        print("ไม่แสดง OAuth token หรือ client secret")

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
    def _prompt_index(label: str, item_count: int) -> int:
        while True:
            value = input(f"{label} (1-{item_count}): ").strip()
            if value.isdigit() and 1 <= int(value) <= item_count:
                return int(value) - 1
            print(f"เลือกหมายเลข 1 ถึง {item_count}")

    @staticmethod
    def _prompt_bool(label: str) -> bool:
        while True:
            value = input(f"{label}: ").strip().casefold()
            if value in {"yes", "y", "ใช่"}:
                return True
            if value in {"no", "n", "ไม่ใช่"}:
                return False
            print("ตอบ yes หรือ no")
