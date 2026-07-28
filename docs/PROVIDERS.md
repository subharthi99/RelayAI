# OpenAI-compatible provider adapters

RelayAI 0.3.0 includes reference adapters for OpenAI-compatible speech
transcription and chat-based text refinement. They use only the Python standard
library and are designed for embedding in a trusted host process.

These adapters do not make pipeline files trusted. The host application owns:

- adapter IDs and exposure classifications;
- the allowlist of endpoint IDs and base URLs;
- credential resolution;
- the allowlist of refinement prompt IDs;
- request timeouts and size limits; and
- registration in the capability-specific adapter registry.

Pipeline files can select only an endpoint, model, and prompt already made
available by the host.

## Security model

An adapter instance is either `local` or `network`; one instance cannot mix the
two classifications.

- Local adapters accept only `localhost`, `127.0.0.1`, or `::1` endpoints.
- Network adapters require HTTPS.
- URLs cannot contain credentials, queries, or fragments.
- HTTP redirects are not followed.
- Speech uploads default to a 25 MiB limit.
- Provider responses default to a 2 MiB limit.
- Unknown provider settings and malformed responses are rejected.
- Bearer credentials are resolved from opaque `credential_id` references and
  are never read from pipeline settings.
- Resolved credentials containing newline characters are rejected before an
  HTTP request is made.

A host should use a unique adapter ID for each trust boundary, such as
`cloud.team_speech` and `local.ollama_refinement`.

## Credential resolver

Implement the small `CredentialResolver` protocol using the platform secret
store:

```python
class KeychainCredentialResolver:
    def resolve(self, credential_id: str) -> str:
        # Retrieve the secret from the OS keychain.
        ...
```

`MappingCredentialResolver` is provided for tests and short-lived embedding
processes. Do not use it to persist production credentials.

## Cloud speech adapter

```python
from relayai_core import (
    Exposure,
    OpenAICompatibleSpeechProvider,
)

cloud_speech = OpenAICompatibleSpeechProvider(
    adapter_id="cloud.primary_speech",
    exposure=Exposure.NETWORK,
    endpoints={
        "primary": "https://speech-provider.example/v1",
    },
    credential_resolver=keychain_resolver,
)

registry.speech.add(cloud_speech)
```

The corresponding pipeline reference contains no URL or secret:

```json
{
  "adapter_id": "cloud.primary_speech",
  "credential_id": "speech-production",
  "settings": {
    "endpoint_id": "primary",
    "model": "whisper-1",
    "language": "en"
  }
}
```

Speech settings:

| Setting | Required | Constraint |
| --- | --- | --- |
| `endpoint_id` | Yes | Must be registered by the host |
| `model` | Yes | Non-empty string |
| `language` | No | Non-empty string |
| `temperature` | No | Number from 0 through 1 |

The adapter posts multipart audio to
`{base_url}/audio/transcriptions` and requests a JSON response.

## Local refinement through an OpenAI-compatible server

The application should load prompts from user or administrator configuration
and pass the resulting allowlist into the adapter:

```python
from relayai_core import (
    Exposure,
    OpenAICompatibleRefinementProvider,
)

local_refinement = OpenAICompatibleRefinementProvider(
    adapter_id="local.ollama_refinement",
    exposure=Exposure.LOCAL,
    endpoints={
        "ollama": "http://127.0.0.1:11434/v1",
    },
    prompts=prompt_catalog,
    require_credential=False,
)

registry.refinement.add(local_refinement)
```

Pipeline reference:

```json
{
  "adapter_id": "local.ollama_refinement",
  "settings": {
    "endpoint_id": "ollama",
    "model": "configured-local-model",
    "temperature": 0.2,
    "max_tokens": 1000
  }
}
```

Refinement settings:

| Setting | Required | Constraint |
| --- | --- | --- |
| `endpoint_id` | Yes | Must be registered by the host |
| `model` | Yes | Non-empty string |
| `temperature` | No | Number from 0 through 2 |
| `max_tokens` | No | Integer from 1 through 100,000 |

The pipeline's `refinement.prompt_id` must also exist in `prompt_catalog`.
Transcript and approved context artifacts are encoded as structured JSON in the
user message. Refinement failure remains recoverable: the pipeline engine records
a warning and restores the raw transcript.

## Testing a provider integration

Inject an implementation of `HTTPTransport` in unit tests. This allows a
provider adapter to be tested without network access and makes it possible to
assert the exact endpoint, headers, fields, and request payload.

Every new provider configuration should test:

- local/network endpoint restrictions;
- credential lookup failure;
- unknown endpoint and prompt IDs;
- request timeout and malformed response handling;
- response and upload limits; and
- raw-transcript fallback when refinement fails.
