import unittest

from review_helpers import (
    person_number_map,
    format_person_reference,
    filter_relationships_for_person,
    format_relationship_label,
    relationship_bbox_anchors, resolve_person_field_value,
)


class ReviewHelperTests(unittest.TestCase):
    def setUp(self):
        self.people = [
            {"person_id": "P1", "name": "杜慶寧"},
            {"person_id": "P2", "name": "子之建"},
            {"person_id": "P3", "name": "子之逢"},
        ]
        self.lookup = {person["person_id"]: person for person in self.people}
        self.numbers = person_number_map(self.people)
        self.name_getter = lambda person: person["name"]
        self.relationships = [
            {"relationship_id": "R1", "parent_candidate_id": "P1", "child_candidate_id": "P2", "review_status": "confirmed"},
            {"relationship_id": "R2", "parent_candidate_id": "P1", "child_candidate_id": "P3", "review_status": "needs_review"},
            {"relationship_id": "R3", "parent_candidate_id": "P2", "child_candidate_id": "P3", "review_status": "rejected"},
        ]

    def test_numbers_match_page_order(self):
        self.assertEqual(self.numbers, {"P1": 1, "P2": 2, "P3": 3})
        self.assertEqual(
            format_person_reference("P2", self.lookup, self.numbers, self.name_getter),
            "2. 子之建",
        )

    def test_filters_relationships_where_person_is_parent_or_child(self):
        related = filter_relationships_for_person(self.relationships, "P1")
        self.assertEqual([rel["relationship_id"] for rel in related], ["R1", "R2"])
        related_as_child = filter_relationships_for_person(self.relationships, "P3")
        self.assertEqual([rel["relationship_id"] for rel in related_as_child], ["R2", "R3"])

    def test_relationship_label_uses_scan_numbers_for_both_people(self):
        label = format_relationship_label(
            self.relationships[0], self.lookup, self.numbers, self.name_getter
        )
        self.assertEqual(label, "confirmed · 1. 杜慶寧 → 2. 子之建")

    def test_no_filter_returns_all_relationships(self):
        self.assertEqual(filter_relationships_for_person(self.relationships, None), self.relationships)

    def test_relationship_anchors_use_parent_bottom_and_child_top(self):
        parent = {"x": 100, "y": 50, "width": 20, "height": 80}
        child = {"x": 140, "y": 200, "width": 30, "height": 70}
        self.assertEqual(
            relationship_bbox_anchors(parent, child),
            ((110.0, 130.0), (155.0, 200.0)),
        )

    def test_person_field_value_prefers_manual_over_ocr_draft(self):
        value = resolve_person_field_value(
            "birth_text", {"birth_text": "검수 완료"}, {}, {"birth_text": "OCR 초안"}
        )
        self.assertEqual(value, "검수 완료")

    def test_person_field_value_uses_source_before_ocr_draft(self):
        value = resolve_person_field_value(
            "birth_text", {}, {"birth_text": "원본 입력"}, {"birth_text": "OCR 초안"}
        )
        self.assertEqual(value, "원본 입력")

    def test_person_field_value_automatically_falls_back_to_ocr_draft(self):
        value = resolve_person_field_value(
            "birth_text", {}, {}, {"birth_text": "壬子年三月生"}
        )
        self.assertEqual(value, "壬子年三月生")


if __name__ == "__main__":
    unittest.main()
