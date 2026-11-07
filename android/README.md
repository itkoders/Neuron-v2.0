# NEURON Android

Must remain isolated from the Telegram bot runtime and source code.

## Non-negotiable boundaries
- Android source lives only under `android/`.
- The Android app must never import, execute, or launch `main.py`.
- Do not add `BOT_TOKEN`, database credentials, or AI provider keys to the APK.
- Existing API authorization must remain server-verified. A native app must not fabricate Telegram WebApp `initData`.

## Current stage
This is the Android build foundation only. The existing Mini App API authenticates requests by validating Telegram-signed `initData`; a standalone Android app does not receive that value automatically. A secure native sign-in handoff must be designed before enabling real account access. No bot-side authentication changes are included in this stage.

## Build
GitHub Actions builds a debug APK from this directory. The APK is for installation/testing and is not a production-signed release.
