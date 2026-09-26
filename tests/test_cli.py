from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from conftest import NOW
from katy404_youtube_agent.auth import ChannelRef
from katy404_youtube_agent.cli import CliApp
from katy404_youtube_agent.models import ApiVideoSnapshot, BatchReport
from katy404_youtube_agent.profile import POLICY_VERSION


class CliHarness:
    def __init__(self, profile, store):
        self.profile = profile
        self.store = store
        self.profile_store = Mock()
        self.profile_store.path = store.db_path.parent / "profile.json"
        self.profile_store.load.return_value = profile
        self.profile_store.save = Mock(side_effect=self._save)
        self.credentials = Mock()
        tokens = {"owner": SimpleNamespace(valid=True, refresh_token="test")}
        self.credentials.load.side_effect = lambda key: tokens.get(key)
        self.credentials.revoke = Mock()
        self.credentials.delete = Mock(side_effect=lambda key: tokens.pop(key, None))
        self.credentials.revoke.side_effect = lambda key: self.credentials.delete(key)
        self.api = SimpleNamespace(
            list_owned_channels=Mock(return_value=[ChannelRef("UC123", "Katy404", "@Katy404")]),
            refresh_videos=Mock(return_value=[]),
        )
        self.oauth = SimpleNamespace(
            authorize=Mock(return_value=SimpleNamespace(valid=True)),
            refresh=Mock(return_value=SimpleNamespace(valid=True)),
            build_api=Mock(return_value=self.api),
        )
        self.runner = SimpleNamespace(profile=profile, store=store, api=None)
        self.runner.dry_run = Mock(return_value=BatchReport([], 0, 0, 0, 0))

        def upload(*args, **kwargs):
            callback = kwargs.get("on_preflight")
            if callback:
                callback(ChannelRef("UC123", "Katy404", "@Katy404"), 2, 1, "private", profile)
            return BatchReport([], 0, 0, 0, 0)

        self.runner.upload = Mock(side_effect=upload)
        self.app = CliApp(
            runner=self.runner,
            profile_store=self.profile_store,
            credential_store=self.credentials,
            oauth_service=self.oauth,
            store=store,
        )

    def _save(self, profile):
        self.profile = profile
        self.runner.profile = profile
        self.profile_store.load.return_value = profile


@pytest.fixture
def cli(valid_profile, store):
    profile = replace(valid_profile, approved_pilot_video_id="approved-private-video")
    return CliHarness(profile, store)


@pytest.fixture
def cli_unaccepted_policy(valid_profile, store):
    profile = replace(valid_profile, policy_version_accepted="old-version")
    return CliHarness(profile, store)


@pytest.fixture
def cli_unapproved_pilot(valid_profile, store):
    return CliHarness(replace(valid_profile, approved_pilot_video_id=None), store)


@pytest.fixture
def cli_approved_pilot(cli):
    return cli


@pytest.fixture
def cli_with_completed_private_pilot(valid_profile, store, candidate, metadata):
    profile = replace(valid_profile, approved_pilot_video_id=None)
    job = store.get_or_create_job(candidate, "UC123", metadata)
    store.mark_video_uploaded(job.id, "video-123", NOW)
    store.mark_thumbnail_result(job.id, success=True)
    store.refresh_api_record(job.id, NOW, {"privacy_status": "private"})
    return CliHarness(profile, store)


def test_upload_command_prints_channel_count_and_visibility_before_upload(cli, capsys):
    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    output = capsys.readouterr().out
    assert "ช่อง: Katy404" in output
    assert "วิดีโอ: 2" in output
    assert "ข้าม: 1" in output
    assert "ความเป็นส่วนตัว: private" in output
    assert "สิทธิ์ assets: ยืนยัน" in output
    assert cli.runner.upload.call_count == 1


def test_upload_refuses_unaccepted_privacy_policy_before_oauth(cli_unaccepted_policy):
    cli = cli_unaccepted_policy
    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 2
    assert cli.oauth.authorize.call_count == 0
    assert cli.credentials.load.call_count == 0
    assert cli.runner.upload.call_count == 0


def test_first_upload_runs_private_pilot_until_user_review(cli_unapproved_pilot):
    cli = cli_unapproved_pilot
    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    assert cli.runner.upload.call_args.kwargs["limit"] == 1
    assert cli.runner.upload.call_args.kwargs["force_private"] is True


def test_approved_pilot_allows_the_requested_full_batch(cli_approved_pilot):
    cli = cli_approved_pilot
    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    assert cli.runner.upload.call_args.kwargs["limit"] is None
    assert cli.runner.upload.call_args.kwargs["force_private"] is False


def test_revoke_authorization_revokes_token_and_removes_local_api_data(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)

    result = cli.app.run(["profile", "revoke-authorization", "--channel-id", "UC123"])

    assert result == 0
    assert cli.store.list_jobs("UC123") == []
    cli.credentials.revoke.assert_called_once_with("owner")
    assert cli.credentials.load("UC123") is None
    assert cli.profile.channel_id is None
    assert cli.profile.approved_pilot_video_id is None


def test_accept_policy_requires_explicit_phrase_before_recording(cli, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "ยอมรับ")

    result = cli.app.run(["profile", "accept-policy"])

    assert result == 0
    assert cli.profile_store.save.call_count == 1
    assert cli.profile.policy_version_accepted == POLICY_VERSION
    assert cli.profile.policy_accepted_at is not None


def test_accept_policy_requires_an_https_privacy_policy_url(cli, monkeypatch):
    cli.profile = replace(cli.profile, privacy_policy_url="")
    cli.profile_store.load.return_value = cli.profile
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must reject before asking for consent"))

    assert cli.app.run(["profile", "accept-policy"]) == 2
    assert cli.profile_store.save.call_count == 0


def test_accept_policy_decline_does_not_change_profile(cli, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "ไม่ยอมรับ")

    result = cli.app.run(["profile", "accept-policy"])

    assert result == 2
    assert cli.profile_store.save.call_count == 0


def test_profile_setup_collects_owner_declarations_and_does_not_accept_policy(cli, monkeypatch):
    answers = iter([
        "Katy404", "", "", "20", "private", "gaming, thailand", "no", "no", "no", "yes",
        str(cli.profile.client_secrets_path), cli.profile.privacy_policy_url,
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = cli.app.run(["profile", "setup"])

    assert result == 0
    created = cli.profile_store.save.call_args.args[0]
    assert created.asset_rights_confirmed is True
    assert created.tags == ("gaming", "thailand")
    assert created.policy_version_accepted is None


def test_dry_run_uses_no_oauth(cli):
    result = cli.app.run(["dry-run", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    cli.runner.dry_run.assert_called_once()
    assert cli.credentials.load.call_count == 0
    assert cli.oauth.authorize.call_count == 0


def test_profile_show_never_displays_client_json_contents(cli, capsys):
    assert cli.app.run(["profile", "show"]) == 0
    output = capsys.readouterr().out
    assert "mfk110-test-upload" not in output
    assert "token" in output.casefold()


def test_approve_pilot_accepts_only_a_completed_private_video(cli_with_completed_private_pilot):
    cli = cli_with_completed_private_pilot

    result = cli.app.run(["profile", "approve-pilot", "--video-id", "video-123"])

    assert result == 0
    assert cli.profile.approved_pilot_video_id == "video-123"


def test_approve_pilot_rejects_video_without_confirmed_private_status(cli_with_completed_private_pilot):
    cli = cli_with_completed_private_pilot
    cli.store.delete_account_data("UC123")

    result = cli.app.run(["profile", "approve-pilot", "--video-id", "video-123"])

    assert result == 2
    assert cli.profile.approved_pilot_video_id is None


def test_profile_privacy_and_audit_commands_update_only_declared_values(cli):
    assert cli.app.run(["profile", "set-privacy", "public"]) == 0
    assert cli.profile.privacy_status == "public"
    assert cli.app.run(["profile", "set-api-audit-status", "passed"]) == 0
    assert cli.profile.api_audit_passed is True
    assert cli.app.run(["profile", "set-asset-rights-status", "not-confirmed"]) == 0
    assert cli.profile.asset_rights_confirmed is False


def test_profile_delete_account_data_explains_remote_videos_remain(cli, candidate, metadata, capsys):
    cli.store.get_or_create_job(candidate, "UC123", metadata)

    result = cli.app.run(["profile", "delete-account-data", "--channel-id", "UC123"])

    assert result == 0
    assert cli.store.list_jobs("UC123") == []
    assert cli.profile.channel_id is None
    assert cli.profile.approved_pilot_video_id is None
    assert "ไม่ได้ลบวิดีโอ" in capsys.readouterr().out


def test_batch_errors_return_one(cli):
    cli.runner.upload.side_effect = lambda *args, **kwargs: BatchReport([], 0, 0, 1, 0)

    assert cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"]) == 1


def test_thumbnail_failure_is_reported_as_batch_error(cli):
    from katy404_youtube_agent.models import UploadItemResult

    cli.runner.upload.side_effect = lambda *args, **kwargs: BatchReport(
        [UploadItemResult("uploaded_thumbnail_failed", Path("clip.mov"), video_id="video-1", error_code="quota")],
        1,
        0,
        0,
        0,
    )

    assert cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"]) == 1


def test_maintenance_refreshes_due_api_data_and_purges_expired_records(
    cli, candidate, metadata, monkeypatch
):
    job = cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.store.mark_video_uploaded(job.id, "video-123", datetime(2026, 8, 1, tzinfo=timezone.utc))
    cli.store.mark_thumbnail_result(job.id, success=True)
    cli.store.refresh_api_record(job.id, datetime(2026, 8, 1, tzinfo=timezone.utc), {"privacy_status": "private"})
    cli.api.refresh_videos.return_value = [
        ApiVideoSnapshot("video-123", "Title", None, "private", None, None)
    ]

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 0
    cli.api.refresh_videos.assert_called_once_with(["video-123"])
    assert cli.store.get_job(job.id).api_fields["privacy_status"] == "private"
    assert cli.store.get_job(job.id).api_fields["title"] == "Title"


def test_maintenance_lost_channel_access_deletes_local_channel_records(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.api.list_owned_channels.return_value = [ChannelRef("UC999", "Other", "@Other")]

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 1
    assert cli.store.list_jobs("UC123") == []
