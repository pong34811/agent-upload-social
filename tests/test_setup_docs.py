from pathlib import Path


def test_readme_contains_katy404_paths_and_pilot_sequence():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert r"G:\My Drive\Projects\Katy404\2026-09\vdo" in readme
    assert "--limit 1 --force-private" in readme
    assert "profile approve-pilot" in readme


def test_setup_docs_describe_local_status_page_for_missing_token():
    readme = Path("README.md").read_text(encoding="utf-8")
    setup = Path("docs/setup.md").read_text(encoding="utf-8")
    section = setup.split("### หน้าเข้าสู่ระบบในเครื่อง", 1)[1].split("## ", 1)[0]

    assert "Credential Manager" in setup
    assert "Google OAuth" in setup
    assert "status page" in readme.casefold()
    assert "ไม่แสดง access/refresh token" in section
