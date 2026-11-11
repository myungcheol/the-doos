"""Cross-page review extension tests."""
from copy import deepcopy
from pathlib import Path
import unittest

import cv2
import numpy as np

from ocr.jokbo_ocr import detect_large_printed_name_regions
from review.data_model import ensure_person_uid
from review.extensions import (merge_review_sources, previous_row_people, orphan_columns, orphan_regions,
                               make_continuation, apply_continuations, recover_name_candidates,
                               continuation_field_parts, append_continuation_text,
                               append_continuation_spouses, continuation_suppressions_for_save,
                               continuation_needs_review)
from review.person_info import extract_continuation_info_draft


def column(identifier, x, text="原文"):
    return {"column_id": identifier, "text": text, "mean_confidence": 81,
            "bbox": {"x": x, "y": 100, "width": 18, "height": 80},
            "token_boxes": [{"text": "文", "bbox": {"x": x, "y": 140, "width": 10, "height": 15}}]}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.previous = {"source_image": "001.jpg", "rows": [{"row_id": "001_row_01", "row_number": 1}]}
        self.row = {"row_id": "002_row_01", "row_number": 1,
                    "columns": [column("c1", 600), column("c2", 550), column("c3", 250), column("header", 50, "六世")]}
        self.page = {"source_image": "002.jpg", "rows": [self.row]}
        self.people = [
            {"person_id": "p1", "source_page": "001.jpg", "source_row_id": "001_row_01", "bbox": {"x": 500}},
            {"person_id": "p2", "source_page": "001.jpg", "source_row_id": "001_row_01", "bbox": {"x": 200}},
            {"person_id": "p3", "source_page": "002.jpg", "source_row_id": "002_row_01", "bbox": {"x": 300, "width": 30}},
        ]
        self.state = {"edition": {"edition_id": "fixture", "publication_year": 1987}}

    def test_partial_row_before_new_name_is_orphan(self):
        columns = orphan_columns(self.row, self.people)
        self.assertEqual([c["column_id"] for c in columns], ["c1", "c2"])
        self.assertEqual([p["person_id"] for p in previous_row_people(self.page, self.row, [self.page, self.previous], self.people, self.state)], ["p2", "p1"])

    def test_nameless_row_includes_all_text_except_generation(self):
        self.assertEqual([c["column_id"] for c in orphan_columns(self.row, [])], ["c1", "c2", "c3"])

    def test_adjacent_orphan_columns_form_one_region_with_original_evidence(self):
        row = {"row_id": "r", "columns": [column("a", 600, "甲"), column("b", 575, "乙"),
                                             column("c", 450, "丙")]}
        regions = orphan_regions(row, [])
        self.assertEqual([[c["column_id"] for c in r["columns"]] for r in regions], [["a", "b"], ["c"]])
        self.assertEqual(regions[0]["bbox"], {"x": 575, "y": 100, "width": 43, "height": 80})
        self.assertEqual(regions[0]["text"], "甲\n乙")
        self.assertEqual(regions[0]["columns"][0]["token_boxes"], row["columns"][0]["token_boxes"])

    def test_missing_immediate_previous_page_does_not_suggest_remote_page(self):
        third = {"source_image": "003.jpg", "rows": [{"row_id": "003_row_01", "row_number": 1}]}
        self.assertEqual(previous_row_people(third, third["rows"][0], [self.previous, third], self.people, self.state), [])

    def test_rejected_person_does_not_claim_columns(self):
        self.assertEqual(len(orphan_columns(self.row, self.people, {"people_updates": {"p3": {"review_status": "rejected"}}})), 3)

    def test_confirmed_columns_are_not_offered_again(self):
        state = {"continuation_links": [{"review_status": "confirmed", "source_row_id": self.row["row_id"],
                                         "columns": [self.row["columns"][0]]}]}
        self.assertEqual([c["column_id"] for c in orphan_columns(self.row, self.people, state)], ["c2"])

    def test_link_preserves_text_coordinates_and_reviewed_biography(self):
        source = deepcopy(self.page)
        link = make_continuation(self.page, self.row, [self.row["columns"][0]], self.people[1], self.state)
        self.state["continuation_links"] = [link]
        person = {"person_uid": link["target_person_uid"], "raw_data": {"record_ocr": {"text": "기존 원문"}},
                  "source_occurrences": [], "biography_text": "검수자가 정리한 기록"}
        apply_continuations(person, self.state)
        self.assertEqual(person["biography_text"], "검수자가 정리한 기록")
        self.assertEqual(person["raw_data"]["record_ocr"]["text"], "기존 원문")
        exported = person["raw_data"]["record_ocr"]["continuations"][0]
        self.assertEqual(exported["columns"][0], self.row["columns"][0])
        self.assertEqual(exported["source_occurrence"]["source_image"], "002.jpg")
        self.assertEqual(exported["source_occurrence"]["row_number"], 1)
        self.assertEqual(person["source_occurrences"][0]["occurrence_type"], "record_continuation")
        self.assertEqual(self.page, source)
        with self.assertRaises(ValueError):
            make_continuation(self.page, self.row, [self.row["columns"][0]], self.people[0], self.state)

    def test_linked_mixed_record_is_split_with_original_column_evidence(self):
        texts = ["穆宗即拜為左司官", "又以宮池為公", "邑封某君", "某宗九年七月",
                 "卒6禮葬于扶", "郡下西面石佛", "庚坐之原", "夫人李氏甲",
                 "七月七日生庚", "七月十九日卒"]
        columns = [column(f"c{i}", 600 - 25 * i, text) for i, text in enumerate(texts)]
        draft = extract_continuation_info_draft(columns)
        values = draft["draft_values"]
        self.assertEqual(values["office_title"], " / ".join(texts[:3]))
        self.assertEqual(values["death_text"], " / ".join([texts[3], "卒6"]))
        self.assertEqual(values["burial_text"], " / ".join(["禮葬于扶", texts[5], texts[6]]))
        self.assertEqual(values["spouse_text"], " / ".join(texts[7:]))
        self.assertNotIn("birth_text", values)
        self.assertEqual(draft["field_sources"]["burial_text"][1]["bbox"], columns[5]["bbox"])
        self.assertEqual(draft["field_sources"]["spouse_text"][0]["token_boxes"], columns[7]["token_boxes"])
        self.assertEqual(values["biography_text"].splitlines(), texts)

    def test_continuation_fields_append_once_and_reviewer_removal_is_respected(self):
        columns = [column("a", 600, "某年卒"), column("b", 575, "禮葬于某原")]
        link = make_continuation(self.page, self.row, columns, self.people[1], self.state)
        self.state["continuation_links"] = [link]
        parts = continuation_field_parts(self.people[1], self.state)
        self.assertTrue(continuation_needs_review(parts, {"information_review_status": "confirmed"}))
        death = parts["death_text"]
        shown = append_continuation_text("기존 판독", death)
        self.assertEqual(append_continuation_text(shown, death), shown)
        suppressed = continuation_suppressions_for_save({}, {"death_text": "기존 판독"}, [], parts)
        self.assertEqual(suppressed["death_text"], [link["continuation_id"]])
        self.assertEqual(append_continuation_text("기존 판독", death, suppressed["death_text"]), "기존 판독")
        reviewed = {"death_text": death[0]["text"],
                    "burial_text": parts["burial_text"][0]["text"],
                    "biography_text": parts["biography_text"][0]["text"]}
        self.assertFalse(continuation_needs_review(parts, reviewed))
        self.assertEqual(append_continuation_spouses([], []), [])
        link["review_status"] = "rejected"
        self.assertEqual(continuation_field_parts(self.people[1], self.state), {})

    def test_linked_burial_without_a_leading_keyword_keeps_previous_column(self):
        columns = [column("a", 600, "基某山"), column("b", 575, "壬坐之原"),
                   column("c", 550, "基失傳有設壇")]
        draft = extract_continuation_info_draft(columns)
        self.assertEqual(draft["draft_values"]["burial_text"], " / ".join(c["text"] for c in columns))

    def test_unverified_linked_spouse_can_be_removed_without_reappearing(self):
        part = {"continuation_id": "link1", "source_page": "002.jpg", "text": "夫人某氏"}
        spouses = append_continuation_spouses([{"type": "wife", "name_and_record": "기존 배우자"}], [part])
        self.assertEqual([item["type"] for item in spouses], ["wife", "other"])
        suppressed = continuation_suppressions_for_save(
            {}, {"spouse_text": ""}, spouses[:1], {"spouse_text": [part]})
        self.assertEqual(suppressed["spouses"], ["link1"])
        self.assertEqual(append_continuation_spouses(spouses[:1], [part], suppressed["spouses"]), spouses[:1])

    def test_detached_link_is_excluded_and_can_be_relinked(self):
        link = make_continuation(self.page, self.row, [self.row["columns"][0]], self.people[1], self.state)
        link["review_status"] = "rejected"
        self.state["continuation_links"] = [link]
        person = {"person_uid": link["target_person_uid"], "raw_data": {"record_ocr": {}}, "source_occurrences": []}
        apply_continuations(person, self.state)
        self.assertNotIn("continuations", person["raw_data"]["record_ocr"])
        make_continuation(self.page, self.row, [self.row["columns"][0]], self.people[1], self.state)

    def test_confirmed_continuation_can_span_three_pages(self):
        link = make_continuation(self.page, self.row, [self.row["columns"][0]], self.people[1], self.state)
        self.state["continuation_links"] = [link]
        third_row = {"row_id": "003_row_01", "row_number": 1}
        third = {"source_image": "003.jpg", "rows": [third_row]}
        targets = previous_row_people(third, third_row, [third, self.previous, self.page], self.people[:2], self.state)
        self.assertEqual([p["person_id"] for p in targets], ["p2"])

    def test_merge_is_idempotent_and_preserves_existing_ids(self):
        original = deepcopy(self.people)
        self.state.update(supplemental_pages=[{"page_result": self.previous, "people": self.people[:2]}], additional_people=[self.people[2]])
        merged = merge_review_sources(self.people, [], [self.page], self.state)
        again = merge_review_sources(*merged, self.state)
        self.assertEqual(merged, again)
        self.assertEqual(self.people, original)
        self.assertEqual(len(merged[2]), 2)


class SplitGlyphTests(unittest.TestCase):
    def split_glyph_image(self):
        image = np.full((130, 180, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (60, 12), (85, 39), (0, 0, 0), -1)
        cv2.rectangle(image, (60, 62), (85, 74), (0, 0, 0), -1)
        cv2.rectangle(image, (65, 77), (80, 85), (0, 0, 0), -1)
        return image

    def test_vertically_split_glyph_is_detected_with_offset(self):
        image = self.split_glyph_image()
        local = detect_large_printed_name_regions(image, 0, 0)
        offset = detect_large_printed_name_regions(image, 41, 86)
        self.assertEqual(len(local), 1)
        self.assertEqual(len(offset), 1)
        self.assertEqual(offset[0]["bbox"]["x"], local[0]["bbox"]["x"] + 41)
        self.assertEqual(offset[0]["bbox"]["y"], local[0]["bbox"]["y"] + 86)
        self.assertEqual(local[0]["component_count"], 2)

    def test_recovery_keeps_existing_people_and_deduplicates(self):
        image = self.split_glyph_image()
        page = {"source_image": "002.jpg", "rows": [{"row_id": "r1", "bbox": {"x": 41, "y": 86, "width": 180, "height": 130}, "columns": []}]}
        result = recover_name_candidates(image, page, [], (41, 86))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["review_status"], "needs_review")
        self.assertEqual(result[0]["raw_name_ocr"], "")
        self.assertEqual(recover_name_candidates(image, page, result, (41, 86)), [])
        state = {}
        uid = ensure_person_uid(result[0], state)
        merged, _, _ = merge_review_sources(result, [], [page], {**state, "additional_people": result})
        self.assertEqual(ensure_person_uid(merged[0], state), uid)

    def test_recovery_without_offset_preserves_matching_raw_ocr(self):
        image = self.split_glyph_image()
        source = {"column_id": "c1", "text": "子甲", "mean_confidence": 71,
                  "bbox": {"x": 58, "y": 10, "width": 30, "height": 80}}
        page = {"source_image": "002.jpg", "rows": [{"row_id": "r1", "bbox": {"x": 0, "y": 0, "width": 180, "height": 130}, "columns": [source]}]}
        result = recover_name_candidates(image, page, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["raw_name_ocr"], "子甲")
        self.assertEqual(result[0]["source_column_id"], "c1")
        self.assertEqual(result[0]["bbox"]["x"], 60)

    def test_sample_page_002_row_one_geometry(self):
        path = Path(__file__).resolve().parents[2] / "scan/genealogy/002.jpg"
        if not path.exists():
            self.skipTest("샘플 스캔 미포함")
        image = cv2.imread(str(path))
        results = detect_large_printed_name_regions(image[86:216, 41:640], 41, 86)
        self.assertTrue(any(235 <= r["bbox"]["x"] <= 245 and 115 <= r["bbox"]["y"] <= 125 for r in results))

    def test_sample_page_001_does_not_add_prose_as_names(self):
        path = Path(__file__).resolve().parents[2] / "scan/genealogy/001.jpg"
        if not path.exists():
            self.skipTest("샘플 스캔 미포함")
        image = cv2.imread(str(path))
        results = detect_large_printed_name_regions(image[82:216, 55:644], 55, 82)
        self.assertEqual(len(results), 1)

    def test_sample_page_003_recovers_six_rightmost_names(self):
        path = Path(__file__).resolve().parents[2] / "scan/genealogy/003.jpg"
        if not path.exists():
            self.skipTest("샘플 스캔 미포함")
        rows = []
        for index, (y, height) in enumerate([(90, 132), (228, 132), (366, 128),
                                           (500, 128), (634, 126), (766, 137)], start=1):
            rows.append({"row_id": f"r{index}", "bbox": {"x": 59, "y": y, "width": 587, "height": height}, "columns": []})
        rows[1]["columns"] = [
            {"column_id": "c1", "text": "子", "bbox": {"x": 607, "y": 245, "width": 25, "height": 22}},
            {"column_id": "c2", "text": "瑛", "bbox": {"x": 605, "y": 291, "width": 27, "height": 35}}]
        page = {"source_image": str(path), "rows": rows}
        image = cv2.imread(str(path))
        full = recover_name_candidates(image, page, [])
        rightmost = [p for p in full if p["bbox"]["x"] > 600]
        self.assertEqual(len(rightmost), 6)
        self.assertEqual(next(p for p in rightmost if p["source_row_id"] == "r2")["raw_name_ocr"], "子\n瑛")
        roi = image[88:905, 59:646]
        offset = recover_name_candidates(roi, page, [], (59, 88))
        self.assertEqual([p["bbox"] for p in full], [p["bbox"] for p in offset])
        self.assertEqual(recover_name_candidates(image, page, full), [])


if __name__ == "__main__":
    unittest.main()
