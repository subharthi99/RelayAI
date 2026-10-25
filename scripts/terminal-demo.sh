#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/relayai-demo.XXXXXX")
trap 'rm -rf "$demo_root"' EXIT HUP INT TERM

relayai_python=${RELAYAI_DEMO_PYTHON:-}
if [ -z "$relayai_python" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && \
      "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    then
      relayai_python=$candidate
      break
    fi
  done
fi
if [ -z "$relayai_python" ]; then
  echo "RelayAI requires Python 3.11 or newer" >&2
  exit 1
fi

if [ "${RELAYAI_DEMO_USE_INSTALLED:-0}" = "1" ]; then
  if ! command -v relayai >/dev/null 2>&1; then
    echo "relayai is not installed or not on PATH" >&2
    exit 1
  fi
  run_relayai() {
    relayai "$@"
  }
else
  run_relayai() {
    PYTHONPATH="$repository_root/src${PYTHONPATH:+:$PYTHONPATH}" \
      "$relayai_python" -m relayai_core "$@"
  }
fi

cat >"$demo_root/whisper-cli" <<'PY'
#!/usr/bin/env python3
import json
import pathlib
import sys

arguments = sys.argv[1:]
output = pathlib.Path(arguments[arguments.index("--output-file") + 1] + ".json")
output.write_text(
    json.dumps(
        {
            "result": {"language": "en"},
            "transcription": [
                {"text": " RelayAI routed this voice note locally."}
            ],
        }
    ),
    encoding="utf-8",
)
PY
chmod 700 "$demo_root/whisper-cli"

printf 'fixture-model' >"$demo_root/ggml-small.bin"
printf 'RIFFfixture-audio' >"$demo_root/demo.wav"

run_relayai run \
  --pipeline "$repository_root/examples/local-audio.pipeline.json" \
  --audio "$demo_root/demo.wav" \
  --database "$demo_root/relayai.sqlite3" \
  --whisper-cli "$demo_root/whisper-cli" \
  --model "small=$demo_root/ggml-small.bin" \
  >"$demo_root/receipt.json"

run_relayai history \
  --database "$demo_root/relayai.sqlite3" \
  list \
  --pipeline-id local-audio \
  >"$demo_root/history.json"

"$relayai_python" - "$demo_root/receipt.json" "$demo_root/history.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
history = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))

assert receipt["status"] == "succeeded"
assert receipt["final_text"] == "RelayAI routed this voice note locally."
assert receipt["exposure_events"] == [
    {
        "adapter_id": "local.whisper_cpp",
        "exposure": "local",
        "stage": "transcription",
    }
]
assert history and history[0]["id"] == receipt["id"]

print("RelayAI terminal demo")
print(f"  status:     {receipt['status']}")
print(f"  transcript: {receipt['final_text']}")
print("  exposure:   local")
print("  receipt:    persisted")
PY
