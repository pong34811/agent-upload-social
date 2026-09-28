"""Desktop OAuth, Windows credential storage, and owned-channel selection."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import keyring
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CREDENTIAL_SERVICE = "Katy404 YouTube Uploader"
OWNER_ACCOUNT_KEY = "owner"
TOKEN_REVOCATION_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)
OAUTH_AUTHORIZATION_TIMEOUT_SECONDS = 600
TOKEN_FILENAME = "token_waritnan34811.json"
_ACCOUNT_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")


class CredentialStoreError(RuntimeError):
    """Raised when credentials cannot be safely stored or loaded."""


class CredentialRevocationError(RuntimeError):
    """Raised when Google's token revocation endpoint could not be reached."""


class OAuthConfigurationError(ValueError):
    """Raised when the OAuth client file is not a valid upload project client."""


class AuthorizationRequiredError(RuntimeError):
    """Raised when user consent is needed again before API access can continue."""


class AuthorizationRevokedError(AuthorizationRequiredError):
    """Raised when Google reports that the stored grant is no longer valid."""


class ChannelResolutionError(ValueError):
    """Raised when a requested channel is not an exact, unique owned channel."""


@dataclass(frozen=True, slots=True)
class ChannelRef:
    channel_id: str
    display_name: str
    handle: str | None = None


class CredentialStore:
    """Store OAuth credentials in separate ignored files for each account.

    ``backend`` remains available for isolated tests and legacy callers. Normal
    application runs use the file store so tokens stay beside this project and
    are excluded by ``.gitignore``.
    """

    def __init__(self, backend: Any | None = None, path: Path | None = None) -> None:
        self._backend = backend
        self.path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / TOKEN_FILENAME

    def _account_path(self, account_key: str) -> Path:
        self._validate_account_key(account_key)
        if account_key == OWNER_ACCOUNT_KEY:
            return self.path
        return self.path.with_name(f"token_{account_key}.json")

    def credential_path(self, account_key: str) -> Path:
        """Return the ignored token file path for a named account."""
        return self._account_path(account_key)

    def _load_file_data(self, path: Path | None = None) -> dict[str, Any] | None:
        path = self.path if path is None else path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("Could not read the local OAuth token file") from exc
        if not isinstance(data, dict):
            raise CredentialStoreError("Local OAuth token file must contain a JSON object")
        return data

    def _save_file_data(self, data: dict[str, Any], path: Path | None = None) -> None:
        path = self.path if path is None else path
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise CredentialStoreError("Could not store the local OAuth token file") from exc

    @staticmethod
    def _is_legacy_credential(data: dict[str, Any]) -> bool:
        return "token" in data or "refresh_token" in data

    @staticmethod
    def _validate_account_key(account_key: str) -> None:
        if not isinstance(account_key, str) or not _ACCOUNT_KEY_PATTERN.fullmatch(account_key):
            raise CredentialStoreError(
                "OAuth account name must be 1-40 letters, numbers, underscores, or hyphens"
            )

    def list_account_keys(self) -> list[str]:
        """Return stored account labels only; move old named entries into separate files."""
        if self._backend is not None:
            return []
        data = self._load_file_data()
        account_keys: set[str] = set()
        if data is not None and self._is_legacy_credential(data):
            account_keys = {OWNER_ACCOUNT_KEY}
        elif data is not None:
            account_keys = {
                key for key, value in data.items()
                if isinstance(key, str)
                and _ACCOUNT_KEY_PATTERN.fullmatch(key)
                and isinstance(value, dict)
                and self._is_legacy_credential(value)
            }
            for account_key in sorted(account_keys - {OWNER_ACCOUNT_KEY}):
                self._migrate_combined_account(account_key)

        try:
            for token_path in self.path.parent.glob("token_*.json"):
                if token_path == self.path:
                    continue
                account_key = token_path.stem.removeprefix("token_")
                if account_key != OWNER_ACCOUNT_KEY and _ACCOUNT_KEY_PATTERN.fullmatch(account_key):
                    account_keys.add(account_key)
        except OSError as exc:
            raise CredentialStoreError("Could not list local OAuth token files") from exc
        return sorted(account_keys)

    def _migrate_combined_account(self, account_key: str) -> None:
        """Split one named credential out of the earlier multi-account JSON file."""
        if account_key == OWNER_ACCOUNT_KEY:
            return
        data = self._load_file_data()
        if data is None or self._is_legacy_credential(data):
            return
        credential_data = data.get(account_key)
        if not isinstance(credential_data, dict) or not self._is_legacy_credential(credential_data):
            return

        account_path = self._account_path(account_key)
        existing_account_data = self._load_file_data(account_path)
        if existing_account_data is None or not self._is_legacy_credential(existing_account_data):
            self._save_file_data(credential_data, account_path)

        del data[account_key]
        if not data:
            self.path.unlink(missing_ok=True)
        elif set(data) == {OWNER_ACCOUNT_KEY} and isinstance(data[OWNER_ACCOUNT_KEY], dict):
            self._save_file_data(data[OWNER_ACCOUNT_KEY])
        else:
            self._save_file_data(data)

    def load(self, account_key: str) -> Credentials | None:
        self._validate_account_key(account_key)
        if self._backend is not None:
            try:
                serialized = self._backend.get_password(CREDENTIAL_SERVICE, account_key)
            except Exception as exc:
                raise CredentialStoreError("Could not read legacy credential storage") from exc
            if serialized is None:
                return None
            try:
                data = json.loads(serialized)
                serialized_data = dict(data)
                serialized_data.pop("_kt404_granted_scopes", None)
                return Credentials.from_authorized_user_info(serialized_data)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CredentialStoreError("Stored OAuth credential data is invalid") from exc

        account_path = self._account_path(account_key)
        data = self._load_file_data(account_path)
        if data is None and account_key != OWNER_ACCOUNT_KEY:
            self._migrate_combined_account(account_key)
            data = self._load_file_data(account_path)
        if data is None:
            return None
        # Accept the original single-credential file and the previous wrapped shape.
        serialized_data: Any = data if self._is_legacy_credential(data) else data.get(account_key)
        if serialized_data is None:
            return None
        try:
            serialized_data = dict(serialized_data)
            serialized_data.pop("_kt404_granted_scopes", None)
            return Credentials.from_authorized_user_info(serialized_data)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("Stored OAuth credential data is invalid") from exc

    def has_required_scopes(self, account_key: str) -> bool:
        """Check stored granted scopes without returning credential contents."""
        self._validate_account_key(account_key)
        if self._backend is not None:
            try:
                serialized = self._backend.get_password(CREDENTIAL_SERVICE, account_key)
            except Exception as exc:
                raise CredentialStoreError("Could not read legacy credential storage") from exc
            if serialized is None:
                return False
            try:
                account_data = json.loads(serialized)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise CredentialStoreError("Stored OAuth credential data is invalid") from exc
        else:
            account_path = self._account_path(account_key)
            data = self._load_file_data(account_path)
            if data is None and account_key != OWNER_ACCOUNT_KEY:
                self._migrate_combined_account(account_key)
                data = self._load_file_data(account_path)
            if data is None:
                return False
            account_data = data if self._is_legacy_credential(data) else data.get(account_key)
        if not isinstance(account_data, dict):
            return False
        # Requested scopes are not proof of consent. Only authorize_desktop writes
        # this marker after the completed consent response confirms the grant.
        scopes_value = account_data.get("_kt404_granted_scopes")
        if isinstance(scopes_value, str):
            granted = set(scopes_value.split())
        elif isinstance(scopes_value, (list, tuple)):
            granted = {scope for scope in scopes_value if isinstance(scope, str)}
        else:
            return False
        if "https://www.googleapis.com/auth/youtube" in granted:
            return True
        return set(SCOPES).issubset(granted)

    def save(
        self,
        account_key: str,
        credentials: Credentials,
        *,
        granted_scopes: Sequence[str] | None = None,
    ) -> None:
        self._validate_account_key(account_key)
        try:
            serialized = credentials.to_json()
            if not isinstance(serialized, str) or not serialized:
                raise ValueError("empty credential serialization")
            data = json.loads(serialized)
            if not isinstance(data, dict):
                raise ValueError("credential JSON must be an object")
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("OAuth credential data is invalid") from exc

        if self._backend is not None:
            try:
                existing_serialized = self._backend.get_password(CREDENTIAL_SERVICE, account_key)
                existing_data = json.loads(existing_serialized) if existing_serialized else {}
                if granted_scopes is not None:
                    values = granted_scopes.split() if isinstance(granted_scopes, str) else granted_scopes
                    data["_kt404_granted_scopes"] = sorted(set(values))
                elif isinstance(existing_data, dict) and "_kt404_granted_scopes" in existing_data:
                    data["_kt404_granted_scopes"] = existing_data["_kt404_granted_scopes"]
                self._backend.set_password(
                    CREDENTIAL_SERVICE, account_key, json.dumps(data, ensure_ascii=True, separators=(",", ":"))
                )
            except Exception as exc:
                raise CredentialStoreError("Could not store legacy credential data") from exc
            return

        if granted_scopes is not None:
            values = granted_scopes.split() if isinstance(granted_scopes, str) else granted_scopes
            data["_kt404_granted_scopes"] = sorted(set(values))
        else:
            existing_data = self._load_file_data(self._account_path(account_key))
            if isinstance(existing_data, dict) and not self._is_legacy_credential(existing_data):
                existing_data = existing_data.get(account_key)
            if existing_data is None:
                combined = self._load_file_data()
                existing_data = (
                    combined.get(account_key)
                    if isinstance(combined, dict) and not self._is_legacy_credential(combined)
                    else None
                )
            if isinstance(existing_data, dict) and "_kt404_granted_scopes" in existing_data:
                data["_kt404_granted_scopes"] = existing_data["_kt404_granted_scopes"]

        if account_key == OWNER_ACCOUNT_KEY:
            existing = self._load_file_data() or {}
            if not existing or self._is_legacy_credential(existing):
                self._save_file_data(data)
            else:
                existing[OWNER_ACCOUNT_KEY] = data
                self._save_file_data(existing)
            return

        self._migrate_combined_account(account_key)
        self._save_file_data(data, self._account_path(account_key))

    def delete(self, account_key: str) -> None:
        self._validate_account_key(account_key)
        if self._backend is not None:
            try:
                self._backend.delete_password(CREDENTIAL_SERVICE, account_key)
            except Exception as exc:
                # A missing entry is already the desired local state.
                if "not found" not in str(exc).casefold() and "no password" not in str(exc).casefold():
                    raise CredentialStoreError("Could not delete legacy credential data") from exc
            return

        if account_key != OWNER_ACCOUNT_KEY:
            try:
                self._account_path(account_key).unlink(missing_ok=True)
            except OSError as exc:
                raise CredentialStoreError("Could not delete the local OAuth token file") from exc
        data = self._load_file_data()
        if data is None:
            return
        if self._is_legacy_credential(data):
            if account_key != OWNER_ACCOUNT_KEY:
                return
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise CredentialStoreError("Could not delete the local OAuth token file") from exc
            return
        if account_key in data:
            del data[account_key]
            if data:
                if set(data) == {OWNER_ACCOUNT_KEY} and isinstance(data[OWNER_ACCOUNT_KEY], dict):
                    self._save_file_data(data[OWNER_ACCOUNT_KEY])
                else:
                    self._save_file_data(data)
            else:
                try:
                    self.path.unlink(missing_ok=True)
                except OSError as exc:
                    raise CredentialStoreError("Could not delete the local OAuth token file") from exc

    def revoke(self, account_key: str) -> None:
        credentials = self.load(account_key)
        token = None if credentials is None else (credentials.refresh_token or credentials.token)
        if token:
            try:
                response = requests.post(TOKEN_REVOCATION_URL, data={"token": token}, timeout=10)
                response.raise_for_status()
            except requests.RequestException as exc:
                self.delete(account_key)
                raise CredentialRevocationError(
                    "Google token revocation could not be confirmed; local credentials were deleted. "
                    "Revoke access from Google Security settings."
                ) from exc
        self.delete(account_key)


def _validate_desktop_client(client_secrets_path: Path) -> None:
    client_secrets_path = Path(client_secrets_path)
    try:
        data = json.loads(client_secrets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthConfigurationError("Could not read Desktop OAuth client file") from exc
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, dict):
        raise OAuthConfigurationError("OAuth client must use the Desktop installed-app format")


def authorize_desktop(
    client_secrets_path: Path,
    credential_store: CredentialStore,
    *,
    account_key: str = OWNER_ACCOUNT_KEY,
    on_authorization_started: Callable[[], None] | None = None,
) -> Credentials:
    """Open the local browser consent flow and save the grant under its account label."""
    CredentialStore._validate_account_key(account_key)
    _validate_desktop_client(client_secrets_path)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=SCOPES)
    if on_authorization_started is not None:
        on_authorization_started()
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        access_type="offline",
        prompt="consent" if account_key == OWNER_ACCOUNT_KEY else "select_account consent",
        timeout_seconds=OAUTH_AUTHORIZATION_TIMEOUT_SECONDS,
    )
    granted_scopes = getattr(credentials, "granted_scopes", None)
    if not granted_scopes:
        # Google omits a distinct granted_scopes list when consent matched the
        # requested set; in that case the successful consent response uses scopes.
        granted_scopes = getattr(credentials, "scopes", None)
    credential_store.save(account_key, credentials, granted_scopes=granted_scopes or ())
    return credentials


def refresh_credentials(
    account_key: str, credential_store: CredentialStore, credentials: Credentials
) -> Credentials:
    """Refresh an existing user grant; stop and erase it when Google revokes it."""
    if not credentials.refresh_token:
        credential_store.delete(account_key)
        raise AuthorizationRequiredError("A new Desktop OAuth consent is required")
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        if "invalid_grant" in str(exc).casefold():
            credential_store.delete(account_key)
            raise AuthorizationRevokedError(
                "Google authorization was revoked or expired; authorize the owner account again"
            ) from exc
        raise
    credential_store.save(account_key, credentials)
    return credentials


def execute_api_request(request: Any) -> Any:
    """Translate a revoked grant during discovery-client refresh into a safe auth error."""
    try:
        return request.execute()
    except RefreshError as exc:
        if "invalid_grant" in str(exc).casefold():
            raise AuthorizationRevokedError(
                "Google authorization was revoked or expired; authorize the owner account again"
            ) from exc
        raise


def _canonical_handle(value: str) -> str:
    value = value.strip()
    return (value if value.startswith("@") else f"@{value}").casefold()


def resolve_channel(requested: str, owned_channels: Sequence[ChannelRef]) -> ChannelRef:
    """Match only an exact channel ID, handle, or display name."""
    target = requested.strip()
    if not target:
        raise ChannelResolutionError("A channel ID, handle, or exact display name is required")
    matches: dict[str, ChannelRef] = {}
    for channel in owned_channels:
        if channel.channel_id == target:
            matches[channel.channel_id] = channel
        if channel.display_name.casefold() == target.casefold():
            matches[channel.channel_id] = channel
        if channel.handle and _canonical_handle(channel.handle) == _canonical_handle(target):
            matches[channel.channel_id] = channel
    if not matches:
        raise ChannelResolutionError(f"No owned YouTube channel matches exactly: {target}")
    if len(matches) != 1:
        raise ChannelResolutionError(f"Channel name or handle is ambiguous: {target}")
    return next(iter(matches.values()))


class YouTubeApi:
    """Small authenticated YouTube Data API wrapper used for owned-channel lookup."""

    def __init__(self, credentials: Credentials, client: Any | None = None) -> None:
        self.client = client or build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def list_owned_channels(self) -> list[ChannelRef]:
        channels: list[ChannelRef] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"part": "id,snippet", "mine": True, "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            response = execute_api_request(self.client.channels().list(**params))
            for item in response.get("items", []):
                snippet = item.get("snippet") or {}
                channel_id = item.get("id")
                display_name = snippet.get("title")
                if not isinstance(channel_id, str) or not isinstance(display_name, str):
                    continue
                custom_url = snippet.get("customUrl")
                handle = custom_url if isinstance(custom_url, str) and custom_url.startswith("@") else None
                channels.append(ChannelRef(channel_id, display_name, handle))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return channels
