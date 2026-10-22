# Plan: Scheduled upload for Aommi-mama

## Goal
Upload every valid landscape/portrait video pair from the explicitly supplied `vdo` folder to the `aommi-mama` channel and schedule both members of each pair as Private-to-Public releases beginning 9 October 2026 at 07:30 Thailand time, one pair per day.

## Current context / assumptions
- Workspace: `D:\agent-upload-social`; branch `master`. Last observed `git status --short --branch` was clean and tracking `origin/master`.
- Project is a Python CLI (`kt404-youtube`) with named channel profiles. Use `--profile aommi-mama` explicitly; profile path is `profiles/aommi-mama.json`. Its configured channel ID is `UCRT33iJwDqTPcslrl8vY8kA`, alias `Aomi-mama【DL】`, and privacy default `public`.
- The existing CLI supports scheduled batch upload with `--schedule-from RFC3339`; scheduler groups direct-child media by orientation, sorts each group by filename, and assigns one landscape plus one portrait to the same daily slot. The CLI forces those videos to `private` while setting `publishAt`.
- User confirmed that both orientations of a filename-matched pair should publish at the same time on day one, followed by subsequent pairs on successive days; user confirmed public scheduled release.
- Interpret 7:30 A.M. as 07:30 in Thailand (UTC+07:00), yielding `2026-10-09T07:30:00+07:00`.
- At planning time, read-only inventory found three landscape/portrait basename pairs, each with a same-basename JPG thumbnail, plus `desktop.ini`; no nested traversal is permitted. Media health, duration/orientation, hash stability, and actual readiness must be established by the uploader's dry-run/preflight at execution.
- Do not print, copy, or log OAuth token, client secret, resumable URL, or raw API response. Never bypass channel ownership, media, hash, quota, or authorization failures.
- This is an operational upload, not a code change: no TDD or project-code commit is appropriate. The only plan artifact should be saved now; actual upload is a later, explicitly authorized execution step.

## Architecture / proposed approach
Use the existing CLI and named profile rather than modifying code or profile settings. First run the explicit-folder dry-run and check credentials/scopes without exposing secrets; if any prerequisite fails, stop and report the exact safe error instead of starting the batch. If preflight confirms every intended item is ready and the OAuth grant has scheduling scope, run the full scheduled batch once with a `+07:00` timestamp; the existing runner will validate ownership, pair orientations, upload as Private, set the schedule, and report video links. Verify the exact target channel, Private privacy, and requested publish timestamp by reading the uploaded video metadata back from YouTube before reporting success.

## Step-by-step tasks

1. **Confirm the CLI and current branch state (2–5 min).** In `D:\agent-upload-social`, run:
   ```bash
   git status --short --branch
   .venv/Scripts/python.exe -m katy404_youtube_agent.cli --help
   ```
   Expected: branch `master` tracks `origin/master`, no unintended changes; CLI help describes supported subcommands. If module invocation is unsupported, use the installed entrypoint ` .venv/Scripts/kt404-youtube.exe --help` (without the leading space). Do not switch branches, discard files, or commit.

2. **Verify the selected profile safely (2–5 min).** Run:
   ```bash
   .venv/Scripts/kt404-youtube.exe profile show --profile aommi-mama
   ```
   Expected: shows alias `Aomi-mama【DL】`, channel ID `UCRT33iJwDqTPcslrl8vY8kA`, account key `aommi-mama`, and profile privacy; explicitly says it does not show OAuth token/client secret. Stop if the profile is missing, invalid, points to a different channel, or channel ID does not match. Do not edit the profile to force it through.

3. **Dry-run the exact folder only (2–5 min).** Run:
   ```bash
   .venv/Scripts/kt404-youtube.exe dry-run --profile aommi-mama --channel "UCRT33iJwDqTPcslrl8vY8kA" --folder "G:\My Drive\Projects\Aomi-mama\2026-08\【LIVE】ว่างหลังจากเดบิว จ้ะ\vdo"
   ```
   Expected based on the inventory: `วิดีโอที่พร้อม: 6` and `ข้าม/ต้องแก้ก่อนอัปโหลด: 0`. This command scans only direct child files; it is local and does not upload. If readiness differs, inspect/report safe filenames and error codes, then stop for user direction—do not silently omit a requested orientation or proceed with an incomplete scheduled batch.

4. **Confirm OAuth scope/authorization before any upload (2–5 min).** Do not inspect or print token JSON. If the configured local OAuth grant cannot be used for upload + metadata edit/scheduling, use the project’s guided `auth reauthorize --profile aommi-mama` flow; the user must complete any Google consent in the opened browser. The command’s expected successful output confirms the OAuth account and metadata-edit permission, without uploading. If authorization is denied/revoked or consent cannot be completed, stop and report; never ask the user to paste a token/code into chat.

5. **Check schedule pairing before executing batch (2–5 min).** The directory inventory contains the three stems `เจอ Brum ป่าเลยกดออกเกมกลับมาโดน 30 นาที`, `หมาบ่นเกมหมา`, and `อีโกวีทูปเบอร์`, each with matching non-`_9x16` and `_9x16` `.mov` assets and matching JPGs. The existing planner sorts landscape and portrait groups by path name and pairs same-rank names, so expected slots are:
   - 2026-10-09 07:30 +07:00: landscape + portrait of `เจอ Brum ป่าเลยกดออกเกมกลับมาโดน 30 นาที`
   - 2026-10-10 07:30 +07:00: landscape + portrait of `หมาบ่นเกมหมา`
   - 2026-10-11 07:30 +07:00: landscape + portrait of `อีโกวีทูปเบอร์`
   Execute only if the dry-run confirmed all six assets and the user-approved pairing semantics still match. If pair order is uncertain or naming has changed, stop before upload.

6. **Run one scheduled upload batch (long-running; 2–5 min to start/monitor).** Execute exactly:
   ```bash
   .venv/Scripts/kt404-youtube.exe upload --profile aommi-mama --channel "UCRT33iJwDqTPcslrl8vY8kA" --folder "G:\My Drive\Projects\Aomi-mama\2026-08\【LIVE】ว่างหลังจากเดบิว จ้ะ\vdo" --schedule-from "2026-10-09T07:30:00+07:00"
   ```
   Expected preflight: channel ID above; six videos; zero skipped; privacy `private`; schedule plan of six clips, three days, one landscape + one portrait per day; first slot `2026-10-09T07:30:00+07:00`; final slot `2026-10-11T07:30:00+07:00`. Expected completion: six uploads and six confirmed scheduled videos, zero failed/pending, subject to actual YouTube/API outcome. Do not add `--limit` or `--force-private`; scheduled batch mode forbids them. If the command fails due to quota, API project restriction, OAuth, ownership, media, or hash issue, preserve the reported outcome and stop; do not retry blindly or bypass the failure.

7. **Verify all six schedules by API read-back (2–5 min).** For each returned video ID, read the video metadata using the app’s read/refresh capability or YouTube Studio/API and check: channel ID `UCRT33iJwDqTPcslrl8vY8kA`, `privacyStatus=private`, and `publishAt` matches the planned timestamp (allow equivalent UTC representations, compare instants). Confirm all six IDs map to intended filenames/orientations. Existing `YouTubeApi` scheduling path performs read-back confirmation per video; still inspect the final per-item CLI result and ensure there are no failed/pending items. Never include raw API response bodies in logs or response. Report only verified links and schedule times; distinguish any unverified/failed item explicitly.

## Tests / validation
- No code changes are planned; TDD and project tests are not applicable to this operational task. Do not run `pytest` as a substitute for validating uploads.
- Local validation: profile show returns the specified channel; dry-run reports exactly six ready media and zero skipped/failed; uploader preflight prints the expected three-day paired schedule.
- External validation: all six uploads return stable video IDs/links; YouTube read-back confirms ownership, Private privacy, and publishAt for each ID. A successful process exit alone is insufficient.
- Do not commit or push operational data, credentials, tokens, or plan execution results.

## Risks, tradeoffs, and open questions
- Scheduling a batch has an irreversible external side effect: videos are uploaded to the channel and schedules are set. The separate execution turn must follow all stop gates and report results; this plan itself authorizes no upload.
- The inspected local grant appeared to lack the metadata-edit OAuth scope marker needed by the app’s `has_required_scopes` check. If this remains true at execution, reauthorization will be required and cannot be assumed successful.
- The profile’s `api_audit_passed` value is false, but project instructions say not to use that flag as a local upload gate or modify it on the user’s behalf.
- If YouTube rejects this OAuth project (for example, an upload restriction), or any API/quota/auth error occurs, report the real result and stop.
- Media inventory is a snapshot; filenames, bytes, and folder state may change before execution. Dry-run and upload-time hash checks are authoritative; never proceed past a changed-file/hash warning.
- Filename sorting determines daily pairing. User approved matched orientations scheduled together; exact association/order is based on the observed matching stems above. If the folder contents differ when executing, regenerate the plan and reconfirm any changed ordering rather than guessing.
