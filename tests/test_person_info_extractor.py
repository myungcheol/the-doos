import unittest

from person_info_extractor import extract_person_info_draft, get_person_section_columns, get_field_source_columns


class PersonInfoExtractorTests(unittest.TestCase):
    def test_split_birth_ganji_and_death_components_are_ocr_drafts(self):
        person = {"person_id": "P", "source_row_id": "r", "bbox": {"x": 530, "y": 0, "width": 20, "height": 90}}
        texts = ["高麗穆宗八年乙", "生", "軍壬寅九月二十", "一日卒0基于老"]
        row = {"row_id": "r", "columns": [
            {"column_id": f"c{i}", "text": text,
             "bbox": {"x": 500 - i * 25, "y": 0, "width": 20, "height": 90}}
            for i, text in enumerate(texts)
        ]}
        draft = extract_person_info_draft(person, {"rows": [row]}, [person])
        birth = draft["draft_values"]["birth_date"]
        death = draft["draft_values"]["death_date"]
        self.assertEqual(draft["draft_values"]["birth_text"], "高麗穆宗八年乙 / 生")
        self.assertEqual((birth["country"], birth["ruler_or_era"], birth["regnal_year"]),
                         ("고려", "목종 穆宗", 8))
        self.assertEqual((birth["sexagenary_ocr"], birth["sexagenary_year"]), ("乙", "乙巳"))
        self.assertEqual((death["sexagenary_year"], death["month"], death["day"]),
                         ("壬寅", 9, 21))
        self.assertIsNone(death["ce_year"])
        self.assertEqual(draft["field_sources"]["birth_text"][0]["bbox"], row["columns"][0]["bbox"])

    def setUp(self):
        self.people = [
            {"person_id": "P1", "source_row_id": "row1", "bbox": {"x": 510, "y": 100, "width": 28, "height": 90}},
            {"person_id": "P2", "source_row_id": "row1", "bbox": {"x": 200, "y": 100, "width": 28, "height": 90}},
        ]
        self.row = {
            "row_id": "row1",
            "columns": [
                {"column_id": "c1", "text": "乙亥十月十五日生", "bbox": {"x": 475, "y": 110, "width": 20, "height": 100}},
                {"column_id": "c2", "text": "官至中書舍人", "bbox": {"x": 440, "y": 110, "width": 20, "height": 100}},
                {"column_id": "c3", "text": "配宜人李氏", "bbox": {"x": 405, "y": 110, "width": 20, "height": 100}},
                {"column_id": "c4", "text": "丙戌四月十九日生", "bbox": {"x": 155, "y": 110, "width": 20, "height": 100}},
                {"column_id": "c5", "text": "葬于主山壬坐之原", "bbox": {"x": 125, "y": 110, "width": 20, "height": 100}},
            ],
        }
        self.page = {"rows": [self.row]}

    def test_columns_are_assigned_to_person_to_the_right(self):
        p1_cols = get_person_section_columns(self.people[0], self.row, self.people)
        p2_cols = get_person_section_columns(self.people[1], self.row, self.people)
        self.assertEqual([c["column_id"] for c in p1_cols], ["c1", "c2", "c3"])
        self.assertEqual([c["column_id"] for c in p2_cols], ["c4", "c5"])

    def test_extracts_biography_and_keyword_fields(self):
        draft = extract_person_info_draft(self.people[0], self.page, self.people)
        self.assertIn("biography_text", draft["draft_values"])
        self.assertIn("birth_text", draft["draft_values"])
        self.assertIn("office_title", draft["draft_values"])
        self.assertIn("spouse_text", draft["draft_values"])
        self.assertTrue(draft["needs_review"])
        self.assertIn("乙亥", draft["source_record_ocr_text"])

    def test_field_source_columns_keep_bboxes_without_column_id_lookup(self):
        source = {
            "text": "乙亥十月十五日生",
            "bbox": {"x": 475, "y": 110, "width": 20, "height": 100},
            "token_boxes": [{"text": "生", "bbox": {"x": 475, "y": 190, "width": 10, "height": 12}}],
        }
        draft = {
            "field_sources": {"birth_text": [source]},
            # Deliberately use unrelated/missing IDs in the all-columns list.
            "columns": [{"column_id": "different-id", "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        }
        boxes = get_field_source_columns(draft, "birth_text")
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["bbox"], source["bbox"])
        self.assertEqual(boxes[0]["token_boxes"], source["token_boxes"])

    def test_field_source_columns_skip_items_without_bbox(self):
        draft = {"field_sources": {"death_text": [{"text": "卒"}, {"text": "庚寅卒", "bbox": {"x": 10, "y": 20, "width": 5, "height": 40}}]}}
        self.assertEqual(len(get_field_source_columns(draft, "death_text")), 1)

    def test_extracts_burial_for_second_person(self):
        draft = extract_person_info_draft(self.people[1], self.page, self.people)
        self.assertIn("葬", draft["draft_values"]["burial_text"])

    def test_spouse_columns_do_not_leak_into_subject_fields(self):
        texts = [
            "開寶八年乙亥十月", "十五日生", "淳化五年甲午官至", "中書舍人",
            "間父子被祸漂", "高麗文宗二年戊子", "卒0禮葬于今萬",
            "项縣主山壬坐之原", "故因號杜州曰杜", "杜氏貫杜陵焉",
            "夫人洛陽洪氏丙子", "生庚寅卒0葬于", "公之基附右",
        ]
        person = {"person_id": "p", "source_row_id": "row", "bbox": {"x": 500, "y": 0, "width": 20, "height": 100}}
        row = {"row_id": "row", "columns": [
            {"column_id": None, "text": value,
             "bbox": {"x": 480 - 25 * i, "y": 0, "width": 20, "height": 100}}
            for i, value in enumerate(texts)
        ]}
        draft = extract_person_info_draft(person, {"rows": [row]}, [person])
        values = draft["draft_values"]
        self.assertEqual(values["birth_text"], " / ".join(texts[:2]))
        self.assertEqual(values["office_title"], " / ".join(texts[2:4]))
        self.assertEqual(values["death_text"], " / ".join([texts[5], "卒0"]))
        self.assertEqual(values["burial_text"], " / ".join(["禮葬于今萬", texts[7]]))
        self.assertEqual(values["spouse_text"], " / ".join(texts[10:]))
        self.assertNotIn("courtesy_name_hanja", values)
        self.assertNotIn("pen_name_hanja", values)
        self.assertEqual(get_field_source_columns(draft, "courtesy_name_hanja"), [])
        self.assertEqual(get_field_source_columns(draft, "pen_name_hanja"), [])
        for field, expected in {
            "birth_text": [0, 1], "office_title": [2, 3], "death_text": [5, 6],
            "burial_text": [6, 7], "spouse_text": [10, 11, 12],
        }.items():
            self.assertEqual([source["bbox"]["x"] for source in get_field_source_columns(draft, field)],
                             [row["columns"][i]["bbox"]["x"] for i in expected])

    def test_no_matching_columns_returns_empty_draft(self):
        person = {"person_id": "P3", "source_row_id": "missing", "bbox": {"x": 1, "y": 1, "width": 20, "height": 30}}
        draft = extract_person_info_draft(person, self.page, [person])
        self.assertEqual(draft["draft_values"], {})
        self.assertFalse(draft["source_record_ocr_text"])


if __name__ == "__main__":
    unittest.main()
