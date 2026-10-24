---
name: youtube-upload
description: Upload or schedule a folder of clips to a YouTube channel with this project's local `yt-upload` CLI. Use when the user explicitly asks to upload a folder or schedule a video batch through this project.
---

# YouTube Upload

Uploader version: 0.4.0 (`src/yt_uploader/__init__.py` and `pyproject.toml`).

Use this skill only for an explicit request to upload or schedule videos through this repository. Folder discussion, inventory requests, and planning are not upload authorization.

## Workflow

1. Use the exact folder and channel the user supplied (from this request or earlier in the session); do not ask again. Read only that folder's top-level files. Never search a parent folder, neighboring folder, or drive.
2. Run `profile list --json`. When more than one profile exists, pass `--profile <name>` on every channel command; pick the profile that matches the user's channel. Do not run `profile setup` or change profile values without a reason.
3. Run `upload ... --json` directly; it runs the preflight itself. Run `dry-run ... --json` only when the user wants a preview, and report ready/needs-fixing counts briefly.
4. For a scheduled batch, pass the user's RFC 3339 time with its UTC offset as `--schedule-from`. Landscape and portrait clips are paired by filename, one pair per day. Never invent or shift a schedule.
5. If the saved credential lacks the metadata-edit scope, a scheduled upload opens Google OAuth itself; complete it only for this explicit request.
6. Report from the JSON: `summary` counts, each item's `status` and `video_url`, `publish_at` for scheduled items, and `stopped_reason`/`error` when `ok` is false. A schedule counts as done only when the CLI confirmed it (items have `publish_at`).

## Commands

Run from the project root:

```powershell
.\.venv\Scripts\yt-upload.exe profile list --json
.\.venv\Scripts\yt-upload.exe upload --profile "<profile>" --folder "<user folder>" --channel "<user channel>" --json
.\.venv\Scripts\yt-upload.exe upload --profile "<profile>" --folder "<user folder>" --channel "<user channel>" --schedule-from "<RFC3339 time>" --json
.\.venv\Scripts\yt-upload.exe dry-run --profile "<profile>" --folder "<user folder>" --channel "<user channel>" --json
```

## Files and metadata

- Videos: `.mp4`/`.mov`; each needs a `.jpg`/`.jpeg`/`.png` thumbnail with the same basename. Portrait files end in `_9x16`.
- Titles come from the filename; descriptions, tags, privacy, audience, and synthetic-media declarations come from the profile.
- Portrait Shorts hashtags come from the profile: `vertical_short_hashtags` if set, otherwise `shorts_hashtag_template` (`{channel}`, `{game}` placeholders). To change a channel's hashtags, edit that profile file, not the code.
- OAuth tokens live at the repo root as `token_<oauth_account_key>.json` and load automatically for the selected profile. Do not ask the user for a token path.

## Failures

- `ok: false` → report `error`/`stopped_reason` and the affected files, then stop. Never skip channel-ownership, broken-file, changed-hash, quota, or authorization errors; continue only after the cause is fixed.
- `error` mentions an ambiguous channel → ask the user for the channel handle or channel ID.
- `api_audit_passed` is not a local gate and not proof of Google's project status; do not change it. If YouTube restricts the project or rejects a request, report the real result and stop.
- Never print, copy, or log OAuth tokens, client secrets, resumable session URLs, or API response bodies.
- Do not create background uploads, folder watchers, or scheduled local jobs.
