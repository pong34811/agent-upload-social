from pathlib import Path


def test_setup_docs_name_required_project_oauth_and_policy_gates():
    setup = Path("docs/setup.md").read_text(encoding="utf-8")
    policy = Path("docs/privacy-policy.md").read_text(encoding="utf-8")

    assert "mfk110" in setup
    assert "Desktop" in setup
    assert "security.google.com/settings/security/permissions" in policy
    assert "30 วัน" in policy
    assert "7 วัน" in policy


def test_terms_and_privacy_drafts_include_required_user_links_and_owner_contact():
    policy = Path("docs/privacy-policy.md").read_text(encoding="utf-8")
    terms = Path("docs/terms-of-use.md").read_text(encoding="utf-8")

    assert "policies.google.com/privacy" in policy
    assert "ช่องทางติดต่อเจ้าของโปรเจกต์" in policy
    assert "www.youtube.com/t/terms" in terms


def test_readme_contains_katy404_paths_and_pilot_sequence():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert r"G:\My Drive\Projects\Katy404\2026-09\vdo" in readme
    assert "--limit 1 --force-private" in readme
    assert "profile approve-pilot" in readme
