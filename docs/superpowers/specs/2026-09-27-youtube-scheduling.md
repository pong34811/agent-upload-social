# YouTube Scheduled Publishing

## Approved behavior

- Schedule one landscape and one portrait video for each day from 1 through 12 October 2026, at 07:30 Asia/Bangkok. The two videos for a day use the same publish timestamp.
- Add a command to schedule an already-uploaded private video and an explicit schedule option to a full upload batch.
- Keep the API audit and channel-ownership checks. A scheduled video is private until its future publish time, but the operation is treated as intended public publishing.
- Add the YouTube metadata-edit OAuth scope; request Desktop OAuth consent automatically when a scheduled upload lacks it.
- Scheduling must be a direct YouTube API operation triggered by an explicit CLI command. Do not add a watcher or a background uploader.

## Scheduling rules

- Accept only RFC 3339 timestamps with an explicit UTC offset. Reject past timestamps so they cannot publish immediately by accident.
- For a scheduled batch, scan only the exact selected folder, require every video and thumbnail to pass preflight, reject square videos, and require equal landscape/portrait counts.
- Sort filenames within each orientation. Pair the Nth landscape with the Nth portrait on `start + N days`.
- Set `status.privacyStatus=private` with `status.publishAt` for uploads. For an already-uploaded video, verify it belongs to the configured channel and is currently private before updating it.
- Preserve all mutable status fields returned by YouTube when calling `videos.update(part="status")`; send privacyStatus as private with publishAt.
- Existing completed jobs in the selected batch are scheduled in their planned slot instead of being re-uploaded.
- Start a full scheduled batch directly after preflight and required YouTube checks pass; do not add an extra review/approval step.
