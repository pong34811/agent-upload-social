"""Top-level media discovery with exact thumbnail pairing and content hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import MediaCandidate, ScanIssue

_VIDEO_SUFFIXES = {".mov", ".mp4"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
_MAX_VIDEO_BYTES = 256 * 1024**3
_MAX_IMAGE_BYTES = 50 * 1024**2
_HASH_CHUNK_BYTES = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _issue(path: Path, code: str, message: str) -> ScanIssue:
    return ScanIssue(path=path, code=code, message=message)


def scan_folder(folder: Path) -> tuple[list[MediaCandidate], list[ScanIssue]]:
    """Scan only direct child files, pairing each video with one matching image."""
    folder = Path(folder)
    if not folder.is_dir():
        return [], [_issue(folder, "folder_unavailable", "Folder does not exist or is not a directory")]
    try:
        entries = sorted(folder.iterdir(), key=lambda item: (item.name.casefold(), item.name))
    except OSError as exc:
        return [], [_issue(folder, "folder_unreadable", str(exc))]

    videos = [
        entry for entry in entries
        if entry.suffix.casefold() in _VIDEO_SUFFIXES and entry.is_file()
    ]
    images_by_stem: dict[str, list[Path]] = {}
    for entry in entries:
        if entry.suffix.casefold() in _IMAGE_SUFFIXES and entry.is_file():
            images_by_stem.setdefault(entry.stem.casefold(), []).append(entry)

    candidates: list[MediaCandidate] = []
    issues: list[ScanIssue] = []
    for video in videos:
        if video.is_symlink():
            issues.append(_issue(video, "symlink_not_supported", "Symbolic links are not accepted"))
            continue
        matches = images_by_stem.get(video.stem.casefold(), [])
        if not matches:
            issues.append(_issue(video, "thumbnail_missing", "No JPG/JPEG/PNG with the same basename was found"))
            continue
        if len(matches) != 1:
            issues.append(_issue(video, "thumbnail_ambiguous", "More than one image matches this video basename"))
            continue

        thumbnail = matches[0]
        if thumbnail.is_symlink():
            issues.append(_issue(thumbnail, "symlink_not_supported", "Symbolic links are not accepted"))
            continue
        try:
            video_before = video.stat()
            thumbnail_before = thumbnail.stat()
            if video_before.st_size > _MAX_VIDEO_BYTES:
                issues.append(_issue(video, "video_too_large", "Video exceeds the 256 GB upload limit"))
                continue
            if thumbnail_before.st_size > _MAX_IMAGE_BYTES:
                issues.append(_issue(thumbnail, "thumbnail_too_large", "Thumbnail exceeds the 50 MB upload limit"))
                continue
            if thumbnail_before.st_size == 0:
                issues.append(_issue(thumbnail, "thumbnail_unreadable", "Thumbnail is empty"))
                continue
            # Opening and reading locally catches inaccessible or broken file handles without decoding or rewriting media.
            with thumbnail.open("rb") as stream:
                stream.read(1)
            video_hash = _sha256_file(video)
            thumbnail_hash = _sha256_file(thumbnail)
            video_after = video.stat()
            thumbnail_after = thumbnail.stat()
        except OSError as exc:
            issues.append(_issue(video, "file_unreadable", str(exc)))
            continue

        if (video_before.st_size, video_before.st_mtime_ns) != (video_after.st_size, video_after.st_mtime_ns):
            issues.append(_issue(video, "file_changed_during_scan", "Video changed while it was being scanned"))
            continue
        if (thumbnail_before.st_size, thumbnail_before.st_mtime_ns) != (thumbnail_after.st_size, thumbnail_after.st_mtime_ns):
            issues.append(_issue(thumbnail, "file_changed_during_scan", "Thumbnail changed while it was being scanned"))
            continue
        candidates.append(
            MediaCandidate(
                path=video,
                thumbnail_path=thumbnail,
                sha256=video_hash,
                thumbnail_sha256=thumbnail_hash,
                size_bytes=video_before.st_size,
                thumbnail_size_bytes=thumbnail_before.st_size,
                modified_ns=video_before.st_mtime_ns,
            )
        )

    candidates.sort(key=lambda item: (str(item.path).casefold(), str(item.path)))
    issues.sort(key=lambda item: (str(item.path).casefold(), item.code))
    return candidates, issues
