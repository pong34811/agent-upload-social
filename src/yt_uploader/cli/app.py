"""Command dispatcher; every side-effecting service is injectable for offline tests."""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..auth import AuthorizationRequiredError, CredentialStore, CredentialStoreError
from ..config.profile import ProfileError, ProfileStore, resolve_profile_path
from ..jobs.store import JobStore
from ..models import UploadProfile
from ..pipeline.upload import BatchRunner
from .commands.auth import AuthCommands
from .commands.maintenance import MaintenanceCommands
from .commands.profile import ProfileCommands
from .commands.upload import UploadCommands
from .output import print_report, safe_error
from .parser import build_parser
from .services import OAuthService


class CliApp(ProfileCommands, AuthCommands, UploadCommands, MaintenanceCommands):
    """Run one command. With ``--json``, human text goes to stderr and stdout is one JSON object."""

    _print_report = staticmethod(print_report)
    _safe_error = staticmethod(safe_error)

    def __init__(
        self,
        *,
        runner: BatchRunner,
        profile_store: ProfileStore,
        credential_store: CredentialStore | None,
        oauth_service: Any,
        store: JobStore | None = None,
        credential_store_factory: Callable[[], CredentialStore] = CredentialStore,
    ) -> None:
        self.runner = runner
        self.profile_store = profile_store
        self.profile_root = Path(profile_store.path).parent
        self.credential_store = credential_store
        self.oauth = oauth_service
        self.store = store if store is not None else runner.store
        self._credential_store_factory = credential_store_factory
        self.json_mode = False
        self.result: dict[str, Any] = {}

    def run(self, argv: list[str]) -> int:
        self.json_mode = "--json" in argv
        self.result = {}
        if not self.json_mode:
            return self._run(argv)
        stdout = sys.stdout
        with contextlib.redirect_stdout(sys.stderr):
            code = self._run(argv)
        payload = {"ok": code == 0, "exit_code": code, **self.result}
        stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return code

    def _run(self, argv: list[str]) -> int:
        parser = build_parser()
        try:
            args = parser.parse_args(argv)
            self.result["command"] = " ".join(
                part for part in (args.command, getattr(args, f"{args.command}_command", None)) if part
            )
            if args.command == "profile" and args.profile_command == "list":
                return self._list_profiles()
            uses_profile = (
                args.command in {"dry-run", "upload", "schedule", "maintenance"}
                or (args.command == "profile" and args.profile_command != "list")
                or (args.command == "auth" and args.auth_command in {"login", "reauthorize"})
            )
            if uses_profile:
                for_setup = args.command == "profile" and args.profile_command == "setup"
                try:
                    selected_path = resolve_profile_path(
                        self.profile_root,
                        getattr(args, "profile_name", None),
                        for_setup=for_setup,
                    )
                except ProfileError as exc:
                    self._err(self._safe_error(exc))
                    return 2
                self.result["profile"] = selected_path.stem
                if Path(self.profile_store.path).resolve() != selected_path.resolve():
                    self.profile_store = ProfileStore(selected_path)
                    self.runner.profile_store = self.profile_store
            if args.command == "profile":
                return self._run_profile(args)
            if args.command == "auth" and args.auth_command == "login":
                return self._auth_login(args.channel)
            if args.command == "auth" and args.auth_command == "token":
                return self._auth_token(args.client_secrets, args.account)
            if args.command == "auth" and args.auth_command == "accounts":
                return self._auth_accounts()
            if args.command == "auth" and args.auth_command == "reauthorize":
                return self._auth_reauthorize()
            if args.command == "dry-run":
                return self._dry_run(args.folder, args.channel, args.file)
            if args.command == "upload":
                return self._upload(args)
            if args.command == "schedule":
                return self._schedule_video(args.video_id, args.publish_at)
            if args.command == "maintenance" and args.maintenance_command == "refresh":
                return self._maintenance_refresh()
            parser.error("unsupported command")
        except SystemExit as exc:
            return int(exc.code or 0)
        except (ProfileError, CredentialStoreError, AuthorizationRequiredError, ValueError, OSError) as exc:
            self._err(f"ตั้งค่าไม่พร้อม: {self._safe_error(exc)}")
            return 2
        except Exception as exc:
            # Do not print exception bodies from HTTP/OAuth libraries: they can contain URLs or API data.
            self._err(f"คำสั่งทำงานไม่สำเร็จ ({type(exc).__name__})")
            return 1
        return 2

    def _err(self, message: str) -> None:
        """Report a problem on stderr; JSON output keeps the first one as ``error``."""
        print(message, file=sys.stderr)
        self.result.setdefault("error", message)

    def _load_profile(self) -> UploadProfile | None:
        try:
            profile = self.profile_store.load()
        except ProfileError as exc:
            self._err(self._safe_error(exc))
            return None
        self.runner.profile = profile
        return profile

    def _save_profile(self, profile: UploadProfile) -> None:
        self.profile_store.save(profile)
        self.runner.profile = profile

    def _profile_revision(self) -> str:
        try:
            modified = self.profile_store.path.stat().st_mtime
        except (AttributeError, OSError):
            return "ยังไม่บันทึกบนดิสก์"
        return datetime.fromtimestamp(modified, timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    profile_store = ProfileStore()
    store = JobStore()
    try:
        profile = profile_store.load()
    except ProfileError:
        profile = UploadProfile(channel_alias="ยังไม่ได้ตั้งค่า")
    runner = BatchRunner(profile, store, None, profile_store=profile_store)
    return CliApp(
        runner=runner,
        profile_store=profile_store,
        credential_store=None,
        oauth_service=OAuthService(),
        store=store,
    ).run(list(sys.argv[1:] if argv is None else argv))
