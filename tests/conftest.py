import pytest

from katy404_youtube_agent.models import UploadProfile


NOW = "2026-09-26T00:00:00Z"


@pytest.fixture
def valid_profile(tmp_path):
    secrets_path = tmp_path / "client_secrets.json"
    secrets_path.write_text(
        '{"installed":{"project_id":"mfk110-test-upload"}}', encoding="utf-8"
    )
    return UploadProfile(
        channel_alias="Katy404",
        channel_id="UC123",
        client_secrets_path=secrets_path,
        privacy_status="private",
        api_audit_passed=False,
        category_id="20",
        description_template="{title}",
        tags=(),
        made_for_kids=False,
        contains_synthetic_media=False,
        is_official_artist_channel=False,
        shorts_title_suffix=" #Shorts",
        privacy_policy_url="https://privacy.example.test/katy404",
        policy_accepted_at=NOW,
        policy_version_accepted="2026-09-26",
        approved_pilot_video_id=None,
    )
