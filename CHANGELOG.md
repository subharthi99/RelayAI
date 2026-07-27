# Changelog

All notable changes to RelayAI are documented here.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Contributor guide, community code of conduct, and security reporting policy.
- Structured GitHub bug-report and feature-proposal forms.
- Pull-request checklist and code ownership rules for safety-critical surfaces.
- GitHub Actions testing across Python 3.11, 3.12, and 3.13.

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
