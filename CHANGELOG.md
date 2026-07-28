# Changelog

All notable changes to RelayAI are documented here.

The project follows [Semantic Versioning](https://semver.org/).

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
