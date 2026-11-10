import json
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QImage, QInputMethodEvent, QRawFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from desktop_review import (HistoricalDateDialog, ReviewComboBox, ReviewWindow, RegionOcrWorker, configure_application,
                                crop_selected_region, restore_qt_environment)
    from review_extensions import make_continuation
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 데스크톱 의존성이 설치되지 않음")
class DesktopReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.font_loaded = configure_application(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        image_path = self.root / "sample.png"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xffffffff)
        self.assertTrue(image.save(str(image_path)))
        self.write("ocr_results.json", [{"source_page": "sample.png", "source_image": str(image_path), "rows": []}])
        self.write("people_candidates.json", [
            {"person_id": "p1", "source_page": "sample.png", "bbox": {"x": 10, "y": 10, "width": 10, "height": 10}, "raw_name_ocr": "子甲", "name_hanja_candidate": "子甲"},
            {"person_id": "p2", "source_page": "sample.png", "bbox": {"x": 30, "y": 30, "width": 10, "height": 10}, "raw_name_ocr": "乙", "name_hanja_candidate": "乙"},
        ])
        self.write("relationship_candidates.json", [])
        self.write("review_state.json", {"people_updates": {"p1": {"notes": "기존 메모", "spouses": [{"type": "concubine", "name_and_record": "기록"}]}}, "custom": "보존"})
        self.window = ReviewWindow(str(self.root))

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.temp.cleanup()

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_first_render_and_save_preserve_state(self):
        self.assertIsNone(self.window.selected_id)
        self.window.select_person_id("p1")
        self.window.inputs["transcribed_name_hanja"].setText("子甲")
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        update = state["people_updates"]["p1"]
        self.assertEqual((update["transcribed_name_hanja"], update["sex_marker"]), ("甲", "子"))
        self.assertEqual(update["notes"], "기존 메모")
        self.assertEqual(update["spouses"][0]["type"], "concubine")
        self.assertEqual(state["custom"], "보존")
        self.assertEqual(len(state["person_uid_map"]), 2)
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        self.assertEqual(exports[0]["raw_data"]["name_ocr"]["raw_text"], "子甲")

    def test_birth_date_draft_saved_without_changing_original_text(self):
        self.window.select_person_id("p1")
        source = "開寶八年乙亥十月十五日生"
        self.window.inputs["birth_text"].setText(source)
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        update = state["people_updates"]["p1"]
        self.assertEqual(update["birth_text"], source)
        self.assertEqual(update["birth_solar"]["start"], "0975-11-20")
        self.assertEqual(update["birth_solar"]["source_text"], source)
        self.assertEqual(update["birth_date"]["sexagenary_year"], "乙亥")
        exported = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(exported["reviewed_data"]["birth_solar"], update["birth_solar"])
        with (self.root / "reviewed_people.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(json.loads(row["birth_solar"])["start"], "0975-11-20")
        self.window.inputs["birth_text"].setText("수정된 원문")
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["people_updates"]["p1"]["birth_solar"])

    def test_split_ocr_date_components_are_visible_and_saved_independently(self):
        self.window.select_person_id("p1")
        self.window.inputs["birth_text"].setText("高麗穆宗八年乙 / 生")
        self.window.inputs["death_text"].setText("軍壬寅九月二十 / 一日卒")
        self.window.refresh_date_parts("birth")
        self.window.refresh_date_parts("death")
        self.assertEqual(self.window.date_part_widgets["birth"]["sexagenary_year"].text(), "乙巳")
        self.assertIn("OCR 원문 乙", self.window.date_part_notes["birth"].text())
        self.assertEqual(self.window.date_part_widgets["death"]["day"].text(), "21")
        self.window.save_person()
        update = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))["people_updates"]["p1"]
        self.assertEqual(update["birth_date"]["sexagenary_ocr"], "乙")
        self.assertEqual(update["birth_date"]["ce_year"], 1005)
        self.assertEqual(update["birth_solar"]["precision"], "year")
        self.assertEqual((update["death_date"]["sexagenary_year"], update["death_date"]["month"],
                          update["death_date"]["day"]), ("壬寅", 9, 21))
        self.assertIsNone(update["death_solar"])

    def test_ocr_date_draft_reaches_export_without_changing_review_state_text(self):
        image_path = str(self.root / "sample.png")
        self.write("ocr_results.json", [{"source_page": "sample.png", "source_image": image_path,
                                         "rows": [{"row_id": "r", "columns": [
                                             {"column_id": "c1", "text": "高麗穆宗八年乙",
                                              "bbox": {"x": 3, "y": 10, "width": 3, "height": 40}},
                                             {"column_id": "c2", "text": "生",
                                              "bbox": {"x": 1, "y": 10, "width": 1, "height": 40}},
                                         ]}]}])
        people = json.loads((self.root / "people_candidates.json").read_text(encoding="utf-8"))
        people[0]["source_row_id"] = "r"
        self.write("people_candidates.json", people)
        self.window.close()
        self.window = ReviewWindow(str(self.root))
        self.assertTrue(self.window.persist())
        exported = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(exported["reviewed_data"]["birth_date"]["sexagenary_year"], "乙巳")
        self.assertEqual(exported["reviewed_data"]["birth_date"]["review_status"], "needs_review")
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertNotIn("birth_text", state["people_updates"]["p1"])

    def test_date_dialog_looks_up_king_year_and_partial_lunar_month(self):
        dialog = HistoricalDateDialog("문종 이년 이월", "birth")
        dialog.country.setCurrentIndex(dialog.country.findData("고려"))
        dialog.populate_reigns()
        dialog.reign.setCurrentIndex(next(i for i in range(dialog.reign.count())
                                          if dialog.reign.itemData(i).name == "문종 文宗"))
        dialog.regnal_year.setText("二")
        self.assertEqual(dialog.ce_year.text(), "1048")
        dialog.month.setText("二")
        dialog.convert()
        self.assertEqual(dialog.result_value["precision"], "month")
        self.assertEqual(dialog.result_value["start"], "1048-03-17")

    def test_date_dialog_allows_unlisted_era_with_explicit_year_mapping(self):
        dialog = HistoricalDateDialog("미등록 연호 원년", "death")
        dialog.reign.setCurrentIndex(dialog.reign.findData("custom"))
        dialog.custom_name.setText("미등록 연호")
        dialog.custom_first.setText("1048")
        dialog.custom_last.setText("1052")
        dialog.regnal_year.setText("二")
        self.assertEqual(dialog.ce_year.text(), "1049")
        dialog.convert()
        self.assertEqual(dialog.result_value["lunar"]["year"], 1049)
        self.assertEqual(dialog.result_value["reference"]["mapping_source"], "reviewer")

    def test_spouse_ocr_draft_is_visible_and_unverified(self):
        self.write("ocr_results.json", [{"source_page": "sample.png",
                                         "source_image": str(self.root / "sample.png"),
                                         "rows": [{"row_id": "r2", "columns": [
                                             {"column_id": "c1", "text": "夫人洪氏",
                                              "bbox": {"x": 5, "y": 30, "width": 20, "height": 40}},
                                             {"column_id": "c2", "text": "庚寅卒",
                                              "bbox": {"x": 1, "y": 30, "width": 3, "height": 40}},
                                         ]}]}])
        people = json.loads((self.root / "people_candidates.json").read_text(encoding="utf-8"))
        people[1]["source_row_id"] = "r2"
        self.write("people_candidates.json", people)
        self.window.close()
        self.window = ReviewWindow(str(self.root))
        self.window.select_person_id("p2")
        self.assertIn("夫人洪氏", self.window.inputs["spouse_text"].toPlainText())
        self.assertEqual(json.loads(self.window.partners.toPlainText())[0]["type"], "other")
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        update = state["people_updates"]["p2"]
        self.assertTrue(update["spouse_text"].startswith("夫人洪氏"))
        self.assertEqual(update["spouses"][0]["review_status"], "needs_review")

    def test_linked_record_prefills_matching_fields_without_losing_reviewed_text(self):
        row = {"row_id": "next_row", "row_number": 1, "columns": [
            {"column_id": "death", "text": "某年卒", "bbox": {"x": 80, "y": 10, "width": 12, "height": 35}},
            {"column_id": "burial", "text": "禮葬于某原", "bbox": {"x": 60, "y": 10, "width": 12, "height": 35}},
            {"column_id": "spouse", "text": "夫人某氏", "bbox": {"x": 40, "y": 10, "width": 12, "height": 35}},
        ]}
        state = self.window.state
        state.setdefault("people_updates", {}).setdefault("p2", {})["death_text"] = "검수한 사망"
        state["people_updates"]["p2"]["information_review_status"] = "confirmed"
        target = next(person for person in self.window.base_people if person["person_id"] == "p2")
        link = make_continuation({"source_image": "next.png", "rows": [row]}, row,
                                 row["columns"], target, state)
        state.setdefault("continuation_links", []).append(link)
        self.write("review_state.json", state)
        self.window.close()
        self.window = ReviewWindow(str(self.root))
        self.window.select_person_id("p2")
        self.assertEqual(self.window.inputs["death_text"].text(), "검수한 사망 / 某年卒")
        self.assertEqual(self.window.inputs["burial_text"].text(), "禮葬于某原")
        self.assertIn("夫人某氏", self.window.inputs["spouse_text"].toPlainText())
        self.assertEqual(json.loads(self.window.partners.toPlainText())[0]["type"], "other")
        self.assertIn("사망 정보 초안", self.window.attached_records.toPlainText())
        self.assertFalse(self.window.info_confirmed.isChecked())
        self.window.save_person()
        self.window.select_person_id("p1")
        self.window.select_person_id("p2")
        self.assertEqual(self.window.inputs["death_text"].text().count("某年卒"), 1)
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        person = next(p for p in exports if p["person_id"] == "p2")
        evidence = person["raw_data"]["field_ocr"]["death_text"]["continuations"][0]
        self.assertEqual(evidence["columns"][0]["bbox"], row["columns"][0]["bbox"])
        self.assertEqual(person["reviewed_data"]["information_review_status"], "needs_review")
        self.window.inputs["death_text"].setText("검수한 사망")
        self.window.save_person()
        self.window.select_person_id("p1")
        self.window.select_person_id("p2")
        self.assertEqual(self.window.inputs["death_text"].text(), "검수한 사망")

    def test_bundled_font_covers_korean_and_hanja(self):
        self.assertTrue(self.font_loaded)
        font = QRawFont.fromFont(self.app.font())
        for character in "족보검수子女杜慶寧":
            self.assertTrue(font.supportsCharacter(character), character)

    def test_search_and_selection_keep_page_numbers(self):
        self.window.search.setText("p2")
        self.assertTrue(self.window.person_results.item(0).isHidden())
        item = self.window.person_results.item(1)
        self.assertFalse(item.isHidden())
        self.window.person_results.setCurrentItem(item)
        self.assertEqual(self.window.selected_id, "p2")
        self.assertTrue(item.text().strip().startswith("2."))

    def test_focus_buttons_select_without_popup(self):
        self.window.show()
        self.window.select_person_id("p1")
        QTest.mouseClick(self.window.focus.group.button(1), Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.window.focus.currentData(), "name")
        self.assertIsNone(QApplication.activePopupWidget())

    def test_combo_box_closes_its_popup_after_user_selection(self):
        combo = ReviewComboBox()
        combo.addItems(["첫 값", "둘째 값"])
        with patch.object(combo, "hidePopup") as close_popup:
            combo.activated.emit(1)
            self.app.processEvents()
        close_popup.assert_called_once()
        self.assertTrue(all(isinstance(widget, ReviewComboBox) for widget in (
            self.window.pages, self.window.people_list, self.window.marker, self.window.gender,
            self.window.name_status, self.window.orphan_row, self.window.continuation_target,
        )))

    def test_korean_input_method_commit(self):
        self.window.select_person_id("p1")
        field = self.window.inputs["transcribed_name_hanja"]
        field.clear()
        event = QInputMethodEvent("한", [])
        QApplication.sendEvent(field, event)
        commit = QInputMethodEvent()
        commit.setCommitString("한글")
        QApplication.sendEvent(field, commit)
        self.assertEqual(field.text(), "한글")
        self.assertTrue(self.window.dirty)

    def test_opencv_qt_overrides_restore_explicit_settings(self):
        environment = {"QT_QPA_PLATFORM_PLUGIN_PATH": "/opencv/qt/plugins", "QT_QPA_FONTDIR": "/opencv/qt/fonts"}
        restore_qt_environment({"QT_QPA_PLATFORM_PLUGIN_PATH": "/custom/plugins", "QT_QPA_FONTDIR": None}, environment, "/opencv")
        self.assertEqual(environment, {"QT_QPA_PLATFORM_PLUGIN_PATH": "/custom/plugins"})

    def test_other_qt_settings_are_not_modified(self):
        environment = {"QT_QPA_PLATFORM_PLUGIN_PATH": "/custom/plugins"}
        restore_qt_environment({}, environment, "/opencv")
        self.assertEqual(environment["QT_QPA_PLATFORM_PLUGIN_PATH"], "/custom/plugins")

    def test_gender_is_separate_from_marker_and_persisted(self):
        self.window.select_person_id("p1")
        self.assertEqual(self.window.marker.currentData(), "子")
        self.assertEqual(self.window.gender.currentData(), "male")
        self.window.gender.setCurrentIndex(self.window.gender.findData("female"))
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["people_updates"]["p1"]["gender"], "female")
        self.assertEqual(state["people_updates"]["p1"]["sex_marker"], "子")
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        self.assertEqual(exports[0]["reviewed_data"]["gender"], "female")
        self.assertEqual(exports[0]["raw_data"]["name_ocr"]["raw_text"], "子甲")

    def test_unknown_gender_does_not_reinfer_from_marker(self):
        self.window.select_person_id("p1")
        self.window.gender.setCurrentIndex(self.window.gender.findData("unknown"))
        self.window.save_person()
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        self.assertEqual(exports[0]["reviewed_data"]["gender"], "unknown")

    def test_import_attach_detach_and_reload_keep_original_ocr(self):
        original = (self.root / "ocr_results.json").read_bytes()
        previous_dir = self.root / "previous"
        previous_dir.mkdir()
        previous_image = self.root / "000.png"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xffffffff)
        image.save(str(previous_image))
        rows_file = previous_dir / "rows.json"
        rows_file.write_text(json.dumps([{"row_id": "000_row_01", "row_number": 1, "columns": []}]), encoding="utf-8")
        (previous_dir / "people_candidates.json").write_text(json.dumps([
            {"person_id": "p0", "source_page": "000.png", "source_row_id": "000_row_01",
             "name_hanja_candidate": "甲", "bbox": {"x": 30, "y": 20, "width": 10, "height": 20}}
        ]), encoding="utf-8")
        (previous_dir / "relationship_candidates.json").write_text(json.dumps([
            {"relationship_id": "old-format", "parent_candidate_id": "p0", "child_candidate_id": "p0", "review_status": "rejected"}
        ]), encoding="utf-8")
        self.window.page["rows"] = [{"row_id": "sample_row_01", "row_number": 1,
                                     "columns": [{"column_id": "source", "text": "續記原文",
                                                  "bbox": {"x": 60, "y": 10, "width": 15, "height": 50}}]}]
        self.assertTrue(self.window.import_page_data(rows_file, previous_image))
        self.assertEqual(self.window.base_rels[0]["source_page"], "000.png")
        self.window.tabs.setCurrentIndex(2)
        self.window.orphan_list.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(self.window.view.sources[0]["bbox"]["x"], 60)
        self.window.attach_continuation()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["continuation_links"][0]["target_person_id"], "p0")
        self.assertEqual(len(state["person_uid_map"]), 3)
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        person = next(p for p in exports if p["person_id"] == "p0")
        self.assertEqual(person["raw_data"]["record_ocr"]["continuations"][0]["text"], "續記原文")
        self.assertEqual((self.root / "ocr_results.json").read_bytes(), original)
        self.window.open_folder(self.root)
        self.assertIn("p0", [p["person_id"] for p in self.window.base_people])
        self.window.pages.setCurrentIndex(self.window.pages.findText("sample.png"))
        self.assertEqual(self.window.continuation_list.count(), 1)
        self.window.continuation_list.setCurrentRow(0)
        self.window.detach_continuation()
        exports = json.loads((self.root / "reviewed_people.json").read_text(encoding="utf-8"))
        self.assertNotIn("continuations", next(p for p in exports if p["person_id"] == "p0")["raw_data"]["record_ocr"])
        self.assertEqual((self.root / "ocr_results.json").read_bytes(), original)

    def test_sibling_page_is_discovered_without_dialog_or_state_change(self):
        original_state = (self.root / "review_state.json").read_bytes()
        first = self.root / "001.png"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xffffffff)
        self.assertTrue(image.save(str(first)))
        folder = self.root / "001"
        folder.mkdir()
        (folder / "rows.json").write_text(json.dumps([{"row_id": "001_row_01", "row_number": 1,
                                                        "columns": []}]), encoding="utf-8")
        (folder / "people_candidates.json").write_text(json.dumps([{"person_id": "first_person",
            "source_page": "001.png", "source_row_id": "001_row_01", "name_hanja_candidate": "甲",
            "bbox": {"x": 20, "y": 20, "width": 10, "height": 20}}]), encoding="utf-8")
        (folder / "relationship_candidates.json").write_text("[]", encoding="utf-8")
        self.window.import_previous_page()
        self.assertEqual([self.window.pages.itemText(i) for i in range(self.window.pages.count())],
                         ["001.png", "sample.png"])
        self.assertEqual(self.window.page_name, "sample.png")
        self.assertEqual(self.window.previous_scan_title.text(), "이전 페이지 · 001.png")
        self.assertEqual([person["person_id"] for person in self.window.previous_view.people], ["first_person"])
        self.window.pages.setCurrentIndex(0)
        self.assertEqual(self.window.page_people[0]["person_id"], "first_person")
        self.assertEqual(self.window.previous_scan_title.text(), "이전 페이지 없음")
        self.assertEqual((self.root / "review_state.json").read_bytes(), original_state)

    def test_orphan_region_preview_and_attachment_preserve_columns(self):
        self.window.page["rows"] = [{"row_id": "sample_row_01", "row_number": 1,
            "columns": [{"column_id": "a", "text": "甲", "bbox": {"x": 70, "y": 10, "width": 15, "height": 40}},
                        {"column_id": "b", "text": "乙", "bbox": {"x": 50, "y": 10, "width": 15, "height": 40}}]}]
        self.window.refresh_orphan_rows()
        self.assertEqual(self.window.orphan_list.count(), 1)
        item = self.window.orphan_list.item(0)
        self.assertIn("x 50–85", item.text())
        self.assertIn("甲 乙", item.text())
        self.window.orphan_list.setCurrentItem(item)
        self.assertEqual(self.window.orphan_preview.toPlainText(), "甲\n乙")
        self.window.tabs.setCurrentIndex(2)
        self.assertEqual(self.window.view.sources[0]["bbox"], {"x": 50, "y": 10, "width": 35, "height": 40})
        item.setCheckState(Qt.CheckState.Checked)
        self.assertEqual([c["column_id"] for c in self.window.checked_orphan_columns()], ["a", "b"])

    def test_region_crop_uses_original_coordinates_with_and_without_roi_offset(self):
        image = np.arange(100 * 100, dtype=np.uint8).reshape(100, 100)
        box = {"x": 31, "y": 42, "width": 8, "height": 9}
        np.testing.assert_array_equal(crop_selected_region(image, box, (0, 0)), image[42:51, 31:39])
        roi = image[30:80, 20:70]
        np.testing.assert_array_equal(crop_selected_region(roi, box, (20, 30)), image[42:51, 31:39])

    def test_hidden_boxes_allow_drag_selection_and_candidates_appear_in_panel(self):
        original_state = (self.root / "review_state.json").read_bytes()
        self.window.show()
        self.window.hide_boxes.setChecked(True)
        self.window.select_ocr_region.setChecked(True)
        self.assertFalse(self.window.view.overlays_visible)
        self.assertTrue(self.window.view.region_mode)
        viewport = self.window.view.viewport()
        start = self.window.view.mapFromScene(10, 12)
        end = self.window.view.mapFromScene(40, 48)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, pos=end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(self.window.tabs.currentIndex(), 3)
        self.assertEqual(self.window.region_page, self.window.page)
        self.assertGreater(self.window.region_bbox["width"], 0)
        self.assertTrue(self.window.run_region_ocr_button.isEnabled())
        variants = [
            {"hanja_text": "甲乙", "mean_confidence": 60, "variant": "원본"},
            {"hanja_text": "甲乙", "mean_confidence": 80, "variant": "대비"},
            {"hanja_text": "丙丁", "mean_confidence": 50, "variant": "확대"},
        ]
        with patch("jokbo_ocr.initialize_paddle_ocr", return_value=object()), patch(
            "jokbo_ocr.run_name_ocr_variants", return_value=("甲乙", variants, None)
        ):
            QTest.mouseClick(self.window.run_region_ocr_button, Qt.MouseButton.LeftButton)
            for _ in range(50):
                self.app.processEvents()
                if self.window.region_candidates.count() == 2:
                    break
                QTest.qWait(10)
        self.assertEqual(self.window.region_candidates.count(), 2)
        self.assertIn("甲乙", self.window.region_candidates.item(0).text())
        self.assertIn("대비", self.window.region_candidates.item(0).text())
        self.window.region_candidates.setCurrentRow(0)
        self.window.copy_region_candidate()
        self.assertEqual(QApplication.clipboard().text(), "甲乙")
        self.assertIsNone(self.window.selected_id)
        self.assertFalse(self.window.dirty)
        self.assertEqual((self.root / "review_state.json").read_bytes(), original_state)

    def test_selected_crop_runs_existing_ocr_variants_without_writing_review_state(self):
        original = (self.root / "review_state.json").read_bytes()
        worker = RegionOcrWorker()
        captured = []
        worker.finished.connect(captured.append)
        crop = np.full((20, 10, 3), 255, dtype=np.uint8)
        with patch("jokbo_ocr.run_name_ocr_variants", return_value=("甲乙", [{"hanja_text": "甲乙"}], crop)) as recognize:
            worker.recognize({"page": "sample.png", "bbox": {"x": 7, "y": 8, "width": 10, "height": 20},
                              "crop": crop, "engine": "tesseract"})
        self.assertEqual(captured[0]["variants"][0]["hanja_text"], "甲乙")
        self.assertEqual(recognize.call_args.kwargs["padding"], 0)
        self.assertEqual(recognize.call_args.kwargs["scale"], 3.0)
        self.assertEqual((self.root / "review_state.json").read_bytes(), original)

    def test_zoom_controls_belong_to_image_panel(self):
        self.assertIs(self.window.scan_tools.parent(), self.window.view.parent())
        self.assertIs(self.window.previous_view.parent(), self.window.view.parent())
        self.assertIs(self.window.image_views.itemAt(0).widget(), self.window.view)
        self.assertIs(self.window.image_views.itemAt(1).widget(), self.window.previous_view)
        before = self.window.view.transform().m11()
        self.window.scale_scans(1.25)
        self.assertAlmostEqual(self.window.view.transform().m11(), before * 1.25)
        self.assertIn(f"현재 {self.window.view.transform().m11() * 100:.0f}%", self.window.zoom_label.text())
        self.assertIn("이전 없음", self.window.zoom_label.text())
        self.window.fit_scans()
        self.assertIn(f"현재 {self.window.view.transform().m11() * 100:.0f}%", self.window.zoom_label.text())

    def test_high_zoom_uses_lanczos_display_without_changing_source_coordinates(self):
        view = self.window.view
        original = self.window.source_image.copy()
        view.resetTransform()
        view.scale(2.72, 2.72)
        view.update_image_quality()
        self.assertEqual(view.image_item.pixmap().width(), view.original_pixmap.width() * 3)
        self.assertAlmostEqual(view.image_item.scale(), 1 / 3)
        mapped = view.image_item.mapToScene(QPointF(30, 45))
        self.assertAlmostEqual(mapped.x(), 10)
        self.assertAlmostEqual(mapped.y(), 15)
        np.testing.assert_array_equal(self.window.source_image, original)

    def test_recovery_persists_unverified_candidate_without_renumbering(self):
        self.window.select_person_id("p1")
        self.window.save_person()
        old_map = dict(self.window.state["person_uid_map"])
        recovered = {"person_id": "new_candidate", "source_page": "sample.png", "source_row_id": "row1",
                     "bbox": {"x": 60, "y": 10, "width": 20, "height": 40}, "raw_name_ocr": "",
                     "review_status": "needs_review"}
        with patch("desktop_review.recover_name_candidates", return_value=[recovered]), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.recover_people()
        self.assertEqual([p["person_id"] for p in self.window.page_people], ["p1", "p2", "new_candidate"])
        self.assertEqual(self.window.selected_id, "new_candidate")
        for key, uid in old_map.items():
            self.assertEqual(self.window.state["person_uid_map"][key], uid)
        self.window.open_folder(self.root)
        self.assertIn("new_candidate", [p["person_id"] for p in self.window.base_people])

    def test_external_state_change_is_not_overwritten(self):
        self.window.select_person_id("p1")
        self.write("review_state.json", {"external": "새 변경"})
        with patch.object(QMessageBox, "warning"):
            self.window.save_person()
        self.assertEqual(json.loads((self.root / "review_state.json").read_text(encoding="utf-8")), {"external": "새 변경"})

    def test_changed_partners_update_legacy_text(self):
        self.window.select_person_id("p1")
        self.window.partners.setPlainText(json.dumps([{"type": "wife", "name_and_record": "새 기록"}], ensure_ascii=False))
        self.window.save_person()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["people_updates"]["p1"]["spouse_text"], "부인: 새 기록")

    def test_manual_relationship_and_duplicate(self):
        self.window.select_person_id("p1")
        self.window.set_parent()
        self.window.select_person_id("p2")
        self.window.add_child()
        with patch.object(QMessageBox, "warning"):
            self.window.add_child()
        state = json.loads((self.root / "review_state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["manual_relationships"]), 1)
        self.assertEqual(state["manual_relationships"][0]["child_candidate_id"], "p2")


if __name__ == "__main__":
    unittest.main()
