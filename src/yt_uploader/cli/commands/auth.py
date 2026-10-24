"""``auth`` commands and the shared credential load/authorize/revoke helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ...auth import (
    OWNER_ACCOUNT_KEY,
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    CredentialStore,
    CredentialStoreError,
    resolve_channel,
)
from ...config.profile import ProfileError, validate_upload_profile
from ...models import UploadProfile


class AuthCommands:
    def _auth_login(self, requested_channel: str) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        # Validate owner-supplied channel settings before any OAuth or API request.
        validate_upload_profile(profile, requested_privacy="private")
        credential_store = self._get_credential_store()
        try:
            credentials = credential_store.load(profile.oauth_account_key)
            if credentials is None:
                credentials = self._authorize_for_account(
                    profile.client_secrets_path, credential_store, profile.oauth_account_key
                )
            elif not getattr(credentials, "valid", True):
                credentials = self.oauth.refresh(profile.oauth_account_key, credential_store, credentials)

            api = self.oauth.build_api(credentials, self.store)
            channel = resolve_channel(requested_channel, api.list_owned_channels())
        except AuthorizationRevokedError as exc:
            self._handle_revoked_authorization(profile)
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ; ลบข้อมูล API ในเครื่อง: {self._safe_error(exc)}")
            return 1
        except (ProfileError, CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"เชื่อมช่องไม่ได้: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            self._err(f"เชื่อมช่องไม่สำเร็จ ({type(exc).__name__})")
            return 1

        print(f"เชื่อมบัญชีและยืนยันช่อง: {channel.display_name} ({channel.channel_id})")
        token_name = credential_store.credential_path(profile.oauth_account_key).name
        print(f"OAuth credential บันทึกใน {token_name} แล้ว; ไม่มีการอัปโหลดวิดีโอ")
        return 0

    def _auth_token(self, client_secrets_path: Path, account_key: str = OWNER_ACCOUNT_KEY) -> int:
        """Create a local OAuth grant without performing YouTube API operations."""
        client_path = Path(client_secrets_path).expanduser().resolve()
        if not client_path.is_file():
            self._err(f"ไม่พบ Desktop OAuth JSON: {client_path}")
            return 2

        credential_store = self._get_credential_store()
        try:
            credentials = credential_store.load(account_key)
            if credentials is not None and getattr(credentials, "valid", True):
                print(f"OAuth credential '{account_key}' ใช้งานได้อยู่แล้ว; ไม่เปิด browser ซ้ำ")
                if account_key == OWNER_ACCOUNT_KEY:
                    print("หากต้องการเพิ่มบัญชี Google อีกบัญชี ให้รันซ้ำด้วย --account ชื่อใหม่ เช่น --account channel2")
                return 0
            if credentials is not None:
                print(f"กำลังต่ออายุ OAuth credential '{account_key}' ที่บันทึกไว้")
                self.oauth.refresh(account_key, credential_store, credentials)
                print("ต่ออายุ OAuth credential สำเร็จ; ไม่มีการเรียก YouTube API")
                return 0
            else:
                self._authorize_for_account(client_path, credential_store, account_key)
        except AuthorizationRevokedError as exc:
            self._err(f"OAuth ถูกยกเลิกหรือหมดอายุ: {self._safe_error(exc)}")
            return 1
        except (CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"สร้าง OAuth credential ไม่ได้: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            self._err(f"OAuth ไม่สำเร็จ ({type(exc).__name__})")
            return 1

        token_name = credential_store.credential_path(account_key).name
        print(f"สร้าง OAuth credential '{account_key}' สำเร็จและบันทึกใน {token_name} แล้ว")
        print("ขั้นตอนนี้ไม่มีการเรียก YouTube API หรืออัปโหลดวิดีโอ")
        return 0

    def _auth_reauthorize(self) -> int:
        profile = self._load_profile()
        if profile is None:
            return 2
        if profile.client_secrets_path is None:
            self._err("โปรไฟล์ยังไม่มี Desktop OAuth JSON")
            return 2
        credential_store = self._get_credential_store()
        try:
            self._authorize_for_account(
                profile.client_secrets_path, credential_store, profile.oauth_account_key
            )
            if not credential_store.has_required_scopes(profile.oauth_account_key):
                self._err("Google ยังไม่ได้มอบ scope ที่ต้องใช้; ยังตั้งเวลาไม่ได้")
                return 2
        except (CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"ขอ OAuth consent ใหม่ไม่สำเร็จ: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            self._err(f"OAuth ไม่สำเร็จ ({type(exc).__name__})")
            return 1
        print(f"เชื่อม OAuth ใหม่สำหรับ account '{profile.oauth_account_key}' แล้ว")
        print("เพิ่มสิทธิ์สำหรับแก้ metadata แล้ว; ไม่มีการอัปโหลดหรือเปลี่ยนวิดีโอ")
        return 0

    def _handle_revoked_authorization(self, profile: UploadProfile) -> None:
        try:
            self._get_credential_store().delete(profile.oauth_account_key)
        except CredentialStoreError as exc:
            self._err(f"ลบ OAuth token ในเครื่องไม่สำเร็จ: {self._safe_error(exc)}")

        saved_profile = self._load_profile() or profile
        runner_channel = getattr(getattr(self, "runner", None), "profile", None)
        runner_channel_id = getattr(runner_channel, "channel_id", None)
        channel_id = saved_profile.channel_id or profile.channel_id or runner_channel_id
        if channel_id:
            if saved_profile.channel_id != channel_id:
                saved_profile = replace(saved_profile, channel_id=channel_id)
            self._delete_account_data(saved_profile, channel_id)

    def _get_credential_store(self) -> CredentialStore:
        if self.credential_store is None:
            self.credential_store = self._credential_store_factory()
        return self.credential_store

    def _authorize_for_account(
        self, client_secrets_path: Path, credential_store: CredentialStore, account_key: str
    ) -> Any:
        if account_key == OWNER_ACCOUNT_KEY:
            return self.oauth.authorize(client_secrets_path, credential_store)
        return self.oauth.authorize(client_secrets_path, credential_store, account_key)

    def _auth_accounts(self) -> int:
        try:
            account_keys = self._get_credential_store().list_account_keys()
        except CredentialStoreError as exc:
            self._err(f"อ่านรายการ OAuth ไม่สำเร็จ: {self._safe_error(exc)}")
            return 2
        self.result["accounts"] = account_keys
        if not account_keys:
            print("ยังไม่มี OAuth credential ที่บันทึกไว้")
            return 0
        print("OAuth account ที่บันทึกไว้:")
        for account_key in account_keys:
            print(f"  {account_key}")
        return 0
