# Test results

This page records reproducible verification evidence for the current RelayAI
core. GitHub Actions remains the source of truth for a commit; local results are
supporting evidence rather than a substitute for CI.

## Latest recorded verification

Recorded on **2026-10-24** for RelayAI `0.5.0`.

| Check | Environment | Result |
| --- | --- | --- |
| Complete unit and integration suite | Python 3.11, macOS | 88 passed |
| Complete suite with resource warnings treated as errors | Python 3.13, macOS | 88 passed |
| Pipeline schema and all example JSON files | Python 3.11 | Passed |
| GitHub workflow YAML parsing | Ruby YAML parser | Passed |
| Wheel build and metadata inspection | Python 3.11 | Passed |
| Real whisper.cpp v1.8.3 + verified tiny.en + JFK audio | CPU, macOS Apple Silicon | Passed |

The suite covers policy denial before transcription, raw-transcript fallback,
destination approval, secret rejection, path containment, SQLite persistence,
authenticated loopback API behavior, OpenAI-compatible provider validation, and
`whisper.cpp` subprocess safety.

## Reproduce locally

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -W error::ResourceWarning -m unittest discover -s tests -v
sh scripts/terminal-demo.sh
git diff --check
```

Validate public contracts:

```sh
python -m json.tool schemas/pipeline.v1.schema.json >/dev/null
for pipeline in examples/*.pipeline.json; do
  relayai pipeline validate "$pipeline"
done
```

## Automated CI gates

The [CI workflow](../.github/workflows/ci.yml) runs on pushes to `main` and every
pull request. It must pass before a change is considered release-ready:

1. Run the suite on Python 3.11, 3.12, and 3.13 on Linux and macOS.
2. Promote `ResourceWarning` to an error.
3. Validate the schema and every example pipeline.
4. Check Python compilation and whitespace.
5. Build a wheel, install it into a clean virtual environment, and run the
   terminal demo against the installed artifact.

See the live [GitHub Actions history](https://github.com/subharthi99/RelayAI/actions/workflows/ci.yml)
for commit-specific results.

The [real-model workflow](../.github/workflows/whisper-integration.yml) runs on
relevant pull requests, weekly, and manually. It pins whisper.cpp commit
`2eeeba56e9edd762b4b38467bab96c2517163158` and tiny.en SHA-256
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
The local smoke run transcribed JFK audio in approximately 1.2 seconds. This is
one integration observation, not a broad accuracy or latency benchmark.

## Reporting a regression

Open a bug report with the failing Python version, operating system, exact
command, and sanitized output. Never attach real recordings, transcripts,
credentials, or production pipeline data. Report security-sensitive failures
through [SECURITY.md](../SECURITY.md).
