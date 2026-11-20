import sys
import unicodedata
import unittest
import json
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from name_readings import DEFAULT_SOURCE as JSON_SOURCE, build_index, lookup_character, lookup_name
from build_name_readings import DEFAULT_SOURCE as HTML_SOURCE, convert


class NameReadingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index()

    def test_multiple_readings_are_candidates_not_a_decision(self):
        result = lookup_character("樂", self.index)
        readings = {item["reading"] for item in result["candidates"]}
        self.assertTrue({"락", "악", "요"} <= readings)
        self.assertIsNone(result["confirmed_reading"])

    def test_surname_reading_candidates_are_not_collapsed(self):
        result = lookup_character("李", self.index, at_name_start=True)
        readings = {item["reading"] for item in result["candidates"]}
        self.assertTrue({"리", "이"} <= readings)
        derived = next(item for item in result["candidates"] if item["reading"] == "이")
        self.assertEqual(derived["source"], "initial_sound_law")

    def test_unregistered_character_is_preserved(self):
        result = lookup_character("龘", self.index)
        self.assertEqual(result["original"], "龘")
        self.assertEqual(result["status"], "unregistered")
        self.assertEqual(result["candidates"], [])

    def test_compatibility_character_uses_normalization_only_for_lookup(self):
        compatibility = "李"
        self.assertEqual(unicodedata.normalize("NFKC", compatibility), "李")
        result = lookup_character(compatibility, self.index)
        self.assertEqual(result["original"], compatibility)
        self.assertEqual(result["lookup_character"], "李")
        self.assertTrue(result["normalized_for_lookup"])
        self.assertTrue(result["candidates"])

    def test_name_original_and_confirmation_are_separate(self):
        result = lookup_name("杜慶寧", self.index)
        self.assertEqual(result["original"], "杜慶寧")
        self.assertIsNone(result["confirmed_reading"])
        self.assertEqual([item["original"] for item in result["characters"]], list("杜慶寧"))

    def test_json_can_be_rebuilt_from_html(self):
        rebuilt = convert(HTML_SOURCE)
        self.assertEqual(rebuilt["metadata"]["source_row_count"], 485)
        self.assertEqual(rebuilt["metadata"]["character_count"], 9111)
        self.assertEqual(rebuilt["characters"]["杜"], [{"reading": "두", "kinds": ["name"]}])
        self.assertEqual(rebuilt["metadata"]["source_sha256"], "dd002dd18a8d6c66b102c6db582f927c0590c5f07b3c38c6eb67613b455c8081")
        self.assertEqual(rebuilt, json.loads(JSON_SOURCE.read_text(encoding="utf-8")))
