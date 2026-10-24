"""Desktop OAuth consent, token refresh, and revoked-grant translation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .credentials import (
    OAUTH_AUTHORIZATION_TIMEOUT_SECONDS,
    OWNER_ACCOUNT_KEY,
    SCOPES,
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    CredentialStore,
    OAuthConfigurationError,
)

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
