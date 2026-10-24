"""OAuth credentials, consent flow, and owned-channel resolution."""

from .channels import ChannelRef, ChannelResolutionError, resolve_channel
from .credentials import (
    CREDENTIAL_SERVICE,
    OWNER_ACCOUNT_KEY,
    SCOPES,
    AuthorizationRequiredError,
    AuthorizationRevokedError,
    CredentialRevocationError,
    CredentialStore,
    CredentialStoreError,
    OAuthConfigurationError,
)
from .oauth import InstalledAppFlow, authorize_desktop, execute_api_request, refresh_credentials

__all__ = [
    "CREDENTIAL_SERVICE",
    "OWNER_ACCOUNT_KEY",
    "SCOPES",
    "AuthorizationRequiredError",
    "AuthorizationRevokedError",
    "ChannelRef",
    "ChannelResolutionError",
    "CredentialRevocationError",
    "CredentialStore",
    "CredentialStoreError",
    "InstalledAppFlow",
    "OAuthConfigurationError",
    "authorize_desktop",
    "execute_api_request",
    "refresh_credentials",
    "resolve_channel",
]
