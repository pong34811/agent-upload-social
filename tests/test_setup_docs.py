from pathlib import Path


def test_readme_documents_agent_skill_and_direct_upload_command():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert ".agents/skills/kt404-youtube-upload/SKILL.md" in readme
    assert 'upload --folder "<โฟลเดอร์คลิป>" --channel "waritnan34811"' in readme


def test_setup_docs_describe_automatic_oauth_and_account_token_storage():
    readme = Path("README.md").read_text(encoding="utf-8")
    setup = Path("docs/setup.md").read_text(encoding="utf-8")
    oauth_section = setup.split("## 4. OAuth", 1)[1].split("## ", 1)[0]

    assert "เมื่อรัน `upload` ครั้งแรก โปรแกรมจะเปิด Google OAuth เอง" in oauth_section
    assert "ไม่ต้องสร้าง token แยกก่อนอัปโหลด" in oauth_section
    assert "`token_<account>.json`: OAuth credential เฉพาะเครื่อง; ถูก ignore" in setup
    assert "status page" in readme.casefold()
    assert "ไม่แสดง token" in readme
    assert "โดยไม่แสดง OAuth token" in setup
