# NEURON Android

A mobile client for NEURON SMART JOURNAL. The Android app loads the independently deployed mobile API dashboard in a WebView.

## Isolation and security
- The app and API are maintained on this branch; the Telegram bot's `main.py` is not imported, executed, or modified.
- Keep `BOT_TOKEN`, `DATABASE_URL`, and `JWT_SECRET` on the server only. Never embed them in the APK.
- Telegram Login Widget HMAC is validated by the API. Short-lived one-time handoff codes are exchanged for a signed app session.
- Super Admin access is restricted server-side to owner Telegram ID 6359925487.

## Current mobile features
- Teacher: subject list, create subject/student, enter scores, attendance and payment state, view recent journal history.
- Student: view scores, attendance, payment state and teacher note.
- Parent: view linked children, their scores, attendance, payment state and teacher notes.
- Super Admin: overview counts, teacher approval and plan editing.
- Parent score notifications are sent by the separate API after score changes when the Telegram bot token is configured.

## Known setup requirements
- Render API must have `BOT_TOKEN`, `DATABASE_URL`, `JWT_SECRET`, and `BOT_USERNAME`.
- Configure Telegram Login Widget domain in @BotFather to `neuron-android-api.onrender.com`.
- This is an evolving MVP. Validate each role against real accounts and the Neon schema before production use. The debug APK is not a Play Store release.

## Build
GitHub Actions builds a debug APK from this directory. Download the `neuron-debug-apk` artifact from a successful workflow run.
