# Milestone: first usable desktop release

## Target

**RelayAI Desktop Alpha 0.6.0 — macOS private dictation**

The milestone is complete when a new user can install one macOS application,
grant permissions, hold a global hotkey, speak, and receive locally transcribed
text in the field that was focused when recording began. They must be able to
inspect the resulting execution receipt without using the terminal.

This is the first usable desktop release, not the full V1 product promise.
Polished cloud refinement and approved automation remain supported by the core
but are not release blockers for this alpha.

## Entry state

RelayAI `0.4.1` already provides:

- policy-aware prepare and dispatch orchestration;
- safe local `whisper.cpp` audio-file execution;
- pipeline validation and SQLite receipt storage;
- local/cloud provider contracts; and
- tests across Python 3.11–3.13.

## Delivery sequence

### 0.5.0 — desktop foundation

- Create the Tauri/Rust/React macOS shell.
- Define a versioned, typed Python↔Tauri IPC protocol.
- Package and supervise the Python sidecar.
- Add sidecar health, cancellation, structured errors, and graceful shutdown.
- Implement Keychain-backed credential resolution.
- Add CI for Python, Rust, TypeScript, and IPC contract fixtures.

Exit criterion: the desktop shell can list pipelines, execute a fixture audio
run through the sidecar, cancel it, and display its receipt without bypassing
core policy checks.

### 0.6.0 — usable private dictation alpha

- Capture the selected microphone as supported `whisper.cpp` audio.
- Register push-to-talk and toggle global hotkeys.
- Preserve the application and field focused at recording start.
- Show a recording/transcribing overlay with cancel and recoverable errors.
- Add clipboard delivery and focused-field insertion with clipboard restoration.
- Provide microphone, Accessibility, and Input Monitoring permission guidance.
- Bundle or safely provision one local model using a checksum manifest.
- Add pipeline selection and a local history/receipt screen.
- Produce a signed and notarized macOS build with checksums and release notes.

## Definition of done

All of the following must be demonstrated on a clean supported macOS account:

- [ ] Installation and first launch require no Python, Rust, Node.js, or terminal.
- [ ] Push-to-talk begins recording within 250 ms at p95 on reference hardware.
- [ ] Releasing the hotkey transcribes locally and inserts into the original
      focused field.
- [ ] Cancel produces no insertion and leaves no retained audio artifact.
- [ ] A `local_only` run produces no external network traffic.
- [ ] Clipboard content is restored after successful and failed insertion.
- [ ] Missing microphone, denied/revoked permission, missing model, model checksum
      failure, sidecar crash, timeout, and insertion failure are recoverable.
- [ ] Raw transcript, final text, provider, local/cloud exposure, latency, and
      destination result are visible in the receipt UI.
- [ ] App restart preserves pipelines and history according to retention settings.
- [ ] Python, Rust, TypeScript, IPC, and macOS integration gates pass in CI.
- [ ] The signed artifact passes notarization, clean-install, update, and rollback
      smoke tests.

## Release-blocking tests

- Hotkey focus-preservation test across at least three application types.
- Microphone permission denial and revocation tests.
- Local-only network-isolation test.
- Clipboard restoration tests for success, cancellation, and insertion failure.
- Sidecar crash/restart and request-cancellation tests.
- Model manifest/checksum and first-run provisioning tests.
- End-to-end private dictation test on Intel and Apple Silicon where supported.

## Explicitly deferred

- Windows and Linux desktop builds
- Meeting and system-audio capture
- Wake words and continuous listening
- Cloud sync, accounts, teams, and mobile keyboards
- Autonomous multi-step agents and plugin marketplace
- MCP client/server UI

These items must not delay the private-dictation alpha unless they become
necessary to satisfy a release-blocking safety or reliability criterion.
