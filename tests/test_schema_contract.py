"""Validate the public schema with an independent validator in test/CI installs."""

import copy
import json
import unittest
from pathlib import Path

from relayai_core import ConfigurationError, load_pipeline

try:
    import jsonschema
except ImportError:
    jsonschema = None


@unittest.skipIf(
    jsonschema is None, "install relayai-core[test] for independent schema checks"
)
class SchemaContractTests(unittest.TestCase):
    def test_schema_and_loader_agree_on_structural_fixtures(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/pipeline.v1.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        base = json.loads((root / "examples/local-audio.pipeline.json").read_text())
        fixtures = [
            base,
            {**base, "schema_version": True},
            {**base, "name": " "},
            {**base, "description": {}},
            {**base, "refinement": {}},
            {**base, "refinement": {"enabled": True}},
            {**base, "refinement": {"enabled": False, "adapter": None}},
            {**base, "transcription": {"adapter_id": "speech", "credential_id": ""}},
            {**base, "capture": {"activation": []}},
            {**base, "policy": {"local_only": "true"}},
        ]
        for document in fixtures:
            with self.subTest(document=document):
                schema_valid = validator.is_valid(document)
                try:
                    load_pipeline(copy.deepcopy(document))
                    loader_valid = True
                except ConfigurationError:
                    loader_valid = False
                self.assertEqual(loader_valid, schema_valid)
        for path in (root / "examples").glob("*.pipeline.json"):
            validator.validate(json.loads(path.read_text()))
            load_pipeline(path.read_text())
