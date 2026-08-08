# RelayAI Deployment Guide

This document describes how to validate, package, distribute, install, and roll
back the current RelayAI Python core. It also defines the deployment boundary for
the planned macOS desktop application.

> [!IMPORTANT]
> RelayAI does not yet ship a desktop executable or hosted service. The only
> deployable artifact today is the `relayai-core` Python package and its
> authenticated loopback API process. Sections marked **Planned** describe release
> requirements, not commands that work in the current repository.

## 1. Deployment model

The current package is an embeddable orchestration library:

```text
Host application
  -> relayai-core
      -> registered speech/refinement/context/destination adapters
      -> SQLite pipeline and receipt store
```

It does not capture audio or register global hotkeys. The optional `relayai serve`
command opens a read-only HTTP API on `127.0.0.1`; it cannot bind to an external
interface. A host process owns adapter composition, lifecycle, credentials, and
the database location.

Supported current deployment targets:

- developer source checkout;
- isolated Python virtual environment;
- private or public Python wheel distribution; and
- embedding in a future desktop sidecar process.

## 2. Runtime requirements

| Requirement | Current core | Planned desktop |
| --- | --- | --- |
| Operating system | Any OS supported by Python 3.11+ | macOS first |
| Python | 3.11 or newer | Bundled sidecar runtime or packaged executable |
| Runtime packages | Python standard library only | Tauri/platform dependencies |
| Persistent storage | SQLite path supplied by host | Application Support directory |
| Secrets | Credential references only | OS keychain |
| Network | Optional authenticated loopback API and registered adapters | User-policy dependent |

Build tooling may require `build`, `pip`, and `setuptools`; these are build-time
tools and are not imported by `relayai-core` at runtime.

## 3. Source deployment

Use this mode for development and local integration.

```sh
git clone <repository-url>
cd RelayAI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests -v
relayai --version
```

For CI or a read-only checkout, installation is optional:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### Verification

A valid source deployment must satisfy all of the following:

- the full unit suite passes;
- every file in `examples/*.pipeline.json` loads through `load_pipeline`;
- `schemas/pipeline.v1.schema.json` is valid JSON;
- `git diff --check` reports no whitespace errors; and
- no credential, recording, transcript database, or model artifact is present in
  the source tree.

## 4. Building a wheel

Create a clean build environment:

```sh
python3 -m venv .build-venv
source .build-venv/bin/activate
python -m pip install --upgrade pip build
python -m build
```

Expected outputs:

```text
dist/
├── relayai_core-<version>-py3-none-any.whl
└── relayai_core-<version>.tar.gz
```

The exact normalized filenames are generated from the package metadata in
`pyproject.toml`.

### Clean-room artifact test

Test the wheel in a second environment rather than reusing the build environment:

```sh
python3 -m venv .verify-venv
source .verify-venv/bin/activate
python -m pip install dist/relayai_core-*.whl
python -c "import relayai_core; print(relayai_core.__doc__)"
```

Run repository tests against the installed artifact without adding `src` to
`PYTHONPATH`:

```sh
python -m unittest discover -s tests -v
```

## 5. Versioning and release artifacts

RelayAI uses semantic versions for the Python package:

- **Patch** — compatible fixes with no public contract changes.
- **Minor** — backward-compatible adapters, fields, or behavior.
- **Major** — incompatible Python API or pipeline-schema changes.

Before cutting a release:

1. Update `project.version` in `pyproject.toml`.
2. Update documentation and example pipelines.
3. Add a migration before increasing the pipeline schema version.
4. Run the full verification checklist.
5. Build wheel and source distribution from a clean checkout.
6. Install and test the wheel in a clean environment.
7. Generate hashes for published artifacts.
8. Tag the exact tested commit.

Example artifact hashing command:

```sh
shasum -a 256 dist/*
```

Do not publish from a working tree containing uncommitted source changes.

## 6. Installing a released package

Install a specific wheel by explicit path:

```sh
python -m pip install ./relayai_core-0.4.1-py3-none-any.whl
```

For a private package index, pin the exact version:

```sh
python -m pip install "relayai-core==0.4.1"
```

The host application is responsible for:

- registering concrete adapters;
- selecting a writable SQLite location;
- resolving `credential_id` values outside the pipeline document;
- controlling retention of transcript-bearing receipts; and
- exposing preview and approval UI before dispatching protected destinations.

### CLI smoke test

```sh
relayai --version
relayai pipeline validate examples/private-dictation.pipeline.json
relayai database --database /tmp/relayai-smoke.sqlite3 init
relayai database --database /tmp/relayai-smoke.sqlite3 import \
  examples/private-dictation.pipeline.json
relayai database --database /tmp/relayai-smoke.sqlite3 list
```

Local execution additionally requires an independently installed `whisper-cli`
binary and GGML model. RelayAI does not download either during package
installation. See [`docs/LOCAL_EXECUTION.md`](docs/LOCAL_EXECUTION.md) for the
explicit executable/model allowlist and end-to-end smoke command.

## 7. Runtime configuration

### Pipeline definitions

Load pipeline files only through `relayai_core.load_pipeline`. Do not deserialize
directly into dataclasses or bypass schema-version checks.

Production pipeline files should be:

- read from an application-controlled directory;
- writable only by the current user or administrator;
- backed up before migration;
- free of plaintext credentials; and
- validated before replacing an active definition.

### SQLite

Call `SQLiteStore.initialize()` before the first read or write. The store creates
its schema and enables write-ahead logging.

Recommended future macOS location:

```text
~/Library/Application Support/<final-bundle-id>/relayai.sqlite3
```

The final bundle ID has not been selected. Do not hardcode the working product
name into migrations or public filesystem contracts yet.

Back up the database using SQLite-aware tooling or while the application is
stopped. Copying only the main database file while WAL writes are active can
produce an incomplete backup.

### Credentials

The current core stores only opaque credential references. A production host must
resolve them from an approved secret store. The macOS desktop target will use the
Keychain.

OpenAI-compatible adapters accept an injected `CredentialResolver`. Their
endpoint URLs, exposure classification, and prompt catalogs are trusted host
configuration rather than pipeline-controlled values. See
[`docs/PROVIDERS.md`](docs/PROVIDERS.md).

Never place secrets in:

- pipeline `settings`;
- example files;
- SQLite pipeline JSON;
- logs or execution warnings;
- command-line arguments; or
- repository environment files.

## 8. Security gates

A production host must preserve the following invariants:

- Run engine preflight before giving audio or text to any adapter.
- Do not allow imported pipelines to register adapters.
- Treat registry exposure/effect metadata as trusted application code.
- Show prepared text before approving network or executable destinations.
- Approve destinations by stable instance ID, not adapter type.
- Configure webhook URLs outside transcript-controlled data.
- Configure scripts as fixed argument vectors and never invoke a shell.
- Pass transcript text through standard input.
- Restrict file destinations to explicit roots.
- Keep raw transcription available when refinement fails.

Disabling confirmation policy for network or executable effects should require an
explicit advanced setting in the future desktop UI and should be visible in the
pipeline summary.

## 9. Observability and health

The current core emits structured data through `PipelineRun` rather than a global
logger. A host should record or aggregate:

- run status;
- stage timings;
- provider identifiers;
- exposure events;
- refinement fallback count;
- destination status and effect;
- policy denials; and
- destination failure count.

Do not emit audio, raw transcript text, refined text, credentials, or webhook
payloads to logs by default.

Recommended initial operational gates:

- no policy-bypass test failures;
- no secret-bearing example or exported pipeline;
- no unapproved network/execute destination invocation;
- stable schema round trips; and
- successful clean-environment package installation.

### Local API deployment

Generate a new token for each deployment environment:

```sh
export RELAYAI_API_TOKEN="$(openssl rand -hex 32)"
relayai serve --database /absolute/path/to/relayai.sqlite3 --port 8765
```

Operational requirements:

- keep the token out of command arguments, pipeline files, logs, and shell
  history;
- restrict access to the environment of the RelayAI process;
- use a database path writable only by the intended local user;
- supervise the process with the operating system's user-level service manager
  if persistent execution is required;
- probe `GET /health` for process health;
- send the bearer token on every `/v1/*` request; and
- rotate the token when local access may have been exposed.

The V1 API is intentionally read-only. Do not place a reverse proxy in front of
it or expose it through port forwarding. See [`docs/LOCAL_API.md`](docs/LOCAL_API.md).

Latency and reliability SLOs must be established after real audio and provider
adapters exist; numeric production targets would be speculative today.

## 10. Rollback

### Python package

Keep at least one previously verified wheel. Roll back by installing the last
known-good version explicitly:

```sh
python -m pip install --force-reinstall ./relayai_core-<previous-version>-py3-none-any.whl
```

Before rolling back across a schema version:

1. Stop the host process.
2. Back up the SQLite database and pipeline directory.
3. Confirm the older release can read the active pipeline schema.
4. Restore pre-migration pipeline files if backward reading is unsupported.
5. Install the older package and run a read-only validation before dispatching.

Never downgrade a persisted schema by editing its version number manually.

### Failed destination rollout

Remove or disable the destination adapter registration, restore the previous
pipeline definition, and preserve failed receipts for diagnosis. Do not delete raw
transcripts automatically as part of operational rollback unless the retention
policy requires deletion.

## 11. Planned macOS desktop deployment

This section defines the intended release boundary and is not yet executable.

The desktop distribution will include:

- signed and notarized Tauri application;
- Rust platform adapters for audio, hotkeys, permissions, insertion, clipboard,
  keychain, and notifications;
- React configuration/history/approval UI;
- bundled Python core sidecar or an equivalent packaged core runtime;
- bundled or first-run-installed local STT engine and model manifest; and
- database/schema migrations with backup and rollback handling.

The desktop release pipeline must eventually perform:

1. TypeScript, Rust, and Python tests.
2. Pipeline-schema compatibility tests.
3. Release builds on a pinned macOS runner.
4. Code signing with protected CI credentials.
5. Apple notarization and stapling.
6. Installation and first-run permission tests on a clean macOS account.
7. Local-only network-isolation tests.
8. Update and rollback tests from the previous stable release.
9. Publication of checksums and release notes.

Do not advertise or distribute a desktop build until microphone, Accessibility,
Input Monitoring, and keychain permission failures are recoverable in product UI.

## 12. CI recommendation

The first CI workflow should run on every pull request and protected branch:

```sh
/usr/bin/env PYTHONPATH=src python3.11 -m unittest discover -s tests -v
python3 -m json.tool schemas/pipeline.v1.schema.json >/dev/null
git diff --check
```

API integration tests bind an ephemeral loopback port. CI sandboxes must permit
local socket binding.

A release workflow should be added only after the repository has a chosen package
registry, protected release environment, changelog policy, and maintainer approval
process.

## 13. Release checklist

- [ ] Version and schema compatibility reviewed
- [ ] Unit and safety tests pass
- [ ] Example pipelines validate
- [ ] Public documentation matches actual behavior
- [ ] No credentials, recordings, transcripts, or databases included
- [ ] Wheel and source distribution built from a clean commit
- [ ] Clean-environment installation succeeds
- [ ] Artifact hashes recorded
- [ ] Upgrade and rollback paths tested
- [ ] Release tag points to the tested commit

## 14. Troubleshooting

### `ModuleNotFoundError: relayai_core`

Install the package with `python -m pip install -e .` or run source tests with
`PYTHONPATH=src`.

### Pipeline import rejects a credential field

Move the credential to the host secret store and replace it with a
`credential_id`. Import rejection is intentional and must not be bypassed.

### Local-only pipeline rejects an adapter

The registered adapter declares network exposure. Select a local adapter or
disable `local_only` only after reviewing the data exposure.

### Destination stays in `awaiting_confirmation`

Display the prepared output to the user and call `dispatch` with that
destination's instance ID in `approved_destination_ids`.

### SQLite database is locked

Ensure each host process uses the store as intended and that no external tool is
holding a write transaction. Avoid placing the active database on a network
filesystem.
