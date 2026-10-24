"""Project-root locations for local profiles, credentials, and job state."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "profiles"
LEGACY_PROFILE_PATH = PROJECT_ROOT / "profile.json"
DB_PATH = PROJECT_ROOT / "state.sqlite3"
CLIENT_SECRETS_PATH = PROJECT_ROOT / "client_secrets.json"
OWNER_TOKEN_PATH = PROJECT_ROOT / "token_waritnan34811.json"
