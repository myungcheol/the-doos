import copy
import unittest

from person_data_model import (
    build_person_registry,
    build_raw_data,
    build_reviewed_data,
    ensure_person_uid,
    make_source_occurrence,
    strip_name_marker,
)


class PersonDataModelTests(unittest.TestCase):
    def test_registry_clears_stale_solar_date_after_same_source_text_is_corrected(self):
        occurrence = {"source_occurrence_id": "OCC_1"}
        old_solar = {"source_text": "옛 판독", "start": "0975-11-20", "end": "0975-11-20"}
        previous = {"persons": {"PER_1": {
            "person_uid": "PER_1", "canonical_name_hanja": "甲", "aliases": [],
            "source_occurrences": [occurrence],
            "reviewed_data": {"birth_text": "옛 판독", "birth_solar": old_solar},
            "raw_data_latest": {"source_occurrence": occurrence},
        }}}
        person = {"person_uid": "PER_1", "name_hanja_candidate": "甲",
                  "birth_text": "수정된 판독", "birth_solar": None,
                  "raw_data": {"source_occurrence": occurrence}}
        registry = build_person_registry([person], copy.deepcopy(previous))
        self.assertEqual(registry["persons"]["PER_1"]["reviewed_data"]["birth_text"], "수정된 판독")
        self.assertIsNone(registry["persons"]["PER_1"]["reviewed_data"]["birth_solar"])
        other_edition = dict(person, raw_data={"source_occurrence": {"source_occurrence_id": "OCC_2"}})
        preserved = build_person_registry([other_edition], copy.deepcopy(previous))
        self.assertEqual(preserved["persons"]["PER_1"]["reviewed_data"]["birth_solar"], old_solar)

    def test_child_marker_is_removed_but_preserved_separately(self):
        self.assertEqual(strip_name_marker("子之建"), ("之建", "子", "male"))
        self.assertEqual(strip_name_marker("女明玉"), ("明玉", "女", "female"))
        self.assertEqual(strip_name_marker("杜慶寧"), ("杜慶寧", None, None))

    def test_uid_is_persistent_and_opaque_not_location_based(self):
        person = {
            "source_page": "001.jpg", "person_id": "001_P0001",
            "source_row_id": "row1", "source_column_id": "col1",
            "bbox": {"x": 10, "y": 20, "width": 5, "height": 20},
        }
        state = {"person_uid_map": {}, "edition": {"edition_id": "edition-1987"}}
        first = ensure_person_uid(person, state)
        renamed_candidate_id = dict(person, person_id="renumbered_P0001")
        second = ensure_person_uid(renamed_candidate_id, state)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("PER_"))
        self.assertNotIn("001.jpg", first)

    def test_source_occurrence_records_edition_and_coordinates_separately(self):
        person = {
            "source_page": "001.jpg", "person_id": "P1", "source_row_id": "row1",
            "source_column_id": "col3", "bbox": {"x": 10, "y": 20, "width": 5, "height": 20},
        }
        page = {"source_image": "scan/001.jpg", "rows": [{
            "row_id": "row1", "row_number": 2,
            "columns": [{"column_id": "col3", "order_right_to_left": 3}],
        }]}
        occurrence = make_source_occurrence(
            person, page, {"edition_id": "family-1987", "publication_year": 1987},
            {"printed_page": "12"}, [person],
        )
        self.assertEqual(occurrence["publication_year"], 1987)
        self.assertEqual(occurrence["printed_page"], "12")
        self.assertEqual(occurrence["column_number_right_to_left"], 3)
        self.assertEqual(occurrence["position_in_column"], 1)
        self.assertTrue(occurrence["source_occurrence_id"].startswith("OCC_"))

    def test_raw_and_reviewed_data_are_separate(self):
        person = {
            "name_hanja_candidate": "之建", "raw_name_ocr": "子之建",
            "transcribed_name_hanja": "之建", "sex_marker": "子", "gender": "male",
            "birth_text": "壬子年三月生", "spouses": [
                {"type": "wife", "name_and_record": "洪氏"},
                {"type": "concubine", "name_and_record": "金氏"},
            ],
        }
        raw = build_raw_data(person, {"source_image": "001.jpg"}, {
            "source_record_ocr_text": "壬子年三月生", "evidence": {"birth_text": ["壬子年三月生"]},
            "field_sources": {},
        }, {"source_occurrence_id": "OCC_1"})
        reviewed = build_reviewed_data(person)
        self.assertEqual(raw["name_ocr"]["raw_text"], "子之建")
        self.assertEqual(reviewed["name_hanja"], "之建")
        self.assertEqual(len(reviewed["spouses"]), 2)
        self.assertEqual(reviewed["spouses"][1]["type"], "concubine")


    def test_raw_record_data_preserves_all_ocr_column_bboxes(self):
        columns = [{
            "column_id": "col_birth", "text": "壬子年三月生",
            "bbox": {"x": 100, "y": 20, "width": 12, "height": 90},
            "token_boxes": [],
        }]
        raw = build_raw_data(
            {"raw_name_ocr": "子之建", "bbox": {"x": 200, "y": 10, "width": 10, "height": 80}},
            {"source_image": "001.jpg"},
            {"source_record_ocr_text": "壬子年三月生", "columns": columns},
            {"source_occurrence_id": "OCC_BBOX"},
        )
        self.assertEqual(raw["record_ocr"]["columns"], columns)
        self.assertEqual(raw["record_ocr"]["columns"][0]["bbox"]["x"], 100)

    def test_registry_preserves_existing_confirmed_fields_when_new_occurrence_is_unreviewed(self):
        old = {
            "persons": {
                "PER_X": {
                    "person_uid": "PER_X", "canonical_name_hanja": "之建",
                    "aliases": [], "source_occurrences": [],
                    "reviewed_data": {
                        "name_hanja": "之建", "birth_text": "壬子年生",
                        "review_status": "confirmed", "information_review_status": "confirmed",
                    },
                }
            }
        }
        current = [{
            "person_uid": "PER_X",
            "reviewed_data": {
                "name_hanja": "之建", "birth_text": None,
                "review_status": "needs_review", "information_review_status": "needs_review",
            },
            "raw_data": {"source_occurrence": {"source_occurrence_id": "OCC_NEW"}},
        }]
        merged = build_person_registry(current, old)
        result = merged["persons"]["PER_X"]["reviewed_data"]
        self.assertEqual(result["birth_text"], "壬子年生")
        self.assertEqual(result["review_status"], "confirmed")
        self.assertEqual(result["information_review_status"], "confirmed")

    def test_registry_merges_occurrences_under_same_global_person_id(self):
        people = [
            {"person_uid": "PER_ABC", "reviewed_data": {"name_hanja": "之建"},
             "raw_data": {"source_occurrence": {"source_occurrence_id": "OCC_A", "publication_year": 1987}}},
            {"person_uid": "PER_ABC", "reviewed_data": {"name_hanja": "之建"},
             "raw_data": {"source_occurrence": {"source_occurrence_id": "OCC_B", "publication_year": 2024}}},
        ]
        registry = build_person_registry(people)
        self.assertEqual(len(registry["persons"]["PER_ABC"]["source_occurrences"]), 2)


if __name__ == "__main__":
    unittest.main()
