# Local audio execution

RelayAI 0.4.0 can execute a complete local pipeline from an existing audio file
using `whisper.cpp`. It performs policy preflight, transcription, local delivery,
and SQLite receipt persistence without requiring the desktop client.

## Supported boundary

The local runner currently registers:

- `local.whisper_cpp` for speech transcription;
- `builtin.result` for returning text in the structured run receipt; and
- `builtin.file` only when one or more roots are explicitly allowed on the
  command line.

Context, refinement, scripts, webhooks, focused-field insertion, and clipboard
delivery are not registered by this command yet. A pipeline referencing an
unregistered adapter fails during preflight before audio is processed.

## Install whisper.cpp

Build `whisper-cli` using the official
[`whisper.cpp` instructions](https://github.com/ggml-org/whisper.cpp):

```sh
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build
cmake --build build -j --config Release
sh ./models/download-ggml-model.sh small
```

The resulting executable is normally `build/bin/whisper-cli`, and the model is
normally `models/ggml-small.bin`. RelayAI does not download or execute installers
automatically.

Upstream `whisper-cli` accepts FLAC, MP3, OGG, and WAV input. Its standard WAV
path expects 16-bit PCM; convert other audio when necessary according to the
upstream documentation.

## Run a pipeline

The included `local-audio` example uses `builtin.result`, so its final text is
returned in the JSON receipt:

```sh
relayai run \
  --pipeline examples/local-audio.pipeline.json \
  --audio /absolute/path/to/audio.wav \
  --database relayai.sqlite3 \
  --whisper-cli /absolute/path/to/whisper-cli \
  --model small=/absolute/path/to/ggml-small.bin
```

`--model NAME=PATH` creates a trusted model allowlist. The pipeline can select
`small`; it cannot provide or alter the filesystem path.

To verify the model on every run, add:

```sh
--model-sha256 small=<64-character-sha256>
```

Generate the digest on macOS with:

```sh
shasum -a 256 /absolute/path/to/ggml-small.bin
```

## Preview without delivery

Add `--prepare-only` to stop after transcription and optional refinement. The
stored receipt remains in `ready` status and has no destination receipts.

## File delivery

A pipeline may use `builtin.file` only below a root explicitly supplied to the
runner:

```sh
relayai run \
  ... \
  --allow-file-root /absolute/path/to/approved-output
```

The file destination resolves the final target and rejects path traversal
outside the allowed root.

## Runtime guarantees

- The executable and model mapping come from trusted CLI configuration, not the
  pipeline document.
- `whisper-cli` is started with an argument vector and never through a shell.
- Arbitrary extra whisper arguments are rejected.
- Input and JSON output use a private temporary directory removed after the run.
- Standard output is discarded and standard error is captured only for bounded
  diagnostics.
- Timeouts and task cancellation terminate the child process.
- Audio is limited to 512 MiB and JSON output to 16 MiB by default.
- Successful prepared or dispatched runs are persisted to the explicit SQLite
  database.

The JSON printed by `relayai run` is the complete `PipelineRun`; it includes raw
and final transcript text and must be handled as sensitive local data.
