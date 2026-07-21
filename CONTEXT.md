# RelayAI

> RelayAI is an internal working name pending branding and trademark review.

## Product

RelayAI is an open-source, policy-aware voice router for developers, technical
power users, and privacy-conscious professionals.

> Speak once, then route the result through a configurable local or cloud
> pipeline into text, prompts, scripts, webhooks, or AI tools.

RelayAI is not defined as an alternative to one proprietary dictation product.
Polished dictation is the baseline experience; the product differentiates through
transparent pipelines, enforceable privacy rules, inspectable execution, safe
automation, and open integration contracts.

## Product principles

- Local-first: a useful private pipeline must work without an account or network.
- Policy-enforced: privacy and action permissions are engine rules, not prompts.
- Inspectable: users can see raw input, transformations, providers, exposure,
  timing, cost when known, and destination results.
- Composable: capture, transcription, refinement, context, and destinations are
  independent adapters with distinct contracts.
- Safe by default: a transcript is data, never an executable command by default.
- Recoverable: raw transcription remains available if refinement or delivery fails.
- Portable core: macOS ships first, while platform-specific behavior stays behind
  adapters so Windows and Linux can follow.
- UI contains presentation and interaction logic only; policy and orchestration
  live in the core.

## V1: Voice Router

V1 proves that one user can create three pipelines without modifying code:

1. Private dictation using only local processing.
2. Polished communication using an explicitly permitted refinement provider.
3. An approved automation delivering text to a webhook or allowlisted script.

V1 includes:

- macOS desktop application with global push-to-talk and toggle hotkeys.
- Recording overlay, cancel action, microphone selection, and audio feedback.
- One bundled local STT engine and one OpenAI-compatible remote STT adapter.
- One OpenAI-compatible refinement adapter usable with local endpoints such as
  Ollama or explicitly configured cloud endpoints.
- Named, versioned pipelines covering capture, transcription, refinement,
  context, policy, and destinations.
- Manual pipeline selection, dedicated hotkeys, and application-based selection.
- Focused-field insertion, clipboard, file, HTTP webhook, and allowlisted local
  script destinations.
- Preview or explicit confirmation before network destinations and executable
  actions. Arbitrary transcript text is never interpreted as shell code.
- Separate raw and refined text with automatic raw-transcript fallback.
- Execution receipts and local history stored in SQLite.
- Credentials stored only in the OS keychain and referenced by opaque IDs.

## Explicitly outside V1

- Meeting/system-audio recording, diarization, and meeting-note chat.
- Wake words and always-listening capture.
- Complete hands-free desktop control.
- Autonomous multi-step agents.
- Cloud sync, teams, mobile keyboards, and a plugin marketplace.
- Supporting every possible STT or LLM vendor directly.

These are product extensions, not prerequisites for validating voice routing.

## Pipeline model

The public configuration unit is a versioned `PipelineDefinition`:

```text
capture -> transcription -> context -> optional refinement -> destinations
                                      |                    |
                                      +-- policy checks ----+
```

Each pipeline contains:

- `schema_version`: compatibility version for import and migration.
- `id`, `name`, and optional description.
- `capture`: activation behavior and audio source configuration.
- `transcription`: speech adapter ID and non-secret settings.
- `context`: zero or more context adapter references.
- `refinement`: optional refinement adapter, prompt/template reference, and
  non-secret settings.
- `policy`: local-only and confirmation requirements.
- `destinations`: one or more destination adapter references.

Credentials must never appear in pipeline files. Provider settings reference a
keychain entry by credential ID. Imports containing credential-like fields are
rejected rather than silently retained.

## Core contracts

Do not collapse providers behind one generic interface. The core exposes:

- `SpeechProvider`: audio to raw transcription.
- `RefinementProvider`: transcript plus approved context to refined text.
- `ContextProvider`: active-application or user-approved contextual data.
- `Destination`: final text to a declared output or action.

Every adapter declares its exposure (`local` or `network`) and destinations also
declare their effect (`passive`, `local_write`, `network`, or `execute`). The
engine trusts adapter declarations from the registry, never classifications from
imported pipeline data.

Execution is two-phase:

1. `prepare` validates policy, transcribes, gathers approved context, attempts
   refinement, and produces a preview plus pending destinations.
2. `dispatch` delivers to passive destinations immediately and requires explicit
   approval for network or executable destinations according to policy.

A `PipelineRun` records artifacts, provider IDs, exposure events, timing, status,
warnings, and per-destination receipts. Refinement failure adds a warning and uses
the raw transcript. Destination failures never erase transcription artifacts.

## Policy invariants

- `local_only` rejects every network speech, refinement, context, or destination
  adapter before audio or text is sent anywhere.
- Network and executable destinations require confirmation by default.
- Script destinations execute only a preconfigured command ID mapped to a fixed
  argument vector. They never use a shell and receive text through standard input.
- File destinations resolve their target under an allowlisted root.
- Webhook destinations use configured endpoints; transcript content cannot select
  or alter the URL.
- Imported pipelines reject unknown schema versions, embedded credentials,
  duplicate destination IDs, and unsafe or malformed configuration.
- Exported pipelines contain no secrets.

## Architecture

### Desktop shell

- Tauri, Rust, React, and TypeScript.
- Rust adapters own audio capture, hotkeys, permissions, focused-field insertion,
  clipboard behavior, keychain access, and native notifications.
- Platform-specific behavior is accessed through typed commands and events.

### Core

- Python package for pipeline orchestration, provider adapters, policy evaluation,
  migration, and execution receipts.
- Typed local IPC boundary between Tauri and Python.
- Async I/O throughout provider and destination execution.

### Persistence

- SQLite for pipelines, history, execution receipts, dictionaries, and settings.
- JSON for portable pipeline import/export.
- OS keychain for secrets; SQLite and JSON store credential references only.

## V1.5: Open integration layer

- Publish the pipeline JSON schema and adapter contracts.
- Add a CLI and authenticated localhost API to list pipelines, prepare a run,
  approve destinations, dispatch, and retrieve receipts.
- Add an MCP server through which an agent can request and receive a voice response.
- Add MCP client destinations limited to explicitly approved tools.
- Add secret-free pipeline import/export and community templates with declared
  permissions.

## Later roadmap

1. Windows platform adapters, then Linux adapters.
2. Learned corrections, app-context extraction, translation, selected-text
   editing, personal style, and shared dictionaries.
3. Meeting capture only after routing reliability and user demand are demonstrated.
4. Sync, teams, agent workflows, and a marketplace only after the local product
   and extension model are stable.

## Engineering rules

- Never hardcode prompts, provider endpoints, or credentials.
- Ship a small set of well-tested reference adapters; extensibility matters more
  than a long provider checklist.
- Use dependency injection and avoid singleton application state.
- Prefer explicit typed values over unstructured dictionaries at core boundaries.
- Keep startup fast and load models lazily.
- Preserve unrelated clipboard content and restore it after insertion when enabled.
- Log metadata and policy decisions, never audio, transcript text, or secrets by
  default.
- Schema changes require a migration and compatibility test.

## Acceptance criteria

- Hotkey capture begins immediately and preserves the intended focused destination.
- A local-only pipeline produces no external network activity.
- Every cloud stage clearly identifies what leaves the device.
- Refinement failure exposes and can deliver the raw transcript.
- Application switching cannot leak context between pipeline runs.
- Clipboard restoration works after successful and failed insertion.
- Network, script, and future MCP actions cannot run without required approval.
- Imports reject unknown versions, unsafe defaults, and embedded credentials.
- Provider contracts pass the same fixture suite without the desktop UI.
- Permission denial, missing microphone, model failure, timeout, malformed provider
  output, and destination failure produce recoverable errors.
- Benchmarks track time to recording readiness, time to first transcript,
  end-to-end latency, memory use, and startup time.

## Success metrics

Primary product validation:

- A technical user creates and uses private dictation, polished communication, and
  approved automation pipelines without changing code.

Operational metrics:

- Recording-ready latency.
- Time to first transcript and end-to-end completion latency.
- Percentage of runs delivered without manual correction.
- Refinement fallback rate and destination failure rate.
- Percentage of usage completed entirely locally.
- Number of active user-created pipelines.

The long-term goal is not merely the fastest transcription. It is the most trusted
and adaptable path from human speech to useful, observable action.
