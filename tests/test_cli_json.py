import json
from pathlib import Path
from unittest.mock import Mock

from test_cli import CliHarness
from yt_uploader.auth import ChannelResolutionError
from yt_uploader.config.profile import save_profile
from yt_uploader.models import BatchReport, UploadItemResult


def _json(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


def test_profile_list_json_names_profiles_without_client_file_contents(valid_profile, store, capsys):
    cli = CliHarness(valid_profile, store)
    save_profile(store.db_path.parent / "profiles" / "katy404.json", valid_profile)

    assert cli.app.run(["profile", "list", "--json"]) == 0

    payload, err = _json(capsys)
    assert payload["ok"] is True
    assert payload["command"] == "profile list"
    assert payload["profiles"] == [{
        "name": "katy404",
        "readable": True,
        "channel_alias": "Katy404",
        "channel_id": "UC123",
        "oauth_account": "owner",
        "privacy_status": "private",
        "category_id": "20",
        "made_for_kids": False,
        "contains_synthetic_media": False,
        "client_secrets_configured": True,
    }]
    assert "client-secret" not in json.dumps(payload)
    assert "โปรไฟล์ที่บันทึกไว้" in err


def test_upload_json_reports_channel_items_and_keeps_text_off_stdout(valid_profile, store, capsys):
    cli = CliHarness(valid_profile, store)
    report = BatchReport(
        items=[
            UploadItemResult(
                "uploaded", Path("media/clip.mov"), video_id="vid1",
                video_url="https://www.youtube.com/watch?v=vid1", actual_visibility="private",
                thumbnail_status="success",
            ),
            UploadItemResult("pending_quota", Path("media/next.mov"), error_code="uploadLimitExceeded"),
        ],
        uploaded_count=1, skipped_count=0, failed_count=0, pending_count=1, stopped_reason="quota",
    )

    def upload(*_args, **kwargs):
        kwargs["on_preflight"](cli.api.list_owned_channels()[0], 2, 0, "private", valid_profile)
        return report

    cli.runner.upload = Mock(side_effect=upload)

    assert cli.app.run(["upload", "--folder", "media", "--channel", "Katy404", "--json"]) == 1

    payload, err = _json(capsys)
    assert payload["ok"] is False
    assert payload["channel"] == {"id": "UC123", "name": "Katy404"}
    assert payload["summary"]["uploaded"] == 1
    assert payload["summary"]["pending"] == 1
    assert payload["stopped_reason"] == "quota"
    assert payload["items"][0]["video_url"] == "https://www.youtube.com/watch?v=vid1"
    assert payload["items"][1] == {
        "file": "next.mov", "path": str(Path("media/next.mov")), "status": "pending_quota", "title": None,
        "video_id": None, "video_url": None, "visibility": None, "thumbnail": None, "publish_at": None,
        "error_code": "uploadLimitExceeded",
    }
    assert "ผลรอบนี้" in err


def test_dry_run_json_includes_titles_for_ready_files(valid_profile, store, capsys):
    cli = CliHarness(valid_profile, store)
    cli.runner.dry_run = Mock(return_value=BatchReport(
        [UploadItemResult("ready", Path("media/clip.mov"), title="clip #Shorts")], 0, 0, 0, 0,
    ))

    assert cli.app.run(["dry-run", "--folder", "media", "--channel", "Katy404", "--json"]) == 0

    payload, _ = _json(capsys)
    assert payload["summary"]["ready"] == 1
    assert payload["items"][0]["title"] == "clip #Shorts"


def test_ambiguous_channel_in_json_mode_stops_without_prompting(valid_profile, store, capsys, monkeypatch):
    cli = CliHarness(valid_profile, store)
    cli.runner.upload = Mock(side_effect=ChannelResolutionError("Channel name or handle is ambiguous: Katy"))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("must not prompt")))

    assert cli.app.run(["upload", "--folder", "media", "--channel", "Katy", "--json"]) == 2

    payload, _ = _json(capsys)
    assert payload["ok"] is False
    assert "ambiguous" in payload["error"]
    assert cli.runner.upload.call_count == 1


def test_json_error_never_contains_exception_bodies(valid_profile, store, capsys):
    cli = CliHarness(valid_profile, store)
    cli.runner.upload = Mock(side_effect=RuntimeError("https://upload.example.test/session-secret body"))

    assert cli.app.run(["upload", "--folder", "media", "--channel", "Katy404", "--json"]) == 1

    payload, err = _json(capsys)
    assert payload["error"] == "อัปโหลดไม่สำเร็จ (RuntimeError)"
    assert "session-secret" not in json.dumps(payload) + err
