from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from conftest import NOW
from katy404_youtube_agent.auth import (
    AuthorizationRevokedError,
    ChannelRef,
    ChannelResolutionError,
)
from katy404_youtube_agent.cli import CliApp, OAuthService
from katy404_youtube_agent.local_oauth_status import LocalOAuthStatusPage
from katy404_youtube_agent.models import ApiVideoSnapshot, BatchReport
from katy404_youtube_agent.profile import POLICY_VERSION


class RecordingOAuthStatusPage:
    def __init__(self):
        self.steps = []

    def start(self):
        self.steps.append("start")

    def set_state(self, state):
        self.steps.append(state)

    def finish(self):
        self.steps.append("finish")


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


def test_missing_credential_authorizes_before_api_creation_and_upload(cli):
    events = []
    credential = SimpleNamespace(valid=True)
    cli.credentials.load.side_effect = lambda _key: None
    cli.oauth.authorize.side_effect = lambda *_args: (events.append("authorize"), credential)[1]
    cli.oauth.build_api.side_effect = lambda *_args: (events.append("build_api"), cli.api)[1]
    cli.runner.upload.side_effect = lambda *_args, **_kwargs: (
        events.append("upload"), BatchReport([], 0, 0, 0, 0)
    )[1]

    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    assert events == ["authorize", "build_api", "upload"]
    cli.credentials.load.assert_called_once_with("owner")


def test_existing_credential_skips_oauth(cli):
    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 0
    cli.oauth.authorize.assert_not_called()
    cli.oauth.build_api.assert_called_once()
    cli.runner.upload.assert_called_once()


def test_oauth_service_reports_success_in_page_states(monkeypatch):
    page = RecordingOAuthStatusPage()
    credential = object()

    def authorize(_path, _store, *, on_authorization_started):
        on_authorization_started()
        return credential

    monkeypatch.setattr("katy404_youtube_agent.auth.authorize_desktop", authorize)
    service = OAuthService(status_page_factory=lambda: page)

    result = service.authorize(Path("client.json"), object())

    assert result is credential
    assert page.steps == ["start", "waiting", "connected", "finish"]


def test_oauth_service_marks_stopped_and_finishes_after_authorization_error(monkeypatch):
    page = RecordingOAuthStatusPage()

    def authorize(_path, _store, *, on_authorization_started):
        on_authorization_started()
        raise RuntimeError("private OAuth response body")

    monkeypatch.setattr("katy404_youtube_agent.auth.authorize_desktop", authorize)
    service = OAuthService(status_page_factory=lambda: page)

    with pytest.raises(RuntimeError, match="private OAuth response body"):
        service.authorize(Path("client.json"), object())

    assert page.steps == ["start", "waiting", "stopped", "finish"]


@pytest.mark.parametrize("browser_result", [False, "raise"])
def test_oauth_page_open_failure_stops_before_google_api_or_upload(cli, monkeypatch, capsys, browser_result):
    import katy404_youtube_agent.auth as auth

    cli.credentials.load.side_effect = lambda _key: None
    flow = Mock()
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", lambda *_args, **_kwargs: flow)
    pages = []

    def browser_open(_url):
        if browser_result == "raise":
            raise RuntimeError("private browser details")
        return browser_result

    def page_factory():
        page = LocalOAuthStatusPage(browser_open=browser_open)
        pages.append(page)
        return page

    service = OAuthService(status_page_factory=page_factory)
    service.build_api = Mock()
    cli.app.oauth = service

    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 1
    flow.run_local_server.assert_not_called()
    service.build_api.assert_not_called()
    cli.runner.upload.assert_not_called()
    assert pages
    assert "private browser details" not in capsys.readouterr().err


@pytest.mark.parametrize("failure_stage", ["google_consent", "credential_store"])
def test_oauth_failure_stops_before_upload_and_hides_exception_body(cli, monkeypatch, capsys, failure_stage):
    import katy404_youtube_agent.auth as auth

    cli.credentials.load.side_effect = lambda _key: None
    page = RecordingOAuthStatusPage()
    service = OAuthService(status_page_factory=lambda: page)
    service.build_api = Mock()
    cli.app.oauth = service
    flow = Mock()
    secret_body = f"private {failure_stage} payload"
    if failure_stage == "google_consent":
        flow.run_local_server.side_effect = RuntimeError(secret_body)
    else:
        flow.run_local_server.return_value = SimpleNamespace(
            to_json=Mock(return_value='{"token":"secret"}')
        )
        cli.credentials.save.side_effect = RuntimeError(secret_body)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", lambda *_args, **_kwargs: flow)

    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 1
    assert page.steps == ["start", "waiting", "stopped", "finish"]
    service.build_api.assert_not_called()
    cli.runner.upload.assert_not_called()
    output = capsys.readouterr()
    assert secret_body not in output.out
    assert secret_body not in output.err


def test_channel_mismatch_after_authorization_keeps_stored_credential(cli):
    stored = {"owner": None}
    credential = SimpleNamespace(valid=True)
    cli.credentials.load.side_effect = lambda key: stored[key]

    def authorize(_path, _store):
        stored["owner"] = credential
        return credential

    cli.oauth.authorize.side_effect = authorize
    cli.runner.upload.side_effect = ChannelResolutionError("No owned channel matches the request")

    result = cli.app.run(["upload", "--folder", "media", "--channel", "@not-my-channel"])

    assert result == 2
    assert cli.credentials.load("owner") is credential


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


def test_revoke_authorization_rejects_channel_mismatch_before_revoking(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)

    result = cli.app.run(["profile", "revoke-authorization", "--channel-id", "UC999"])

    assert result == 2
    cli.credentials.revoke.assert_not_called()
    assert cli.store.list_jobs("UC123")
    assert cli.profile.channel_id == "UC123"
    assert cli.profile.approved_pilot_video_id == "approved-private-video"


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


def test_retry_failed_command_requeues_one_explicit_path_without_oauth(cli, candidate, capsys):
    expected = SimpleNamespace(path=candidate.path)
    cli.runner.requeue_failed = Mock(return_value=expected)

    result = cli.app.run(["profile", "retry-failed", "--path", str(candidate.path)])

    assert result == 0
    cli.runner.requeue_failed.assert_called_once_with(candidate.path, "UC123")
    assert "พร้อมลองใหม่" in capsys.readouterr().out
    cli.credentials.load.assert_not_called()


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
    now = datetime.now(timezone.utc)
    job = cli.store.get_or_create_job(candidate, "UC123", metadata)
    due_at = now - timedelta(days=29, seconds=1)
    cli.store.mark_video_uploaded(job.id, "video-123", due_at)
    cli.store.mark_thumbnail_result(job.id, success=True)
    cli.store.refresh_api_record(job.id, due_at, {"privacy_status": "private"})
    expired_candidate = replace(
        candidate,
        path=candidate.path.with_name("expired.mov"),
        thumbnail_path=candidate.thumbnail_path.with_name("expired.jpg"),
        sha256="d" * 64,
    )
    expired = cli.store.get_or_create_job(expired_candidate, "UC123", metadata)
    expired_at = now - timedelta(days=31)
    cli.store.mark_video_uploaded(expired.id, "video-expired", expired_at)
    cli.store.mark_thumbnail_result(expired.id, success=True)
    cli.store.refresh_api_record(expired.id, expired_at, {"privacy_status": "private"})
    cli.api.refresh_videos.return_value = [
        ApiVideoSnapshot("video-123", "Title", None, "private", None, None)
    ]

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 0
    cli.api.refresh_videos.assert_called_once_with(["video-123"])
    assert cli.store.get_job(job.id).api_fields["privacy_status"] == "private"
    assert cli.store.get_job(job.id).api_fields["title"] == "Title"
    assert cli.store.get_job(expired.id).video_id is None
    assert cli.store.get_job(expired.id).api_fields == {}


def test_maintenance_clears_old_resumable_session_urls(cli, candidate, metadata):
    job = cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.store.mark_validated(job.id)
    cli.store.set_upload_session(job.id, "https://upload.example.test/expired-session", 4096)
    with cli.store._connect() as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            ((NOW - timedelta(days=31)).isoformat(), job.id),
        )

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 0
    refreshed = cli.store.get_job(job.id)
    assert refreshed.state == "validated"
    assert refreshed.session_uri is None
    assert refreshed.offset == 0


def test_maintenance_purges_expired_api_data_even_without_oauth_token(cli, candidate, metadata):
    job = cli.store.get_or_create_job(candidate, "UC123", metadata)
    old = NOW - timedelta(days=31)
    cli.store.mark_video_uploaded(job.id, "video-123", old)
    cli.store.mark_thumbnail_result(job.id, success=True)
    cli.store.refresh_api_record(job.id, old, {"privacy_status": "private"})
    cli.credentials.load.side_effect = lambda _key: None

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 1
    assert cli.store.get_job(job.id).video_id is None
    assert cli.store.get_job(job.id).api_fields == {}


def test_maintenance_lost_channel_access_deletes_local_channel_records(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.api.list_owned_channels.return_value = [ChannelRef("UC999", "Other", "@Other")]

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 1
    assert cli.store.list_jobs("UC123") == []


def test_maintenance_revoked_oauth_clears_channel_data_and_profile(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.oauth.refresh.side_effect = AuthorizationRevokedError("revoked")
    cli.credentials.load.side_effect = lambda _key: SimpleNamespace(valid=False)

    result = cli.app.run(["maintenance", "refresh"])

    assert result == 1
    assert cli.store.list_jobs("UC123") == []
    assert cli.profile.channel_id is None
    assert cli.profile.approved_pilot_video_id is None


def test_upload_revoked_oauth_clears_channel_data_and_profile(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.credentials.load.side_effect = lambda _key: SimpleNamespace(valid=False)
    cli.oauth.refresh.side_effect = AuthorizationRevokedError("revoked")

    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 1
    assert cli.store.list_jobs("UC123") == []
    assert cli.profile.channel_id is None
    assert cli.profile.approved_pilot_video_id is None


def test_upload_api_refresh_revocation_clears_channel_data_and_profile(cli, candidate, metadata):
    cli.store.get_or_create_job(candidate, "UC123", metadata)
    cli.runner.upload.side_effect = AuthorizationRevokedError("revoked")

    result = cli.app.run(["upload", "--folder", "media", "--channel", "Katy404"])

    assert result == 1
    assert cli.store.list_jobs("UC123") == []
    assert cli.profile.channel_id is None
    cli.credentials.delete.assert_called_once_with("owner")
