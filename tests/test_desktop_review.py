import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QInputMethodEvent, QRawFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from desktop_review import ReviewWindow, configure_application, restore_qt_environment
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

    def test_focus_popup_closes_after_selection(self):
        self.window.show()
        self.window.select_person_id("p1")
        self.window.focus.showPopup()
        self.app.processEvents()
        view = self.window.focus.view()
        index = view.model().index(1, 0)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
        self.app.processEvents()
        self.assertEqual(self.window.focus.currentData(), "name")
        self.assertFalse(view.isVisible())

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
