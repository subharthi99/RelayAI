# Changelog

All notable changes to RelayAI are documented here.

The project follows [Semantic Versioning](https://semver.org/).

## [0.4.1] — 2026-08-08

### Fixed

- Explicitly close every short-lived SQLite connection, preventing Python 3.13
  `ResourceWarning` output and file-descriptor leaks.
- Update GitHub Actions to Node.js 24-compatible checkout and Python setup
  actions.

## [0.4.0] — 2026-08-08

### Added

- Allowlisted local `whisper.cpp` speech provider using the upstream
  `whisper-cli` JSON contract.
- `relayai run` for executing a pipeline from FLAC, MP3, OGG, or WAV audio.
- Named model path allowlists with optional SHA-256 verification.
- Prepare-only execution, explicit destination approvals, optional file roots,
  and automatic SQLite pipeline/run persistence.
- Passive `builtin.result` destination for returning text to headless callers.
- Runnable local audio pipeline example and detailed setup guide.

### Security

- `whisper-cli` executes without a shell and accepts no pipeline-controlled
  executable, model path, or arbitrary argument list.
- Child processes are killed on timeout or cancellation.
- Temporary audio/output files are isolated and removed after execution.
- Process diagnostics, audio input, and JSON output have explicit bounds.

## [0.3.0] — 2026-07-27

### Added

- Contributor guide, community code of conduct, and security reporting policy.
- Structured GitHub bug-report and feature-proposal forms.
- Pull-request checklist and code ownership rules for safety-critical surfaces.
- GitHub Actions testing across Python 3.11, 3.12, and 3.13.
- OpenAI-compatible speech-transcription and text-refinement adapters.
- Separate local and network provider configurations with application-owned
  endpoint allowlists.
- Injectable credential resolver and standard-library asynchronous HTTP
  transport.
- Provider integration and security documentation.

### Security

- Local providers accept only loopback endpoints; network providers require
  HTTPS.
- Provider redirects, embedded URL credentials, arbitrary endpoint URLs,
  oversized uploads/responses, unknown settings, and malformed replies are
  rejected.
- Bearer credentials are resolved from opaque IDs and checked for header
  injection before requests.

## [0.2.0] — 2026-07-26

### Added

- `relayai` command-line entry point.
- Pipeline validation and safe inspection commands.
- SQLite database initialization, pipeline import/list/export commands.
- Receipt history list/show commands.
- Filtered, explicit-confirmation history purge.
- Authenticated, read-only HTTP API restricted to `127.0.0.1`.
- Pipeline and receipt list/detail API routes.
- Redacted run summaries that exclude transcript text.
- Storage methods for receipt listing and filtered deletion.
- CLI, API, storage-retention, authentication, and binding tests.
- Local API and deployment documentation.

### Security

- API startup requires a bearer token of at least 32 characters.
- Bearer tokens are compared using constant-time comparison.
- Tokens are loaded from environment variables rather than command arguments.
- API responses disable caching and MIME sniffing.
- The server rejects wildcard and non-loopback bind addresses.
- History purge requires both a filter and `--yes`.

## [0.1.0] — 2026-07-20

### Added

- Versioned pipeline definitions and JSON Schema.
- Separate speech, refinement, context, and destination contracts.
- Policy preflight and local-only enforcement.
- Two-phase prepare/dispatch execution with approval gates.
- Raw-transcript fallback when refinement fails.
- Safe file, webhook, and shell-free script destinations.
- SQLite pipeline and receipt persistence.
