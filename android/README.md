# NEURON Android

This Android wrapper is developed on the separate `android-apk` branch. It does not replace or edit the Telegram Mini App.

## Current integration contract

The Android login screen expects:

- `POST /api/android/login`
- JSON body: `{"code":"one-time-code"}`
- Success response: `{"session_token":"short-lived-or-rotating-session-token"}`

The Mini App must then support the `neuron_android_token` session and the backend must validate it on protected API routes. These backend pieces are intentionally not enabled yet; do not distribute this scaffold as a working app until they are implemented and tested.

## Build

Run the GitHub Actions workflow **Build NEURON Android APK** on the `android-apk` branch and enter the HTTPS Render service URL. Download the APK from the workflow artifact.

The current workflow builds a debug APK for installation/testing. A signed release APK requires a private signing key stored in GitHub Actions secrets; never commit keystore files or passwords.
