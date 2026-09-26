import pytest

from katy404_youtube_agent.auth import (
    ChannelRef,
    ChannelResolutionError,
    YouTubeApi,
    resolve_channel,
)


def test_channel_resolution_stops_on_duplicate_display_names():
    channels = [
        ChannelRef("UC1", "Katy404", "@Katy404"),
        ChannelRef("UC2", "Katy404", "@Katy404Live"),
    ]

    with pytest.raises(ChannelResolutionError, match="ambiguous"):
        resolve_channel("Katy404", channels)


def test_channel_resolution_matches_exact_handle():
    result = resolve_channel("@Katy404", [ChannelRef("UC1", "Katy 404", "@Katy404")])

    assert result.channel_id == "UC1"


def test_channel_resolution_matches_exact_channel_id_or_handle_without_at():
    channels = [ChannelRef("UC123", "Katy404 Gaming", "@Katy404")]

    assert resolve_channel("UC123", channels).display_name == "Katy404 Gaming"
    assert resolve_channel("Katy404", channels).channel_id == "UC123"
    with pytest.raises(ChannelResolutionError, match="No owned"):
        resolve_channel("Katy", channels)


def test_youtube_api_lists_all_owned_channels_with_mine_filter():
    class Request:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class Channels:
        def __init__(self):
            self.calls = []

        def list(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return Request({
                    "items": [{"id": "UC1", "snippet": {"title": "Katy404", "customUrl": "@Katy404"}}],
                    "nextPageToken": "next",
                })
            return Request({"items": [{"id": "UC2", "snippet": {"title": "Other", "customUrl": "other"}}]})

    class Client:
        def __init__(self):
            self.resource = Channels()

        def channels(self):
            return self.resource

    client = Client()
    api = YouTubeApi(credentials=object(), client=client)

    channels = api.list_owned_channels()

    assert channels == [ChannelRef("UC1", "Katy404", "@Katy404"), ChannelRef("UC2", "Other", None)]
    assert client.resource.calls[0]["mine"] is True
    assert client.resource.calls[0]["part"] == "id,snippet"
    assert client.resource.calls[1]["pageToken"] == "next"
