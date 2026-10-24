"""Argument parser for every ``yt-upload`` command."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..auth import OWNER_ACCOUNT_KEY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-upload",
        description="ตัวช่วยอัปโหลดวิดีโอ YouTube ในเครื่องสำหรับช่องที่เลือก",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="ตั้งค่าและจัดการโปรไฟล์ช่อง")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list", help="แสดงโปรไฟล์ช่องที่บันทึกไว้")
    setup = profile_commands.add_parser("setup", help="เชื่อม OAuth เลือกช่อง และตั้งค่าโปรไฟล์สำหรับอัปโหลด")
    add_profile_selection(setup)
    setup.add_argument("--client-secrets", type=Path, help="พาธ Desktop OAuth JSON (ค่าเริ่มต้นคือไฟล์ในโฟลเดอร์โปรเจกต์)")
    setup.add_argument("--oauth-account", default=OWNER_ACCOUNT_KEY, help="ชื่อ credential ที่จะใช้ เช่น channel2")
    setup.add_argument("--replace-existing", action="store_true", help="ตั้งค่าโปรไฟล์ใหม่และเก็บสำเนาโปรไฟล์เดิมไว้")
    show = profile_commands.add_parser("show", help="แสดงค่าที่ตั้งไว้โดยไม่แสดง token")
    add_profile_selection(show)
    privacy = profile_commands.add_parser("set-privacy", help="เปลี่ยนความเป็นส่วนตัวเริ่มต้น")
    add_profile_selection(privacy)
    privacy.add_argument("status", choices=("private", "unlisted", "public"))
    audit = profile_commands.add_parser("set-api-audit-status", help="บันทึกข้อมูล audit เดิม; ไม่มีผลต่อการเรียก API")
    add_profile_selection(audit)
    audit.add_argument("status", choices=("passed", "not-passed"))
    delete_data = profile_commands.add_parser("delete-account-data", help="ลบข้อมูล API ของช่องในเครื่อง")
    add_profile_selection(delete_data)
    delete_data.add_argument("--channel-id")
    retry_failed = profile_commands.add_parser("retry-failed", help="เตรียมงานที่ล้มเหลวหนึ่งไฟล์ให้ลองใหม่")
    add_profile_selection(retry_failed)
    retry_failed.add_argument("--path", required=True, type=Path)
    revoke = profile_commands.add_parser("revoke-authorization", help="ยกเลิกสิทธิ์ OAuth และลบข้อมูลช่อง")
    add_profile_selection(revoke)
    revoke.add_argument("--channel-id")

    auth = commands.add_parser("auth", help="เชื่อมบัญชี Google สำหรับ YouTube")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_commands.add_parser("login", help="สร้าง/ตรวจ OAuth credential โดยไม่อัปโหลดวิดีโอ")
    add_profile_selection(login)
    login.add_argument("--channel", required=True, help="ชื่อช่อง, handle หรือ channel ID ที่ต้องการเชื่อม")
    token = auth_commands.add_parser(
        "token",
        help="สร้างหรือตรวจ OAuth credential โดยไม่เรียก YouTube API หรืออัปโหลดวิดีโอ",
    )
    token.add_argument("--client-secrets", required=True, type=Path, help="พาธ Desktop OAuth JSON")
    token.add_argument("--account", default=OWNER_ACCOUNT_KEY, help="ชื่อใหม่สำหรับเก็บ credential แยกจากบัญชีเดิม")
    auth_commands.add_parser("accounts", help="แสดงชื่อ credential ที่บันทึกไว้ โดยไม่แสดง token")
    reauthorize = auth_commands.add_parser("reauthorize", help="ขอ OAuth consent ใหม่เพื่อเพิ่มสิทธิ์ตั้งเวลาเผยแพร่")
    add_profile_selection(reauthorize)

    for name in ("dry-run", "upload"):
        command = commands.add_parser(name, help="ตรวจไฟล์ในโฟลเดอร์ที่ระบุ" if name == "dry-run" else "อัปโหลดโฟลเดอร์ที่ระบุ")
        add_profile_selection(command)
        command.add_argument("--folder", required=True, type=Path)
        command.add_argument("--channel", required=True)
        command.add_argument("--file", help="เลือกชื่อไฟล์ระดับบนสุดในโฟลเดอร์ที่ระบุ")
        if name == "upload":
            command.add_argument("--limit", type=int)
            command.add_argument("--force-private", action="store_true")
            command.add_argument(
                "--schedule-from",
                help="ตั้งเวลาแนวนอน/แนวตั้งเป็นคู่รายวัน เริ่มจาก RFC 3339 เช่น 2026-10-01T07:30:00+07:00",
            )

    schedule = commands.add_parser("schedule", help="ตั้งเวลาเผยแพร่วิดีโอ Private ที่อัปโหลดแล้ว")
    add_profile_selection(schedule)
    schedule.add_argument("--video-id", required=True)
    schedule.add_argument(
        "--publish-at", required=True,
        help="RFC 3339 พร้อม UTC offset เช่น 2026-10-01T07:30:00+07:00",
    )

    maintenance = commands.add_parser("maintenance", help="ดูแลการเชื่อมต่อและข้อมูล API")
    maintenance_commands = maintenance.add_subparsers(dest="maintenance_command", required=True)
    refresh = maintenance_commands.add_parser("refresh", help="ตรวจสิทธิ์ช่องและปรับปรุงข้อมูลตามรอบเก็บรักษา")
    add_profile_selection(refresh)
    _add_json_flag(parser)
    return parser


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    """Give every leaf command ``--json`` so agents can place it anywhere after the command."""
    subparsers = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not subparsers:
        parser.add_argument(
            "--json",
            action="store_true",
            help="พิมพ์ผลเป็น JSON หนึ่งก้อนทาง stdout; ข้อความอื่นไป stderr",
        )
        return
    for action in subparsers:
        for child in action.choices.values():
            _add_json_flag(child)


def add_profile_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        dest="profile_name",
        metavar="NAME",
        help="เลือกไฟล์ profiles/NAME.json; ระบุเมื่อตั้งค่าโปรไฟล์แยกหรือเมื่อมีหลายโปรไฟล์",
    )
