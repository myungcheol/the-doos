import json
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from ocr_storage import load_ocr_output, save_page_result


class OcrStorageTests(unittest.TestCase):
    def page(self, name="001.png", text="原文"):
        return {"source_image": name, "table_roi": {"x": 17, "y": 23, "width": 100, "height": 80},
                "rows": [{"row_id": "row1", "columns": [{"text": text,
                          "bbox": {"x": 20, "y": 30, "width": 10, "height": 40}}]}],
                "people_candidates": [{"person_id": "001_P0001", "source_page": name,
                                       "raw_name_ocr": "子甲", "name_hanja_candidate": text}],
                "relationship_candidates": []}

    def test_page_supersedes_old_copies_and_keeps_metadata_without_modifying_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.page(text="舊")
            legacy = json.dumps([old], ensure_ascii=False).encode()
            (root / "ocr_results.json").write_bytes(legacy)
            (root / "people_candidates.json").write_text(json.dumps(old["people_candidates"]))
            save_page_result(root, self.page(text="新"))
            pages, people, _, warnings = load_ocr_output(root)
            self.assertEqual(len(pages), 1)
            self.assertEqual(people[0]["name_hanja_candidate"], "新")
            self.assertEqual(people[0]["raw_name_ocr"], "子甲")
            self.assertEqual(pages[0]["table_roi"]["x"], 17)
            self.assertEqual(pages[0]["rows"][0]["columns"][0]["bbox"]["y"], 30)
            self.assertFalse(warnings)
            self.assertEqual((root / "ocr_results.json").read_bytes(), legacy)

    def test_failed_replace_preserves_the_previous_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_page_result(root, self.page())
            before = (root / "001/page.json").read_bytes()
            with patch("ocr_storage.os.replace", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    save_page_result(root, self.page(text="新"))
            self.assertEqual((root / "001/page.json").read_bytes(), before)
            self.assertEqual(list((root / "001").glob("*.tmp")), [])
            invalid = self.page()
            invalid["people_candidates"][0]["source_page"] = "different.png"
            with self.assertRaises(ValueError):
                save_page_result(root, invalid)
            self.assertEqual((root / "001/page.json").read_bytes(), before)

    def test_mixed_new_and_legacy_orphan_pages_are_loaded_without_reocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "001.png"
            image.touch()
            folder = root / "001"
            folder.mkdir()
            old = self.page()
            (folder / "rows.json").write_text(json.dumps(old["rows"]))
            (folder / "people_candidates.json").write_text(json.dumps(old["people_candidates"]))
            new = self.page("002.png")
            new["source_image"] = str(root / "002.png")
            new["people_candidates"][0]["person_id"] = "002_P0001"
            save_page_result(root, new)
            pages, people, _, warnings = load_ocr_output(root)
            self.assertEqual([Path(page["source_image"]).name for page in pages], ["001.png", "002.png"])
            self.assertEqual(len(people), 2)
            self.assertFalse(warnings)
            self.assertFalse((root / "ocr_results.json").exists())

    def test_real_pipeline_writes_one_page_json_with_fake_inference(self):
        class EmptyPaddle:
            def predict(self, image):
                return []

        module = importlib.import_module("jokbo_ocr")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan = root / "001.png"
            cv2.imwrite(str(scan), np.full((120, 100, 3), 255, dtype=np.uint8))
            output = root / "output"
            with patch.object(sys, "argv", ["jokbo_ocr.py", str(scan), "--output", str(output),
                                           "--rows", "1", "--no-auto-roi"]), \
                 patch("jokbo_ocr.initialize_paddle_ocr", return_value=EmptyPaddle()):
                self.assertEqual(module.main(), 0)
            self.assertEqual([path.relative_to(output).as_posix() for path in output.rglob("*.json")],
                             ["001/page.json"])
            self.assertEqual(load_ocr_output(output)[0][0]["image_size"], {"width": 100, "height": 120})


if __name__ == "__main__":
    unittest.main()
