import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from katy404_youtube_agent.auth import (
    AuthorizationRevokedError,
    CredentialStore,
    authorize_desktop,
    execute_api_request,
    refresh_credentials,
)


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def credential_json():
    return json.dumps({
        "token": "access-value",
        "refresh_token": "refresh-value",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    })


def fake_credentials():
    return Credentials.from_authorized_user_info(json.loads(credential_json()))


@pytest.fixture
def fake_keyring():
    return FakeKeyring()


@pytest.fixture
def expired_credentials():
    credentials = Mock()
    credentials.refresh_token = "refresh-value"
    credentials.to_json.return_value = credential_json()
    return credentials


def test_credential_store_round_trips_without_writing_token_file(fake_keyring, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = CredentialStore(fake_keyring)
    store.save("UC1", fake_credentials())

    assert store.load("UC1").refresh_token == "refresh-value"
    assert not Path("token.json").exists()


def test_invalid_grant_removes_token_and_raises_revoked_error(fake_keyring, expired_credentials):
    store = CredentialStore(fake_keyring)
    store.save("UC1", expired_credentials)
    expired_credentials.refresh.side_effect = RefreshError("invalid_grant")

    with pytest.raises(AuthorizationRevokedError):
        refresh_credentials("UC1", store, expired_credentials)

    assert store.load("UC1") is None


def test_authorize_uses_desktop_flow_and_saves_owner_credential(tmp_path, fake_keyring, monkeypatch):
    secrets_path = tmp_path / "client_secrets.json"
    secrets_path.write_text(
        '{"installed":{"project_id":"mfk110-upload","client_id":"client-id"}}',
        encoding="utf-8",
    )
    flow = Mock()
    flow.run_local_server.return_value = fake_credentials()
    monkeypatch.setattr(
        "katy404_youtube_agent.auth.InstalledAppFlow.from_client_secrets_file",
        lambda *args, **kwargs: flow,
    )
    store = CredentialStore(fake_keyring)

    credentials = authorize_desktop(secrets_path, store)

    assert credentials.refresh_token == "refresh-value"
    flow.run_local_server.assert_called_once_with(port=0, access_type="offline", prompt="consent")
    assert store.load("owner").refresh_token == "refresh-value"


def test_authorize_rejects_old_upload_project_before_browser_consent(tmp_path, fake_keyring, monkeypatch):
    secrets_path = tmp_path / "client_secrets.json"
    secrets_path.write_text('{"installed":{"project_id":"old-project"}}', encoding="utf-8")
    flow_factory = Mock()
    monkeypatch.setattr("katy404_youtube_agent.auth.InstalledAppFlow.from_client_secrets_file", flow_factory)

    with pytest.raises(ValueError, match="mfk110"):
        authorize_desktop(secrets_path, CredentialStore(fake_keyring))

    flow_factory.assert_not_called()


def test_revoke_sends_token_then_deletes_local_credential(fake_keyring, monkeypatch):
    import katy404_youtube_agent.auth as auth

    store = CredentialStore(fake_keyring)
    store.save("owner", fake_credentials())
    response = Mock()
    monkeypatch.setattr(auth.requests, "post", Mock(return_value=response))

    store.revoke("owner")

    auth.requests.post.assert_called_once_with(
        "https://oauth2.googleapis.com/revoke", data={"token": "refresh-value"}, timeout=10
    )
    response.raise_for_status.assert_called_once_with()
    assert store.load("owner") is None


def test_discovery_request_translates_invalid_grant_without_exposing_provider_message():
    request = Mock()
    request.execute.side_effect = RefreshError("invalid_grant: private provider details")

    with pytest.raises(AuthorizationRevokedError, match="revoked or expired") as error:
        execute_api_request(request)

    assert "private provider details" not in str(error.value)
