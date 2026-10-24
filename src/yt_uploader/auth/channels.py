"""Exact matching of a requested channel against the account's owned channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

class ChannelResolutionError(ValueError):
    """Raised when a requested channel is not an exact, unique owned channel."""


@dataclass(frozen=True, slots=True)
class ChannelRef:
    channel_id: str
    display_name: str
    handle: str | None = None


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
