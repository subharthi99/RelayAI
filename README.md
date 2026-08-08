# RelayAI

RelayAI is an open-source, policy-aware voice router for developers, technical
power users, and privacy-conscious professionals.

> Speak once, then route the result through a configurable local or cloud
> pipeline into text, prompts, scripts, webhooks, or AI tools.

RelayAI treats polished dictation as a baseline. Its primary design goal is to
make every processing stage visible, configurable, and enforceable: users can
choose where speech is processed, understand which data leaves the device, and
approve side effects before they occur.

> [!IMPORTANT]
> RelayAI is at an early foundation stage. The policy and pipeline core is
> executable and tested. Version 0.4.0 adds complete audio-file execution through
> an allowlisted local `whisper.cpp` process, alongside the CLI, authenticated
> loopback read API, and OpenAI-compatible providers. The macOS desktop shell,
> live microphone capture, bundled model distribution, keychain integration, and
> focused-field insertion are not implemented yet.

## Why RelayAI?

Most voice products expose a recording button and an opaque AI mode. RelayAI is
designed around explicit pipelines:

```text
capture -> transcription -> context -> optional refinement -> destinations
                                      |                    |
                                      +-- policy checks ----+
```

Each pipeline declares:

- how recording starts;
- which speech provider receives the audio;
- which contextual sources may be read;
- whether and how the transcript is refined;
- whether all processing must remain local;
- where the resulting text may be delivered; and
- which destinations require explicit approval.

The core records these decisions in an execution receipt rather than hiding them
inside UI state or model prompts.

## Version 1 product target

The first usable desktop version should let a technical user configure three
workflows without modifying application code:

1. **Private dictation** — local STT with text inserted into the focused field.
2. **Polished communication** — local or remote transcription with an explicitly
   configured refinement provider.
3. **Approved automation** — previewed text delivered to an allowlisted webhook
   or local script only after confirmation.

V1 is macOS-first. The pipeline core remains platform-neutral so Windows and
Linux adapters can be added later.

Meeting recording, diarization, wake words, autonomous agents, cloud sync, team
administration, mobile keyboards, and a plugin marketplace are deliberately
outside the first release.

## Current implementation

The repository currently provides the executable Python core:

- versioned `PipelineDefinition` models;
- separate `SpeechProvider`, `RefinementProvider`, `ContextProvider`, and
  `Destination` contracts;
- adapter registries whose trusted metadata declares local/network exposure and
  destination effects;
- preflight enforcement of `local_only` pipelines;
- two-phase `prepare` and `dispatch` execution;
- confirmation gates for network and executable destinations;
- raw-transcript fallback when refinement fails;
- execution receipts containing timings, providers, exposure events, warnings,
  artifacts, and destination results;
- strict JSON import/export with secret-field detection;
- an open JSON Schema for pipeline files;
- allowlisted file, webhook, and shell-free script destinations;
- SQLite persistence for pipeline definitions and execution receipts;
- a `relayai` CLI for validation, inspection, import/export, and history
  retention;
- an authenticated, read-only API that can bind only to `127.0.0.1`;
- OpenAI-compatible speech and refinement reference adapters for allowlisted
  local or cloud endpoints; and
- an injectable credential resolver contract for future OS keychain integration;
- an allowlisted `whisper.cpp` speech provider with checksum, timeout,
  cancellation, and bounded-output enforcement; and
- a `relayai run` path that executes audio files and persists run receipts.

## Repository layout

```text
RelayAI/
├── CONTEXT.md                  Product scope, invariants, and roadmap
├── CHANGELOG.md                Versioned release notes
├── DEPLOYMENT.md               Build, release, installation, and rollback guide
├── LICENSE                     Apache License 2.0
├── README.md                   Project overview and contributor entry point
├── examples/                   Example V1 pipeline definitions
├── schemas/
│   └── pipeline.v1.schema.json Public pipeline schema
├── src/relayai_core/
│   ├── adapters.py             Adapter protocols
│   ├── api.py                  Authenticated loopback read API
│   ├── cli.py                  Command-line control plane
│   ├── credentials.py          External credential resolver contract
│   ├── destinations.py         Safe reference destinations
│   ├── engine.py               Prepare/dispatch orchestration
│   ├── models.py               Public domain models and receipts
│   ├── openai_compatible.py    Reference speech/refinement providers
│   ├── policy.py               Enforceable policy rules
│   ├── registry.py             Trusted adapter registration
│   ├── serialization.py        Import/export and validation
│   ├── storage.py              SQLite persistence
│   └── whisper_cpp.py          Safe local whisper.cpp process adapter
└── tests/                      Core behavior and safety tests
```

## Requirements

- Python 3.11 or newer
- Git
- No required runtime dependencies outside the Python standard library

The future desktop application will additionally require the Rust and Node.js
toolchains used by Tauri. Those requirements do not apply to the current core.

## Quick start

Clone the repository and create an isolated environment:

```sh
git clone <repository-url>
cd RelayAI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the complete test suite:

```sh
python -m unittest discover -s tests -v
```

Tests can also run directly from a source checkout without installation:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Confirm the installed CLI:

```sh
relayai --version
relayai pipeline validate examples/private-dictation.pipeline.json
relayai pipeline inspect examples/approved-automation.pipeline.json
```

Execute a local audio file after installing `whisper.cpp` and a model:

```sh
relayai run \
  --pipeline examples/local-audio.pipeline.json \
  --audio /path/to/audio.wav \
  --database relayai.sqlite3 \
  --whisper-cli /path/to/whisper-cli \
  --model small=/path/to/ggml-small.bin
```

See [`docs/LOCAL_EXECUTION.md`](docs/LOCAL_EXECUTION.md) for checksum
verification, preview-only execution, and file-delivery controls.

## Command-line interface

The CLI makes pipeline management deployable before the desktop UI exists.

Initialize a database and import the example pipelines:

```sh
relayai database --database relayai.sqlite3 init
relayai database --database relayai.sqlite3 import \
  examples/private-dictation.pipeline.json
relayai database --database relayai.sqlite3 import \
  examples/polished-communication.pipeline.json
relayai database --database relayai.sqlite3 list
```

Export a stored definition:

```sh
relayai database --database relayai.sqlite3 export private-dictation \
  --output private-dictation.exported.json
```

Inspect receipt history:

```sh
relayai history --database relayai.sqlite3 list --limit 20
relayai history --database relayai.sqlite3 show <run-id>
```

History deletion is deliberately filtered and confirmation-gated:

```sh
relayai history --database relayai.sqlite3 purge \
  --pipeline-id private-dictation --yes
```

`purge` rejects an unfiltered deletion and refuses to run without `--yes`.

## Authenticated local API

Start the read-only API with a random bearer token of at least 32 characters:

```sh
export RELAYAI_API_TOKEN="$(openssl rand -hex 32)"
relayai serve --database relayai.sqlite3 --port 8765
```

The server is hard-limited to `127.0.0.1`; it rejects wildcard and external
bindings. `/health` is public and contains no stored state. Every `/v1/*` route
requires:

```text
Authorization: Bearer <token>
```

Available routes:

- `GET /health`
- `GET /v1/pipelines`
- `GET /v1/pipelines/{pipeline_id}`
- `GET /v1/runs?pipeline_id={id}&limit={1..1000}`
- `GET /v1/runs/{run_id}`

Run lists are redacted summaries. A specific run endpoint returns the complete
receipt and may therefore contain transcript text. See
[`docs/LOCAL_API.md`](docs/LOCAL_API.md) for the complete contract and security
guidance.

## Pipeline example

```json
{
  "schema_version": 1,
  "id": "private-dictation",
  "name": "Private dictation",
  "transcription": {
    "adapter_id": "local.whisper_cpp",
    "settings": { "model": "small" }
  },
  "refinement": { "enabled": false },
  "policy": {
    "local_only": true,
    "confirm_network_destinations": true,
    "confirm_executable_destinations": true
  },
  "destinations": [
    {
      "id": "cursor",
      "adapter_id": "platform.focused_field",
      "settings": {}
    }
  ]
}
```

Four complete definitions are available in [`examples/`](examples/):

- [`private-dictation.pipeline.json`](examples/private-dictation.pipeline.json)
- [`polished-communication.pipeline.json`](examples/polished-communication.pipeline.json)
- [`approved-automation.pipeline.json`](examples/approved-automation.pipeline.json)
- [`local-audio.pipeline.json`](examples/local-audio.pipeline.json)

These examples are product contracts. Some referenced platform and provider
adapters are intentionally not registered until the desktop implementation is
added.

## Using the core

Adapters are registered by capability. An imported pipeline can reference only
an adapter present in the matching registry.

```python
from relayai_core import PipelineEngine, load_pipeline
from relayai_core.registry import AdapterRegistry

registry = AdapterRegistry()

# Application composition registers concrete implementations:
# registry.speech.add(local_whisper)
# registry.refinement.add(openai_compatible_refiner)
# registry.context.add(active_application_context)
# registry.destinations.add(focused_field_destination)

engine = PipelineEngine(registry)
pipeline = load_pipeline(open("pipeline.json", encoding="utf-8").read())
```

Execution is deliberately split into two phases:

```python
prepared = await engine.prepare(pipeline, audio_artifact)

# Show prepared.run.final_text and pending destination effects to the user.

completed = await engine.dispatch(
    prepared,
    approved_destination_ids={"issue-tracker"},
)
```

`prepare` performs policy preflight before any adapter runs, then transcribes,
collects allowed context, and attempts refinement. `dispatch` delivers the
prepared text. Network and executable destinations remain in
`awaiting_confirmation` unless the caller supplies their stable destination IDs.

## Policy model

Policies are engine rules, not prompt instructions.

### Local-only enforcement

If `policy.local_only` is true, preflight rejects every registered adapter whose
trusted exposure is `network`. This includes speech, refinement, context, and
destination adapters. Rejection occurs before the speech provider receives
audio.

### Destination approval

Destinations declare one of four effects:

| Effect | Meaning | Default confirmation |
| --- | --- | --- |
| `passive` | Text insertion, clipboard, or equivalent delivery | No |
| `local_write` | Writes data to an allowlisted local path | No |
| `network` | Sends text to a configured remote endpoint | Yes |
| `execute` | Starts an allowlisted local executable | Yes |

Imported files cannot classify their own exposure or effect. Those declarations
come from registered application code so an untrusted pipeline cannot relabel a
network adapter as local.

### Secret handling

Pipeline files may contain opaque `credential_id` references but not credentials.
Import rejects fields such as API keys, passwords, access tokens, refresh tokens,
authorization values, and provider-specific secret names at any nesting level.

The desktop implementation will resolve credential IDs through the OS keychain.
The current core intentionally has no plaintext credential store.

### Safe automation

- Webhooks select an endpoint by preconfigured ID; transcript text cannot alter
  the URL.
- Scripts select an allowlisted command ID mapped to a fixed argument vector.
- Script execution never invokes a shell.
- Transcript text is passed through standard input rather than interpolated into
  a command.
- File destinations resolve the target and reject paths outside configured roots.

## Persistence

`SQLiteStore` persists pipeline JSON and run receipts in SQLite. It opens a
short-lived connection per operation and enables write-ahead logging during
initialization.

The embedding application chooses the database location. For the future macOS
desktop build, it should live under the application-support directory, not in the
repository or current working directory.

Run receipts may contain transcript text. Product UI must make history retention
clear and provide deletion controls before the desktop application is released.

## Development checks

Run before opening a change:

```sh
python -m unittest discover -s tests -v
git diff --check
```

Safety-sensitive changes should include a regression test. In particular, add
tests for policy boundaries, secret rejection, path containment, command
allowlisting, confirmation behavior, and transcript preservation during failure.

## Architecture and product documents

- [`CONTEXT.md`](CONTEXT.md) — authoritative product scope and engineering rules
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — current package deployment and future desktop
  release boundary
- [`docs/LOCAL_API.md`](docs/LOCAL_API.md) — authenticated loopback API contract
- [`docs/LOCAL_EXECUTION.md`](docs/LOCAL_EXECUTION.md) — local `whisper.cpp`
  execution guide
- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — OpenAI-compatible adapter setup and
  security contract
- [`docs/RelayAI-System-Design-v1.docx`](docs/RelayAI-System-Design-v1.docx) —
  formatted V1 system design
- [`schemas/pipeline.v1.schema.json`](schemas/pipeline.v1.schema.json) — public
  interchange contract

## Roadmap

### Current foundation

- Pipeline contracts and validation
- Policy preflight and confirmation gates
- Execution receipts and SQLite persistence
- Safe reference destinations
- CLI and authenticated localhost read API
- OpenAI-compatible cloud speech and local/cloud refinement adapters
- Local audio-file execution with `whisper.cpp` and persisted receipts

### Next implementation slice

- Tauri macOS shell and React UI
- Native microphone capture and global hotkeys
- OS keychain credential resolution
- Focused-field and clipboard platform destinations
- Typed local IPC between Tauri and Python

### V1.5

- CLI and authenticated localhost read API — implemented in 0.2.0
- MCP server for agent-requested voice input
- Approved MCP tool destinations
- Secret-free pipeline import/export UI
- Community pipeline templates with declared permissions

See [`CONTEXT.md`](CONTEXT.md) for explicit non-goals and later-stage features.

## Contributing

Contributions are welcome. You can help with the Python core, adapter contracts,
security tests, documentation, example pipelines, or the future macOS client.

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), then browse
[open issues](https://github.com/subharthi99/RelayAI/issues). For a substantial
feature or contract change, open a proposal issue before investing in an
implementation. Small fixes and documentation improvements can go directly to a
pull request.

All contributors must follow the [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
Please report vulnerabilities privately using the process in
[`SECURITY.md`](SECURITY.md), not in a public issue.

## License

Copyright 2026 Subharthi Saha.

Licensed under the [Apache License 2.0](LICENSE).
