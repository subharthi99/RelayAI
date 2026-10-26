from __future__ import annotations

import json
import math
from urllib.parse import urlsplit, parse_qsl
from collections.abc import Mapping
from typing import Any

from .errors import ConfigurationError
from .models import (
    CURRENT_SCHEMA_VERSION,
    AdapterRef,
    CaptureConfig,
    PipelineDefinition,
    PipelinePolicy,
    RefinementConfig,
)


_FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "token",
    "authorization",
}

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "name",
    "description",
    "capture",
    "transcription",
    "context",
    "refinement",
    "policy",
    "destinations",
}
_ADAPTER_REF_KEYS = {"id", "adapter_id", "settings", "credential_id"}


def _reject_embedded_secrets(value: Any, path: str = "pipeline") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            credential_suffixes = (
                "_api_key",
                "_access_token",
                "_refresh_token",
                "_password",
                "_secret",
            )
            if normalized in _FORBIDDEN_SECRET_KEYS or normalized.endswith(
                credential_suffixes
            ):
                raise ConfigurationError(f"embedded credential at {path}.{key}")
            _reject_embedded_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_embedded_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and "://" in value:
        try:
            parts = urlsplit(value)
            if parts.username is not None or parts.password is not None:
                raise ConfigurationError(f"credential-bearing URL at {path}")
            sensitive = {
                "key",
                "api_key",
                "apikey",
                "token",
                "access_token",
                "password",
                "secret",
                "signature",
                "sig",
            }
            if any(
                key.lower().replace("-", "_") in sensitive
                for key, _ in parse_qsl(parts.query)
            ):
                raise ConfigurationError(f"credential-bearing URL at {path}")
        except ValueError as exc:
            raise ConfigurationError(f"invalid URL at {path}") from exc
    elif isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError(f"non-finite number at {path}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_unknown_keys(
    value: Mapping[str, Any], allowed: set[str], field_name: str
) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ConfigurationError(
            f"{field_name} contains unknown fields: {sorted(unknown)}"
        )


def _boolean(value: Mapping[str, Any], key: str, default: bool) -> bool:
    result = value.get(key, default)
    if not isinstance(result, bool):
        raise ConfigurationError(f"{key} must be a boolean")
    return result


def _adapter_ref(
    value: Any, field_name: str, *, require_instance_id: bool = False
) -> AdapterRef:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{field_name} must be an object")
    allowed_keys = (
        _ADAPTER_REF_KEYS if require_instance_id else _ADAPTER_REF_KEYS - {"id"}
    )
    _reject_unknown_keys(value, allowed_keys, field_name)
    adapter_id = value.get("adapter_id")
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        raise ConfigurationError(f"{field_name}.adapter_id must be a non-empty string")
    settings = value.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigurationError(f"{field_name}.settings must be an object")
    credential_id = value.get("credential_id")
    if "credential_id" in value and (
        not isinstance(credential_id, str) or not credential_id.strip()
    ):
        raise ConfigurationError(
            f"{field_name}.credential_id must be a non-empty string"
        )
    instance_id = value.get("id")
    if instance_id is not None and (
        not isinstance(instance_id, str) or not instance_id.strip()
    ):
        raise ConfigurationError(f"{field_name}.id must be a non-empty string")
    if require_instance_id and instance_id is None:
        raise ConfigurationError(f"{field_name}.id is required")
    return AdapterRef(
        adapter_id.strip(),
        dict(settings),
        credential_id,
        instance_id.strip() if isinstance(instance_id, str) else None,
    )


def load_pipeline(document: str | bytes | Mapping[str, Any]) -> PipelineDefinition:
    try:
        if not isinstance(document, (str, bytes)):
            document = json.dumps(document, allow_nan=False)
        if len(document) > 1024 * 1024:
            raise ConfigurationError("pipeline document exceeds 1 MiB")
        data = json.loads(document, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError) as exc:
        raise ConfigurationError("pipeline is not valid JSON") from exc

    if not isinstance(data, Mapping):
        raise ConfigurationError("pipeline must be a JSON object")

    _reject_embedded_secrets(data)
    _reject_unknown_keys(data, _TOP_LEVEL_KEYS, "pipeline")
    version = data.get("schema_version")
    if isinstance(version, bool) or version != CURRENT_SCHEMA_VERSION:
        raise ConfigurationError(
            f"unsupported schema_version {version!r}; expected {CURRENT_SCHEMA_VERSION}"
        )

    pipeline_id = data.get("id")
    name = data.get("name")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise ConfigurationError("id must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError("name must be a non-empty string")
    if not isinstance(data.get("description", ""), str):
        raise ConfigurationError("description must be a string")

    destinations_value = data.get("destinations")
    if not isinstance(destinations_value, list) or not destinations_value:
        raise ConfigurationError("destinations must be a non-empty array")
    destinations = tuple(
        _adapter_ref(value, f"destinations[{index}]", require_instance_id=True)
        for index, value in enumerate(destinations_value)
    )
    destination_ids = [item.instance_id for item in destinations]
    if len(destination_ids) != len(set(destination_ids)):
        raise ConfigurationError("duplicate destination adapter IDs are not allowed")

    capture_value = data.get("capture", {})
    if not isinstance(capture_value, Mapping):
        raise ConfigurationError("capture must be an object")
    _reject_unknown_keys(capture_value, {"activation", "source"}, "capture")
    activation = capture_value.get("activation", "push_to_talk")
    if not isinstance(activation, str) or activation not in {"push_to_talk", "toggle"}:
        raise ConfigurationError("capture.activation must be push_to_talk or toggle")
    source = capture_value.get("source", "default_microphone")
    if not isinstance(source, str) or not source.strip():
        raise ConfigurationError("capture.source must be a non-empty string")
    capture = CaptureConfig(
        activation=activation,
        source=source,
    )

    context_value = data.get("context", [])
    if not isinstance(context_value, list):
        raise ConfigurationError("context must be an array")
    context = tuple(
        _adapter_ref(value, f"context[{index}]")
        for index, value in enumerate(context_value)
    )

    refinement_value = data.get("refinement", {"enabled": False})
    if not isinstance(refinement_value, Mapping):
        raise ConfigurationError("refinement must be an object")
    _reject_unknown_keys(
        refinement_value, {"enabled", "adapter", "prompt_id"}, "refinement"
    )
    if "refinement" in data and "enabled" not in refinement_value:
        raise ConfigurationError("refinement.enabled is required")
    refinement_enabled = _boolean(refinement_value, "enabled", False)
    refinement_adapter = refinement_value.get("adapter")
    prompt_id = refinement_value.get("prompt_id")
    if prompt_id is not None and (
        not isinstance(prompt_id, str) or not prompt_id.strip()
    ):
        raise ConfigurationError("refinement.prompt_id must be a non-empty string")
    refinement = RefinementConfig(
        enabled=refinement_enabled,
        adapter=(
            _adapter_ref(refinement_adapter, "refinement.adapter")
            if refinement_adapter is not None
            else None
        ),
        prompt_id=prompt_id,
    )
    if refinement.enabled and refinement.adapter is None:
        raise ConfigurationError(
            "refinement.adapter is required when refinement is enabled"
        )
    if "adapter" in refinement_value and refinement_adapter is None:
        raise ConfigurationError("refinement.adapter must be an object")
    if "prompt_id" in refinement_value and prompt_id is None:
        raise ConfigurationError("refinement.prompt_id must be a non-empty string")

    policy_value = data.get("policy", {})
    if not isinstance(policy_value, Mapping):
        raise ConfigurationError("policy must be an object")
    _reject_unknown_keys(
        policy_value,
        {
            "local_only",
            "confirm_network_destinations",
            "confirm_executable_destinations",
        },
        "policy",
    )
    policy = PipelinePolicy(
        local_only=_boolean(policy_value, "local_only", False),
        confirm_network_destinations=_boolean(
            policy_value, "confirm_network_destinations", True
        ),
        confirm_executable_destinations=_boolean(
            policy_value, "confirm_executable_destinations", True
        ),
    )

    return PipelineDefinition(
        schema_version=CURRENT_SCHEMA_VERSION,
        id=pipeline_id.strip(),
        name=name.strip(),
        description=data.get("description", ""),
        capture=capture,
        transcription=_adapter_ref(data.get("transcription"), "transcription"),
        context=context,
        refinement=refinement,
        policy=policy,
        destinations=destinations,
    )


def _ref_to_dict(value: AdapterRef) -> dict[str, Any]:
    result: dict[str, Any] = {
        "adapter_id": value.adapter_id,
        "settings": value.settings,
    }
    if value.credential_id is not None:
        result["credential_id"] = value.credential_id
    if value.id is not None:
        result["id"] = value.id
    return result


def export_pipeline(pipeline: PipelineDefinition) -> str:
    refinement: dict[str, Any] = {"enabled": pipeline.refinement.enabled}
    if pipeline.refinement.adapter is not None:
        refinement["adapter"] = _ref_to_dict(pipeline.refinement.adapter)
    if pipeline.refinement.prompt_id is not None:
        refinement["prompt_id"] = pipeline.refinement.prompt_id
    data = {
        "schema_version": pipeline.schema_version,
        "id": pipeline.id,
        "name": pipeline.name,
        "description": pipeline.description,
        "capture": {
            "activation": pipeline.capture.activation,
            "source": pipeline.capture.source,
        },
        "transcription": _ref_to_dict(pipeline.transcription),
        "context": [_ref_to_dict(value) for value in pipeline.context],
        "refinement": refinement,
        "policy": {
            "local_only": pipeline.policy.local_only,
            "confirm_network_destinations": (
                pipeline.policy.confirm_network_destinations
            ),
            "confirm_executable_destinations": (
                pipeline.policy.confirm_executable_destinations
            ),
        },
        "destinations": [_ref_to_dict(value) for value in pipeline.destinations],
    }
    _reject_embedded_secrets(data)
    document = json.dumps(data, indent=2, sort_keys=True, allow_nan=False)
    load_pipeline(document)
    return document
