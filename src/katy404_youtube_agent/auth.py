"""Desktop OAuth, Windows credential storage, and owned-channel selection."""

from __future__ import annotations

import json
import os
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
)
OAUTH_AUTHORIZATION_TIMEOUT_SECONDS = 600


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
    """Store OAuth credential JSON in Windows Credential Manager via keyring."""

    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            if os.name != "nt":
                raise CredentialStoreError("YouTube OAuth credentials require Windows Credential Manager")
            selected_backend = keyring.get_keyring()
            if (
                type(selected_backend).__module__ != "keyring.backends.Windows"
                or type(selected_backend).__name__ != "WinVaultKeyring"
            ):
                raise CredentialStoreError(
                    "Windows Credential Manager is unavailable; refusing an unprotected token backend"
                )
            self._backend = keyring
        else:
            self._backend = backend

    def load(self, account_key: str) -> Credentials | None:
        try:
            serialized = self._backend.get_password(CREDENTIAL_SERVICE, account_key)
        except Exception as exc:
            raise CredentialStoreError("Could not read credentials from Windows Credential Manager") from exc
        if serialized is None:
            return None
        try:
            data = json.loads(serialized)
            return Credentials.from_authorized_user_info(data, scopes=SCOPES)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("Stored OAuth credential data is invalid") from exc

    def save(self, account_key: str, credentials: Credentials) -> None:
        try:
            serialized = credentials.to_json()
            if not isinstance(serialized, str) or not serialized:
                raise ValueError("empty credential serialization")
            json.loads(serialized)
            self._backend.set_password(CREDENTIAL_SERVICE, account_key, serialized)
        except Exception as exc:
            raise CredentialStoreError("Could not store credentials in Windows Credential Manager") from exc

    def delete(self, account_key: str) -> None:
        try:
            self._backend.delete_password(CREDENTIAL_SERVICE, account_key)
        except Exception as exc:
            # A missing entry is already the desired local state.
            if "not found" not in str(exc).casefold() and "no password" not in str(exc).casefold():
                raise CredentialStoreError("Could not delete local OAuth credentials") from exc

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
    project_id = installed.get("project_id")
    if not isinstance(project_id, str) or not project_id.startswith("mfk110"):
        raise OAuthConfigurationError("Desktop OAuth project_id must start with mfk110")


def authorize_desktop(
    client_secrets_path: Path,
    credential_store: CredentialStore,
    *,
    on_authorization_started: Callable[[], None] | None = None,
) -> Credentials:
    """Open the one-time local browser consent flow and save the grant securely."""
    _validate_desktop_client(client_secrets_path)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=SCOPES)
    if on_authorization_started is not None:
        on_authorization_started()
    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        timeout_seconds=OAUTH_AUTHORIZATION_TIMEOUT_SECONDS,
    )
    credential_store.save(OWNER_ACCOUNT_KEY, credentials)
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
