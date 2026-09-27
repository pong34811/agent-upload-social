---
name: kt404-youtube-upload
description: Upload or schedule videos to YouTube with the local Katy404 uploader. Use when the user explicitly asks to upload a folder or schedule a video batch through this project.
---

# Katy404 YouTube Upload

Use this skill only for an explicit request to upload or schedule videos through `D:\agent-upload-social`. Folder discussion, inventory requests, and planning are not upload authorization.

## Workflow

1. Use the exact folder and YouTube channel supplied by the user. Use session context if they already supplied them; do not ask for them again. Never search a parent folder, neighboring folder, or drive.
2. Use the saved channel profile and OAuth account in `profile.json`. Do not run `profile setup` or repeat prompts when the saved profile is ready.
3. Run `upload` directly. It performs the preflight itself. Run `dry-run` only when the user asks for a preview or inspection before sending.
4. For scheduled batches, pass the user's requested RFC 3339 time, including its UTC offset, with `--schedule-from`. The uploader pairs filename-sorted landscape and portrait clips one of each per day. Do not change the start time or invent a schedule.
5. Scheduled uploads request the necessary OAuth consent from Google automatically if the saved credential lacks the metadata-edit scope. Complete that flow only for the explicit upload request.
6. Schedule through the API with `private` and `publishAt`. Report success only after API readback confirms the video, channel, privacy, and requested instant. The legacy `api_audit_passed` field is not a local blocker or proof of Google's project status; do not change it to enable uploads. If YouTube restricts the project or rejects the request, report the actual result and stop.
7. Report the number uploaded, scheduled, skipped, or failed and include YouTube video links the CLI returned. Do not add a separate review/approval workflow.

## Command templates

Run these from the project root:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --folder "<user-provided-folder>" --channel "<user-provided-channel>"
```

For a scheduled landscape/portrait batch:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --folder "<user-provided-folder>" --channel "<user-provided-channel>" --schedule-from "<user-provided-RFC3339-time>"
```

## Handling failures

- Follow the CLI result for missing files, invalid media, channel mismatch, changed file hashes, quota, or authorization errors. Report the specific issue and stop; never guess a value or skip an error to continue.
- Never print, copy, or log OAuth tokens, client secrets, resumable session URLs, or API response bodies.
- Do not create background uploads, folder watchers, or scheduled local jobs. The requested schedule is sent to YouTube by the explicit command.
