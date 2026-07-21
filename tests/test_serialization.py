from __future__ import annotations

import json
import unittest

from relayai_core.errors import ConfigurationError
from relayai_core.serialization import export_pipeline, load_pipeline


def valid_document() -> dict:
    return {
        "schema_version": 1,
        "id": "private-dictation",
        "name": "Private dictation",
        "transcription": {
            "adapter_id": "local.whisper",
            "settings": {"model": "small"},
        },
        "refinement": {"enabled": False},
        "policy": {"local_only": True},
        "destinations": [
            {
                "id": "cursor",
                "adapter_id": "platform.focused-field",
                "settings": {},
            }
        ],
    }


class PipelineSerializationTests(unittest.TestCase):
    def test_round_trip_preserves_destination_instance_id(self) -> None:
        pipeline = load_pipeline(valid_document())
        exported = json.loads(export_pipeline(pipeline))

        self.assertEqual(pipeline.destinations[0].instance_id, "cursor")
        self.assertEqual(exported["destinations"][0]["id"], "cursor")
        self.assertTrue(exported["policy"]["local_only"])

    def test_rejects_unknown_schema_version(self) -> None:
        document = valid_document()
        document["schema_version"] = 2
        with self.assertRaisesRegex(ConfigurationError, "unsupported schema_version"):
            load_pipeline(document)

    def test_rejects_embedded_credentials_at_any_depth(self) -> None:
        document = valid_document()
        document["transcription"]["settings"]["api_key"] = "do-not-store"
        with self.assertRaisesRegex(ConfigurationError, "embedded credential"):
            load_pipeline(document)

    def test_rejects_provider_specific_secret_names(self) -> None:
        document = valid_document()
        document["transcription"]["settings"]["openai_api_key"] = "secret"
        with self.assertRaisesRegex(ConfigurationError, "embedded credential"):
            load_pipeline(document)

    def test_rejects_duplicate_destination_instance_ids(self) -> None:
        document = valid_document()
        document["destinations"].append(
            {
                "id": "cursor",
                "adapter_id": "builtin.file",
                "settings": {"path": "notes.txt"},
            }
        )
        with self.assertRaisesRegex(ConfigurationError, "duplicate destination"):
            load_pipeline(document)

    def test_enabled_refinement_requires_adapter(self) -> None:
        document = valid_document()
        document["refinement"] = {"enabled": True}
        with self.assertRaisesRegex(ConfigurationError, "adapter is required"):
            load_pipeline(document)

    def test_rejects_string_in_boolean_policy_field(self) -> None:
        document = valid_document()
        document["policy"]["local_only"] = "false"
        with self.assertRaisesRegex(ConfigurationError, "must be a boolean"):
            load_pipeline(document)

    def test_rejects_unknown_fields(self) -> None:
        document = valid_document()
        document["provider"] = "should-not-be-ignored"
        with self.assertRaisesRegex(ConfigurationError, "unknown fields"):
            load_pipeline(document)

    def test_destination_requires_stable_instance_id(self) -> None:
        document = valid_document()
        del document["destinations"][0]["id"]
        with self.assertRaisesRegex(ConfigurationError, "id is required"):
            load_pipeline(document)


if __name__ == "__main__":
    unittest.main()
