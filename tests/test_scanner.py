from pathlib import Path

from katy404_youtube_agent.scanner import scan_folder


def test_scan_uses_top_level_files_and_exact_case_insensitive_thumbnail_stem(tmp_path):
    (tmp_path / "คลิป A_9x16.MOV").write_bytes(b"video")
    (tmp_path / "คลิป A_9x16.jpg").write_bytes(b"image")
    nested = tmp_path / "subfolder"
    nested.mkdir()
    (nested / "nested.mov").write_bytes(b"video")
    (nested / "nested.jpg").write_bytes(b"image")

    candidates, issues = scan_folder(tmp_path)

    assert [item.path.name for item in candidates] == ["คลิป A_9x16.MOV"]
    assert candidates[0].thumbnail_path.name == "คลิป A_9x16.jpg"
    assert len(candidates[0].sha256) == 64
    assert issues == []


def test_missing_or_ambiguous_thumbnail_is_reported_not_paired_arbitrarily(tmp_path):
    (tmp_path / "missing.mov").write_bytes(b"video")
    (tmp_path / "clip.mov").write_bytes(b"video")
    (tmp_path / "CLIP.jpg").write_bytes(b"one")
    (tmp_path / "clip.jpeg").write_bytes(b"two")

    candidates, issues = scan_folder(tmp_path)

    assert candidates == []
    assert {issue.code for issue in issues} == {"thumbnail_missing", "thumbnail_ambiguous"}


def test_scan_sorts_candidates_by_casefolded_path(tmp_path):
    for name in ("z.mov", "a.MOV"):
        (tmp_path / name).write_bytes(b"video")
        (tmp_path / f"{Path(name).stem}.jpg").write_bytes(b"image")

    candidates, issues = scan_folder(tmp_path)

    assert [item.path.name for item in candidates] == ["a.MOV", "z.mov"]
    assert issues == []
