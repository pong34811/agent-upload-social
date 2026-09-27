# YouTube Scheduled Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add explicit YouTube scheduled publishing for existing private videos and orientation-paired upload batches.

**Architecture:** Keep schedule timestamps in upload metadata so new videos are sent to YouTube as Private with `status.publishAt`. Add an API update path for completed jobs that verifies channel ownership/current privacy and preserves the existing mutable status fields. The CLI exposes a one-video scheduling command, an orientation-paired `upload --schedule-from` mode, and an explicit OAuth reauthorization command.

**Tech Stack:** Python 3.13, argparse, google-api-python-client, SQLite job store, YouTube Data API v3.

**Spec:** `docs/superpowers/specs/2026-09-27-youtube-scheduling.md`

## Global Constraints

- Schedule only after the YouTube API audit and channel checks pass.
- Use only the exact user-selected folder; never scan a parent, neighbor, or drive.
- Keep the scheduled video private until its future `publishAt` timestamp.
- Require an explicit CLI call; do not add watchers, delayed local jobs, or automatic uploads.
- Do not print or log OAuth tokens, client secrets, resumable session URLs, or API response bodies.
- Preserve YouTube's existing mutable `status` fields when setting `publishAt`.

## Review Focus

- An offset-less timestamp or a timestamp in the past must fail before OAuth/API changes.
- Square or mismatched orientation counts must stop the full schedule batch before any upload or schedule update.
- Existing non-private or wrong-channel videos must not be updated.
- Updating a video must preserve its existing `embeddable`, `license`, `publicStatsViewable`, `selfDeclaredMadeForKids`, and `containsSyntheticMedia` values.
- Old OAuth credentials must be directed to reauthorization before a scheduled update.

---

### Task 1: API scheduling and OAuth reauthorization

**Files:**
- Modify: `src/katy404_youtube_agent/models.py`
- Modify: `src/katy404_youtube_agent/store.py`
- Modify: `src/katy404_youtube_agent/auth.py`
- Modify: `src/katy404_youtube_agent/youtube.py`
- Modify: `src/katy404_youtube_agent/cli.py`

**Interfaces:**
- `VideoMetadata.publish_at: str | None = None`
- `YouTubeApi.schedule_video(video_id: str, channel_id: str, publish_at: datetime) -> None`
- `CredentialStore.has_required_scopes(account_key: str) -> bool`
- `auth reauthorize` runs a fresh Desktop consent using the current `SCOPES`.

- [ ] Add the `publish_at` metadata field and allow `publish_at` in stored API snapshot fields.
- [ ] Add `youtube.force-ssl` to the OAuth scope set and expose explicit reauthorization without printing credential data.
- [ ] Fetch current video status and channel ID, reject non-owned/non-private videos, and update status while preserving existing mutable fields.
- [ ] Reject schedule timestamps without an offset or at/before the current time.
- [ ] Manually inspect error handling to ensure API response bodies are never surfaced.

### Task 2: CLI scheduling and paired batch planning

**Files:**
- Create: `src/katy404_youtube_agent/scheduling.py`
- Modify: `src/katy404_youtube_agent/runner.py`
- Modify: `src/katy404_youtube_agent/cli.py`
- Modify: `src/katy404_youtube_agent/store.py`

**Interfaces:**
- `parse_publish_at(value: str) -> datetime`
- `plan_daily_pairs(items: Sequence[tuple[MediaCandidate, MediaFacts]], start: datetime) -> dict[Path, datetime]`
- `schedule --video-id ID --publish-at RFC3339` schedules a completed locally-managed video.
- `upload --schedule-from RFC3339` assigns same-day timestamps to the Nth landscape and Nth portrait.

- [ ] Plan slots deterministically from sorted filenames, reject square media or unequal orientation counts, and require a complete preflight before side effects.
- [ ] Gate scheduled public publishing on the API audit before OAuth is loaded; request missing OAuth scope during the scheduled upload command.
- [ ] Schedule complete local jobs in place and upload pending jobs with Private plus `publishAt`.
- [ ] Verify CLI help and source syntax without calling YouTube or uploading files.

### Task 3: Operator documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/operations.md`

- [ ] Document reauthorization, the one-video schedule command, paired batch scheduling, and the required profile gates.
- [ ] Clarify that no background uploader or folder watcher is introduced.
- [ ] Document direct batch scheduling without a separate review/approval step.
