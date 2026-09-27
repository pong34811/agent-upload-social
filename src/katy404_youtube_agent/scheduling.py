"""Validation and deterministic planning for YouTube scheduled publishing."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from .models import MediaCandidate, MediaFacts

_RFC3339 = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)


def parse_publish_at(value: str) -> datetime:
    """Parse an RFC 3339 timestamp with an explicit offset, and reject past times."""
    if not isinstance(value, str) or not _RFC3339.fullmatch(value.strip()):
        raise ValueError("publish time must be RFC 3339 with an explicit UTC offset")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        publish_at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("publish time is not a valid RFC 3339 timestamp") from exc
    if publish_at.tzinfo is None or publish_at.utcoffset() is None:
        raise ValueError("publish time must include a UTC offset")
    publish_at = publish_at.replace(microsecond=0)
    if publish_at <= datetime.now(publish_at.tzinfo):
        raise ValueError("publish time must be in the future")
    return publish_at


def format_publish_at(value: datetime) -> str:
    """Return a stable RFC 3339 timestamp while preserving its explicit offset."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("publish time must include a UTC offset")
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def plan_daily_pairs(
    items: Sequence[tuple[MediaCandidate, MediaFacts]], start: datetime
) -> dict[Path, datetime]:
    """Pair same-rank landscape and portrait files on consecutive days."""
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("schedule start must include a UTC offset")
    if start <= datetime.now(start.tzinfo):
        raise ValueError("schedule start must be in the future")
    groups: dict[str, list[MediaCandidate]] = {"landscape": [], "portrait": []}
    for candidate, facts in items:
        if facts.width == facts.height:
            raise ValueError(f"Square video cannot be assigned to a landscape/portrait schedule: {candidate.path.name}")
        orientation = "landscape" if facts.width > facts.height else "portrait"
        groups[orientation].append(candidate)

    for candidates in groups.values():
        candidates.sort(key=lambda candidate: (candidate.path.name.casefold(), str(candidate.path).casefold()))
    if not groups["landscape"] or len(groups["landscape"]) != len(groups["portrait"]):
        raise ValueError("scheduled daily pairs require equal non-zero landscape and portrait counts")

    slots: dict[Path, datetime] = {}
    for day_index, (landscape, portrait) in enumerate(zip(groups["landscape"], groups["portrait"], strict=True)):
        publish_at = start + timedelta(days=day_index)
        slots[landscape.path] = publish_at
        slots[portrait.path] = publish_at
    return slots
