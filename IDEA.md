# Agent-Powered Social Media Publishing Platform

## Vision

Build a platform that helps creators prepare, schedule, publish, and monitor content across their social channels while keeping account credentials secure and the creator in control of publication.

## Current product

This repository currently provides a local Windows CLI for YouTube publishing:

- Connect Google accounts through Desktop OAuth and verify that the selected account can access the requested YouTube channel. OAuth credentials stay local and are excluded from Git.
- Upload `.mp4` and `.mov` videos with matching cover images after automatic file validation. The uploader records job state, checks hashes to prevent duplicate uploads, and supports recovering failed work.
- Keep channel metadata in separate `profiles/<name>.json` files, with compatibility for the older `profile.json` setup.
- Schedule landscape and portrait videos as daily pairs through the YouTube API, then read the video state back to confirm the channel, privacy, and publish time.

The current implementation supports YouTube only. It is a user-invoked local tool; it does not provide other social network integrations, a cloud backend, background folder watching, AI-written captions, an approval dashboard, or engagement analytics.

## Product ideas

- **More social channels:** Add secure account connections and publishing integrations for additional networks.
- **AI writing assistance:** Draft captions and hashtags, then adapt the copy to each platform while leaving final review to the creator.
- **Media workspace:** Preview images and videos and validate them before publishing.
- **Scheduling and approvals:** Manage schedules across channels and add an approval step before publication. YouTube scheduling is already available in the current CLI; cross-platform coordination and approval workflows remain future work.
- **Publishing insights:** Present publishing status and failures across channels, then add engagement metrics. Local upload job state and failure recovery already exist; cross-channel monitoring and engagement analytics remain future work.
