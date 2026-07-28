from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from typing import Any

from relayai_core.credentials import MappingCredentialResolver
from relayai_core.errors import ConfigurationError, ProviderError
from relayai_core.models import (
    AdapterRef,
    AudioArtifact,
    ContextArtifact,
    Exposure,
    TranscriptArtifact,
)
from relayai_core.openai_compatible import (
    OpenAICompatibleRefinementProvider,
    OpenAICompatibleSpeechProvider,
    StandardLibraryHTTPTransport,
)


class FakeTransport:
    def __init__(
        self,
        *,
        json_response: Mapping[str, Any] | None = None,
        multipart_response: Mapping[str, Any] | None = None,
    ) -> None:
        self.json_response = json_response or {}
        self.multipart_response = multipart_response or {}
        self.json_calls: list[dict[str, Any]] = []
        self.multipart_calls: list[dict[str, Any]] = []

    async def post_json(
        self, url, headers, payload, timeout_seconds
    ) -> Mapping[str, Any]:
        self.json_calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.json_response

    async def post_multipart(
        self,
        url,
        headers,
        fields,
        file_field,
        filename,
        media_type,
        content,
        timeout_seconds,
    ) -> Mapping[str, Any]:
        self.multipart_calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "fields": dict(fields),
                "file_field": file_field,
                "filename": filename,
                "media_type": media_type,
                "content": content,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.multipart_response


class OpenAICompatibleSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribes_with_allowlisted_endpoint_and_resolved_credential(
        self,
    ) -> None:
        transport = FakeTransport(
            multipart_response={
                "text": "hello world",
                "language": "en",
                "usage": {"seconds": 1},
            }
        )
        provider = OpenAICompatibleSpeechProvider(
            {"primary": "https://speech.example.test/v1"},
            credential_resolver=MappingCredentialResolver({"speech-key": "secret"}),
            transport=transport,
        )

        transcript = await provider.transcribe(
            AudioArtifact(b"RIFFdata"),
            AdapterRef(
                provider.adapter_id,
                {
                    "endpoint_id": "primary",
                    "model": "whisper-1",
                    "language": "en",
                    "temperature": 0,
                },
                credential_id="speech-key",
            ),
        )

        self.assertEqual(transcript.text, "hello world")
        self.assertEqual(transcript.language, "en")
        self.assertEqual(transcript.provider_metadata["usage"], {"seconds": 1})
        call = transport.multipart_calls[0]
        self.assertEqual(
            call["url"], "https://speech.example.test/v1/audio/transcriptions"
        )
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(call["filename"], "audio.wav")
        self.assertEqual(call["fields"]["response_format"], "json")

    async def test_rejects_unlisted_endpoint_before_transport(self) -> None:
        transport = FakeTransport(multipart_response={"text": "unused"})
        provider = OpenAICompatibleSpeechProvider(
            {"primary": "https://speech.example.test/v1"},
            credential_resolver=MappingCredentialResolver({"key": "secret"}),
            transport=transport,
        )
        with self.assertRaisesRegex(ConfigurationError, "not allowlisted"):
            await provider.transcribe(
                AudioArtifact(b"audio"),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "attacker", "model": "whisper-1"},
                    credential_id="key",
                ),
            )
        self.assertEqual(transport.multipart_calls, [])

    async def test_requires_credential_before_transport(self) -> None:
        transport = FakeTransport(multipart_response={"text": "unused"})
        provider = OpenAICompatibleSpeechProvider(
            {"primary": "https://speech.example.test/v1"},
            transport=transport,
        )
        with self.assertRaisesRegex(ConfigurationError, "credential_id"):
            await provider.transcribe(
                AudioArtifact(b"audio"),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "primary", "model": "whisper-1"},
                ),
            )
        self.assertEqual(transport.multipart_calls, [])

    async def test_rejects_header_injection_in_resolved_credential(self) -> None:
        transport = FakeTransport(multipart_response={"text": "unused"})
        provider = OpenAICompatibleSpeechProvider(
            {"primary": "https://speech.example.test/v1"},
            credential_resolver=MappingCredentialResolver(
                {"key": "secret\r\nX-Injected: yes"}
            ),
            transport=transport,
        )
        with self.assertRaisesRegex(ConfigurationError, "header-safe"):
            await provider.transcribe(
                AudioArtifact(b"audio"),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "primary", "model": "whisper-1"},
                    credential_id="key",
                ),
            )
        self.assertEqual(transport.multipart_calls, [])

    async def test_rejects_oversized_audio_and_unknown_settings(self) -> None:
        provider = OpenAICompatibleSpeechProvider(
            {"local": "http://127.0.0.1:8080/v1"},
            exposure=Exposure.LOCAL,
            require_credential=False,
            transport=FakeTransport(multipart_response={"text": "unused"}),
            max_audio_bytes=4,
        )
        config = AdapterRef(
            provider.adapter_id,
            {"endpoint_id": "local", "model": "tiny"},
        )
        with self.assertRaisesRegex(ConfigurationError, "upload limit"):
            await provider.transcribe(AudioArtifact(b"12345"), config)
        with self.assertRaisesRegex(ConfigurationError, "unknown settings"):
            await provider.transcribe(
                AudioArtifact(b"1234"),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "local", "model": "tiny", "url": "bad"},
                ),
            )

    async def test_rejects_invalid_speech_response(self) -> None:
        provider = OpenAICompatibleSpeechProvider(
            {"local": "http://localhost:8080/v1"},
            exposure=Exposure.LOCAL,
            require_credential=False,
            transport=FakeTransport(multipart_response={"text": ""}),
        )
        with self.assertRaisesRegex(ProviderError, "transcript"):
            await provider.transcribe(
                AudioArtifact(b"audio"),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "local", "model": "tiny"},
                ),
            )


class OpenAICompatibleRefinementTests(unittest.IsolatedAsyncioTestCase):
    async def test_refines_with_allowlisted_prompt_and_structured_context(
        self,
    ) -> None:
        transport = FakeTransport(
            json_response={
                "choices": [{"message": {"content": "Polished words."}}]
            }
        )
        provider = OpenAICompatibleRefinementProvider(
            {"primary": "https://refine.example.test/v1"},
            {"polish": "Polish the supplied transcript."},
            credential_resolver=MappingCredentialResolver({"refine-key": "secret"}),
            transport=transport,
        )
        result = await provider.refine(
            TranscriptArtifact("raw words"),
            (ContextArtifact("active-app", {"name": "Mail"}),),
            AdapterRef(
                provider.adapter_id,
                {
                    "endpoint_id": "primary",
                    "model": "model-a",
                    "temperature": 0.2,
                    "max_tokens": 200,
                },
                credential_id="refine-key",
            ),
            "polish",
        )

        self.assertEqual(result, "Polished words.")
        call = transport.json_calls[0]
        self.assertEqual(
            call["url"], "https://refine.example.test/v1/chat/completions"
        )
        self.assertEqual(
            call["payload"]["messages"][0]["content"],
            "Polish the supplied transcript.",
        )
        user_payload = json.loads(call["payload"]["messages"][1]["content"])
        self.assertEqual(user_payload["transcript"], "raw words")
        self.assertEqual(user_payload["context"][0]["values"]["name"], "Mail")

    async def test_rejects_unlisted_prompt_before_transport(self) -> None:
        transport = FakeTransport(
            json_response={"choices": [{"message": {"content": "unused"}}]}
        )
        provider = OpenAICompatibleRefinementProvider(
            {"local": "http://[::1]:11434/v1"},
            {"known": "Known prompt"},
            exposure=Exposure.LOCAL,
            require_credential=False,
            transport=transport,
        )
        with self.assertRaisesRegex(ConfigurationError, "not allowlisted"):
            await provider.refine(
                TranscriptArtifact("raw"),
                (),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "local", "model": "local-model"},
                ),
                "unknown",
            )
        self.assertEqual(transport.json_calls, [])

    async def test_rejects_invalid_refinement_response(self) -> None:
        provider = OpenAICompatibleRefinementProvider(
            {"local": "http://127.0.0.1:11434/v1"},
            {"polish": "Polish it"},
            exposure=Exposure.LOCAL,
            require_credential=False,
            transport=FakeTransport(json_response={"choices": []}),
        )
        with self.assertRaisesRegex(ProviderError, "message content"):
            await provider.refine(
                TranscriptArtifact("raw"),
                (),
                AdapterRef(
                    provider.adapter_id,
                    {"endpoint_id": "local", "model": "local-model"},
                ),
                "polish",
            )


class OpenAICompatibleConfigurationTests(unittest.TestCase):
    def test_local_adapter_requires_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "loopback"):
            OpenAICompatibleSpeechProvider(
                {"bad": "http://192.0.2.10:8080/v1"},
                exposure=Exposure.LOCAL,
                require_credential=False,
            )

    def test_network_adapter_requires_https_endpoint(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "HTTPS"):
            OpenAICompatibleSpeechProvider(
                {"bad": "http://speech.example.test/v1"}
            )

    def test_endpoint_cannot_embed_credentials_or_query(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "credentials"):
            OpenAICompatibleSpeechProvider(
                {"bad": "https://user:pass@example.test/v1"}
            )
        with self.assertRaisesRegex(ConfigurationError, "query"):
            OpenAICompatibleSpeechProvider(
                {"bad": "https://example.test/v1?token=secret"}
            )
        with self.assertRaisesRegex(ConfigurationError, "control characters"):
            OpenAICompatibleSpeechProvider(
                {"bad": "https://example.test/v1\r\nX-Injected: yes"}
            )

    def test_exposure_must_use_the_trusted_enum(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "Exposure"):
            OpenAICompatibleSpeechProvider(
                {"primary": "https://example.test/v1"},
                exposure="local",  # type: ignore[arg-type]
            )

    def test_mapping_resolver_rejects_unknown_and_empty_credentials(self) -> None:
        resolver = MappingCredentialResolver({"empty": ""})
        with self.assertRaisesRegex(ConfigurationError, "not found"):
            resolver.resolve("missing")
        with self.assertRaisesRegex(ConfigurationError, "empty"):
            resolver.resolve("empty")

    def test_standard_transport_rejects_oversized_and_invalid_json(self) -> None:
        class FakeResponse:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, limit: int) -> bytes:
                return self.body[:limit]

        class FakeOpener:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def open(self, request, timeout):
                return FakeResponse(self.body)

        transport = StandardLibraryHTTPTransport(max_response_bytes=4)
        transport._opener = FakeOpener(b"12345")
        request = __import__("urllib.request").request.Request(
            "https://example.test"
        )
        with self.assertRaisesRegex(ProviderError, "size limit"):
            transport._send(request, 1)

        transport._opener = FakeOpener(b"nope")
        with self.assertRaisesRegex(ProviderError, "invalid JSON"):
            transport._send(request, 1)


if __name__ == "__main__":
    unittest.main()
