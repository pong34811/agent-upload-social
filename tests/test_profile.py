import dataclasses
import json
from pathlib import Path

import pytest

from katy404_youtube_agent.profile import (
    POLICY_VERSION,
    ProfileError,
    ProfileStore,
    load_profile,
    save_profile,
    validate_upload_profile,
)


def test_load_profile_requires_channel_alias_oauth_policy_and_declarations(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ProfileError, match="channel_alias"):
        load_profile(profile_path)


@pytest.mark.parametrize("requested_privacy", ["unlisted", "public"])
def test_nonprivate_upload_requires_recorded_youtube_api_audit(
    valid_profile, requested_privacy
):
    profile = dataclasses.replace(valid_profile, api_audit_passed=False)

    with pytest.raises(ProfileError, match="API compliance audit"):
        validate_upload_profile(profile, requested_privacy=requested_privacy)


def test_profile_rejects_oauth_client_from_non_upload_project(tmp_path, valid_profile):
    secrets_path = tmp_path / "client_secrets.json"
    secrets_path.write_text(
        json.dumps({"installed": {"project_id": "legacy-project"}}), encoding="utf-8"
    )
    profile = dataclasses.replace(valid_profile, client_secrets_path=secrets_path)

    with pytest.raises(ProfileError, match="mfk110"):
        validate_upload_profile(profile, requested_privacy="private")


def test_unaccepted_or_stale_policy_blocks_api_operations(valid_profile):
    profile = dataclasses.replace(valid_profile, policy_version_accepted="old-version")

    with pytest.raises(ProfileError, match="privacy policy"):
        validate_upload_profile(profile, requested_privacy="private")


def test_unknown_privacy_is_rejected(valid_profile):
    with pytest.raises(ProfileError, match="privacy_status"):
        validate_upload_profile(valid_profile, requested_privacy="friends")


def test_profile_store_round_trips_path_fields(tmp_path, valid_profile):
    path = tmp_path / "profile.json"

    save_profile(path, valid_profile)
    loaded = load_profile(path)

    assert loaded == valid_profile
    assert isinstance(loaded.client_secrets_path, Path)
    assert ProfileStore(path).load() == valid_profile


def test_oauth_files_are_ignored_by_gitignore():
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    assert "client_secrets.json" in ignore_text
    assert "token.json" in ignore_text
    assert "*.sqlite3" in ignore_text
