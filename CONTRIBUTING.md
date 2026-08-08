# Contributing to RelayAI

Thank you for helping build RelayAI. Contributions of code, tests,
documentation, pipeline examples, design feedback, and reproducible bug reports
are welcome.

RelayAI is still pre-alpha. The fastest way to get a contribution merged is to
keep it focused, preserve the product's safety properties, and discuss large
contract changes before implementation.

## Ways to contribute

Good first contributions include:

- clarifying documentation or improving examples;
- adding tests for an existing behavior or failure mode;
- improving error messages and validation;
- adding fixture-based compatibility tests for the pipeline schema;
- benchmarking startup, memory use, and pipeline latency; and
- implementing a narrowly scoped item from an accepted issue.

Provider adapters, platform integrations, schema changes, new network behavior,
and executable destinations need design discussion because they affect privacy,
security, or compatibility. Open a feature proposal before starting those
changes.

## Before you start

1. Read [CONTEXT.md](CONTEXT.md) for the product scope and non-goals.
2. Search [existing issues](https://github.com/subharthi99/RelayAI/issues) and
   pull requests to avoid duplicate work.
3. Open a feature proposal for a substantial change and wait for agreement on
   its scope.
4. Never include real recordings, transcripts, credentials, tokens, or private
   pipeline data in an issue, test, commit, or pull request.

For security vulnerabilities, do not open an issue. Follow
[SECURITY.md](SECURITY.md).

## Development setup

RelayAI requires Python 3.11 or newer and has no third-party runtime
dependencies.

```sh
git clone https://github.com/subharthi99/RelayAI.git
cd RelayAI
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests -v
```

Create a branch from the latest default branch:

```sh
git switch -c type/short-description
```

Suggested prefixes are `fix/`, `feature/`, `docs/`, and `test/`.

## Architecture rules

Every contribution must preserve these invariants:

- Keep speech, refinement, context, and destination adapter contracts separate.
- Enforce privacy policies in engine code, never only in prompts or UI.
- Reject cloud providers and network destinations before executing a
  `local_only` pipeline.
- Treat exposure and destination effects as trusted adapter metadata, not
  pipeline-provided claims.
- Preserve the raw transcript when optional refinement fails.
- Require allowlisting and the configured confirmation gate for scripts,
  webhooks, and MCP tools.
- Keep credentials out of pipeline files, logs, fixtures, and SQLite records.
- Version public pipeline contracts and provide a migration path for breaking
  schema changes.

## Making a change

Keep each pull request focused on one behavior. Add or update tests alongside the
implementation and update user-facing documentation when behavior changes.

Tests use the standard-library `unittest` framework:

```sh
python -m unittest discover -s tests -v
git diff --check
```

Validate the public schema and example pipelines:

```sh
python -m json.tool schemas/pipeline.v1.schema.json >/dev/null
relayai pipeline validate examples/private-dictation.pipeline.json
relayai pipeline validate examples/polished-communication.pipeline.json
relayai pipeline validate examples/approved-automation.pipeline.json
relayai pipeline validate examples/local-audio.pipeline.json
```

Safety-sensitive changes need regression tests. This includes policy preflight,
secret rejection, path containment, command allowlisting, network access,
confirmation behavior, authentication, and transcript preservation during
failure.

## Commit and pull-request guidance

Write concise, imperative commit subjects, for example:

```text
Reject network destinations in local-only pipelines
```

Before opening a pull request:

- rebase or merge the latest default branch as appropriate;
- run the complete test and validation commands above;
- remove generated files and local data;
- update `CHANGELOG.md` under an `Unreleased` heading for user-visible changes;
- explain the motivation and security/privacy impact; and
- link the issue the pull request resolves.

Draft pull requests are welcome for early feedback. A pull request is ready for
review when CI passes, its scope is stable, and the template is complete.

## Review and compatibility

Maintainers may ask for changes to keep public contracts small and stable.
Approval is required before merging. Public schema or API changes must document
compatibility behavior; breaking changes are reserved for an appropriate major
version or schema version.

Contributions are accepted under the repository's
[Apache License 2.0](LICENSE). By submitting a contribution, you agree that it
may be distributed under that license.
