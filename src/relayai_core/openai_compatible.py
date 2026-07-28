from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from .credentials import CredentialResolver
from .errors import ConfigurationError, ProviderError
from .models import (
    AdapterRef,
    AudioArtifact,
    ContextArtifact,
    Exposure,
    TranscriptArtifact,
)


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_SPEECH_SETTINGS = {"endpoint_id", "model", "language", "temperature"}
_REFINEMENT_SETTINGS = {"endpoint_id", "model", "temperature", "max_tokens"}


class HTTPTransport(Protocol):
    async def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...

    async def post_multipart(
        self,
        url: str,
        headers: Mapping[str, str],
        fields: Mapping[str, str],
        file_field: str,
        filename: str,
        media_type: str,
        content: bytes,
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StandardLibraryHTTPTransport:
    """Small asynchronous HTTP transport with redirects and oversized replies blocked."""

    def __init__(self, max_response_bytes: int = 2 * 1024 * 1024) -> None:
        if max_response_bytes < 1:
            raise ConfigurationError("max_response_bytes must be positive")
        self._max_response_bytes = max_response_bytes
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def _send(
        self,
        request: urllib.request.Request,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"provider returned HTTP status {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = type(exc.reason).__name__
            raise ProviderError(f"provider connection failed: {reason}") from exc
        if len(body) > self._max_response_bytes:
            raise ProviderError("provider response exceeded the configured size limit")
        try:
            result = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError("provider returned invalid JSON") from exc
        if not isinstance(result, Mapping):
            raise ProviderError("provider response must be a JSON object")
        return result

    async def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                **headers,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        return await asyncio.to_thread(self._send, request, timeout_seconds)

    async def post_multipart(
        self,
        url: str,
        headers: Mapping[str, str],
        fields: Mapping[str, str],
        file_field: str,
        filename: str,
        media_type: str,
        content: bytes,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        boundary = f"relayai-{uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    ).encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            url,
            data=b"".join(chunks),
            headers={
                **headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        return await asyncio.to_thread(self._send, request, timeout_seconds)


class _OpenAICompatibleBase:
    def __init__(
        self,
        *,
        adapter_id: str,
        exposure: Exposure,
        endpoints: Mapping[str, str],
        credential_resolver: CredentialResolver | None,
        require_credential: bool,
        transport: HTTPTransport | None,
        timeout_seconds: float,
    ) -> None:
        if not adapter_id:
            raise ConfigurationError("adapter_id must be non-empty")
        if not isinstance(exposure, Exposure):
            raise ConfigurationError("exposure must be an Exposure value")
        if not endpoints:
            raise ConfigurationError("at least one endpoint must be configured")
        if timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be positive")
        self.adapter_id = adapter_id
        self.exposure = exposure
        self._endpoints = {
            endpoint_id: self._validate_endpoint(endpoint_id, url)
            for endpoint_id, url in endpoints.items()
        }
        self._credential_resolver = credential_resolver
        self._require_credential = require_credential
        self._transport = transport or StandardLibraryHTTPTransport()
        self._timeout_seconds = timeout_seconds

    def _validate_endpoint(self, endpoint_id: str, url: str) -> str:
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise ConfigurationError("endpoint IDs must be non-empty strings")
        if not isinstance(url, str):
            raise ConfigurationError(f"endpoint '{endpoint_id}' must be a URL")
        if any(character in url for character in "\r\n\t"):
            raise ConfigurationError(
                f"endpoint '{endpoint_id}' contains invalid control characters"
            )
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ConfigurationError(
                f"endpoint '{endpoint_id}' must use an HTTP(S) URL"
            )
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ConfigurationError(
                f"endpoint '{endpoint_id}' cannot contain credentials, query, or fragment"
            )
        if self.exposure is Exposure.LOCAL:
            if parts.hostname.lower() not in _LOOPBACK_HOSTS:
                raise ConfigurationError(
                    f"local endpoint '{endpoint_id}' must use a loopback host"
                )
        elif parts.scheme != "https":
            raise ConfigurationError(
                f"network endpoint '{endpoint_id}' must use HTTPS"
            )
        return url.rstrip("/")

    def _endpoint(self, config: AdapterRef, path: str) -> str:
        endpoint_id = _required_string(config.settings, "endpoint_id")
        try:
            base_url = self._endpoints[endpoint_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"endpoint '{endpoint_id}' is not allowlisted for {self.adapter_id}"
            ) from exc
        return f"{base_url}/{path.lstrip('/')}"

    def _headers(self, config: AdapterRef) -> dict[str, str]:
        headers = {"User-Agent": "relayai-core"}
        if config.credential_id is None:
            if self._require_credential:
                raise ConfigurationError(
                    f"{self.adapter_id} requires a credential_id"
                )
            return headers
        if self._credential_resolver is None:
            raise ConfigurationError(
                f"{self.adapter_id} has no credential resolver"
            )
        secret = self._credential_resolver.resolve(config.credential_id)
        if "\r" in secret or "\n" in secret:
            raise ConfigurationError("resolved bearer credential is not header-safe")
        headers["Authorization"] = f"Bearer {secret}"
        return headers


class OpenAICompatibleSpeechProvider(_OpenAICompatibleBase):
    def __init__(
        self,
        endpoints: Mapping[str, str],
        *,
        adapter_id: str = "openai_compatible.speech",
        exposure: Exposure = Exposure.NETWORK,
        credential_resolver: CredentialResolver | None = None,
        require_credential: bool = True,
        transport: HTTPTransport | None = None,
        timeout_seconds: float = 60,
        max_audio_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        super().__init__(
            adapter_id=adapter_id,
            exposure=exposure,
            endpoints=endpoints,
            credential_resolver=credential_resolver,
            require_credential=require_credential,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        if max_audio_bytes < 1:
            raise ConfigurationError("max_audio_bytes must be positive")
        self._max_audio_bytes = max_audio_bytes

    async def transcribe(
        self, audio: AudioArtifact, config: AdapterRef
    ) -> TranscriptArtifact:
        _reject_unknown_settings(config.settings, _SPEECH_SETTINGS, self.adapter_id)
        if not audio.content:
            raise ConfigurationError("audio content cannot be empty")
        if len(audio.content) > self._max_audio_bytes:
            raise ConfigurationError("audio exceeds the configured upload limit")
        model = _required_string(config.settings, "model")
        fields = {"model": model, "response_format": "json"}
        language = config.settings.get("language")
        if language is not None:
            if not isinstance(language, str) or not language:
                raise ConfigurationError("language must be a non-empty string")
            fields["language"] = language
        temperature = config.settings.get("temperature")
        if temperature is not None:
            fields["temperature"] = _number_string(
                temperature, "temperature", minimum=0, maximum=1
            )
        response = await self._transport.post_multipart(
            self._endpoint(config, "audio/transcriptions"),
            self._headers(config),
            fields,
            "file",
            _audio_filename(audio.media_type),
            audio.media_type,
            audio.content,
            self._timeout_seconds,
        )
        text = response.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("speech provider response has no transcript text")
        response_language = response.get("language")
        if response_language is not None and not isinstance(response_language, str):
            raise ProviderError("speech provider language must be a string")
        metadata = {
            key: response[key]
            for key in ("duration", "usage")
            if key in response
        }
        return TranscriptArtifact(
            text=text,
            language=response_language,
            provider_metadata=metadata,
        )


class OpenAICompatibleRefinementProvider(_OpenAICompatibleBase):
    def __init__(
        self,
        endpoints: Mapping[str, str],
        prompts: Mapping[str, str],
        *,
        adapter_id: str = "openai_compatible.refinement",
        exposure: Exposure = Exposure.NETWORK,
        credential_resolver: CredentialResolver | None = None,
        require_credential: bool = True,
        transport: HTTPTransport | None = None,
        timeout_seconds: float = 60,
    ) -> None:
        super().__init__(
            adapter_id=adapter_id,
            exposure=exposure,
            endpoints=endpoints,
            credential_resolver=credential_resolver,
            require_credential=require_credential,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._prompts = dict(prompts)
        if not self._prompts or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            for key, value in self._prompts.items()
        ):
            raise ConfigurationError("prompts must contain non-empty IDs and text")

    async def refine(
        self,
        transcript: TranscriptArtifact,
        context: tuple[ContextArtifact, ...],
        config: AdapterRef,
        prompt_id: str | None,
    ) -> str:
        _reject_unknown_settings(
            config.settings, _REFINEMENT_SETTINGS, self.adapter_id
        )
        if prompt_id is None:
            raise ConfigurationError("refinement requires a prompt_id")
        try:
            system_prompt = self._prompts[prompt_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"prompt '{prompt_id}' is not allowlisted for {self.adapter_id}"
            ) from exc
        payload: dict[str, Any] = {
            "model": _required_string(config.settings, "model"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "transcript": transcript.text,
                            "context": [
                                {
                                    "provider_id": item.provider_id,
                                    "values": item.values,
                                }
                                for item in context
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        temperature = config.settings.get("temperature")
        if temperature is not None:
            payload["temperature"] = _number(
                temperature, "temperature", minimum=0, maximum=2
            )
        max_tokens = config.settings.get("max_tokens")
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
                raise ConfigurationError("max_tokens must be an integer")
            if max_tokens < 1 or max_tokens > 100_000:
                raise ConfigurationError("max_tokens must be between 1 and 100000")
            payload["max_tokens"] = max_tokens
        response = await self._transport.post_json(
            self._endpoint(config, "chat/completions"),
            self._headers(config),
            payload,
            self._timeout_seconds,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "refinement provider response has no message content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError(
                "refinement provider response has no message content"
            )
        return content


def _required_string(settings: Mapping[str, Any], name: str) -> str:
    value = settings.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"setting '{name}' must be a non-empty string")
    return value


def _reject_unknown_settings(
    settings: Mapping[str, Any], allowed: set[str], adapter_id: str
) -> None:
    unknown = set(settings) - allowed
    if unknown:
        raise ConfigurationError(
            f"{adapter_id} contains unknown settings: {sorted(unknown)}"
        )


def _number(
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ConfigurationError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return result


def _number_string(
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> str:
    return str(_number(value, name, minimum=minimum, maximum=maximum))


def _audio_filename(media_type: str) -> str:
    extensions = {
        "audio/flac": "flac",
        "audio/m4a": "m4a",
        "audio/mp3": "mp3",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }
    try:
        extension = extensions[media_type]
    except KeyError as exc:
        raise ConfigurationError(
            f"unsupported audio media type: {media_type}"
        ) from exc
    return f"audio.{extension}"
