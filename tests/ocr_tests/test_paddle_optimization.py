"""OCR inference and batching tests."""
import unittest
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np
import ocr.jokbo_ocr as pipeline
from ocr.storage import load_ocr_output

from ocr.jokbo_ocr import (
    find_matching_ocr_column,
    run_name_ocr_variants,
)


class FakeResult:
    def __init__(self, payload):
        self.json = {"res": payload}


class CountingPaddle:
    def __init__(self, text="子之逢", score=0.96):
        self.calls = 0
        self.text = text
        self.score = score

    def predict(self, image):
        self.calls += 1
        return [FakeResult({
            "rec_texts": [self.text],
            "rec_scores": np.asarray([self.score]),
            "rec_polys": np.asarray([[[2, 2], [24, 2], [24, 80], [2, 80]]]),
        })]


class PaddleOptimizationTests(unittest.TestCase):
    def test_title_margin_requires_right_side_title_evidence(self):
        box = {"x": 50, "width": 600}
        self.assertEqual(pipeline.page_title_margin([
            {"text": "杜陵杜氏", "bbox": {"x": 615}}], box), 45)
        self.assertEqual(pipeline.page_title_margin([
            {"text": "子成林", "bbox": {"x": 615}}], box), 0)
        self.assertEqual(pipeline.page_title_margin([
            {"text": "杜氏", "bbox": {"x": 300}}], box), 0)
        # Rectification can move the title token's left edge just outside the
        # strip while its center remains inside it.
        self.assertEqual(pipeline.page_title_margin([
            {"text": "杜陵杜氏", "bbox": {"x": 604, "width": 30}}], box), 45)

    def test_split_name_columns_are_reused_in_vertical_order(self):
        columns = [
            {"column_id": "c2", "text": "瑛", "mean_confidence": 90,
             "bbox": {"x": 605, "y": 291, "width": 27, "height": 35}},
            {"column_id": "c1", "text": "子", "mean_confidence": 95,
             "bbox": {"x": 607, "y": 245, "width": 25, "height": 22}},
            {"column_id": "c3", "text": "下四", "mean_confidence": 95,
             "bbox": {"x": 606, "y": 380, "width": 25, "height": 22}},
        ]
        matched = find_matching_ocr_column({"bbox": {"x": 606, "y": 249, "width": 26, "height": 75}}, columns)
        self.assertEqual(matched["text"], "子\n瑛")
        self.assertEqual(matched["source_column_ids"], ["c1", "c2"])

    def test_missing_column_fallback_preserves_offsets_and_does_not_repeat_covered_ocr(self):
        image = np.full((100, 100, 3), 255, dtype=np.uint8)
        existing = {"text": "已讀", "left": 10, "top": 5, "width": 14, "height": 80,
                    "block_num": 1, "par_num": 1, "line_num": 1, "word_num": 1, "confidence": 90}
        extra = {**existing, "text": "出生", "left": 11, "top": 13, "width": 12}
        args = SimpleNamespace(scale=3, preprocess="clahe")
        with patch.object(pipeline, "extract_text_and_confidence", return_value=("出生", 90, image, [extra])) as ocr:
            tokens, calls = pipeline.recover_missing_column_tokens(image, [(10, 24), (50, 64)], [existing], args, object())
        self.assertEqual(calls, 1)
        self.assertEqual(ocr.call_count, 1)
        self.assertEqual((tokens[1]["left"], tokens[1]["top"]), (50, 5))
        self.assertEqual(tokens[1]["block_num"], 2)
        self.assertEqual(tokens[0], existing)

        extra["top"] = 7
        with patch.object(pipeline, "extract_text_and_confidence", return_value=("出生", 90, image, [extra])):
            clipped, _ = pipeline.recover_missing_column_tokens(image, [(50, 64)], [], args, object())
        self.assertEqual(clipped[0]["text"], "出生")
        self.assertEqual(clipped[0]["top"], 0)
        self.assertEqual(clipped[0]["height"], 79)

    def test_successive_ocr_batches_keep_unprocessed_pages_and_review_state(self):
        module = pipeline
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ocr"
            output.mkdir()

            def run_batch(names, revision="first", failure=False):
                def page_result(path, _args, _output, _backend):
                    if failure:
                        raise RuntimeError("OCR failed")
                    name = path.name
                    return {
                        "source_image": str(path), "rows": [{"columns": []}],
                        "people_candidates": [{"person_id": f"{path.stem}_P0001", "source_page": name,
                                               "name_hanja_candidate": revision}],
                        "relationship_candidates": [{"relationship_id": "R0001"}],
                        "paddle_metrics": {}, "elapsed_seconds": 0.1,
                    }

                with patch.object(sys, "argv", ["jokbo_ocr.py", *names, "--output", str(output)]), \
                     patch("ocr.jokbo_ocr.collect_images", return_value=[Path(name) for name in names]), \
                     patch("ocr.jokbo_ocr.initialize_paddle_ocr", return_value=object()), \
                     patch("ocr.jokbo_ocr.ocr_one_image", side_effect=page_result):
                    return module.main()

            self.assertEqual(run_batch(["001.jpg", "002.jpg"]), 0)
            review_state = b'{"people_updates":{"001_P0001":{"notes":"reviewed"}}}'
            (output / "review_state.json").write_bytes(review_state)
            self.assertEqual(run_batch(["003.jpg", "004.jpg"]), 0)
            pages, people, relationships, _ = load_ocr_output(output)
            self.assertEqual([Path(page["source_image"]).name for page in pages],
                             ["001.jpg", "002.jpg", "003.jpg", "004.jpg"])
            self.assertEqual(len(people), 4)
            self.assertEqual(len(relationships), 4)
            for name in ("ocr_results.json", "people_candidates.json", "relationship_candidates.json"):
                self.assertFalse((output / name).exists())
            self.assertEqual(sorted(path.name for path in (output / "001").glob("*.json")), ["page.json"])
            self.assertEqual((output / "review_state.json").read_bytes(), review_state)

            self.assertEqual(run_batch(["002.jpg"], revision="updated"), 0)
            _, people, _, _ = load_ocr_output(output)
            self.assertEqual(len(people), 4)
            self.assertEqual(next(item for item in people if item["source_page"] == "002.jpg")
                             ["name_hanja_candidate"], "updated")
            self.assertEqual((output / "review_state.json").read_bytes(), review_state)

            page_before_failure = (output / "002/page.json").read_bytes()
            self.assertEqual(run_batch(["005.jpg"], failure=True), 1)
            self.assertEqual((output / "002/page.json").read_bytes(), page_before_failure)
            self.assertFalse((output / "005/page.json").exists())

            (output / "ocr_results.json").write_text("{invalid json", encoding="utf-8")
            self.assertEqual(run_batch(["006.jpg"]), 2)
            self.assertEqual((output / "ocr_results.json").read_text(), "{invalid json")
            self.assertEqual((output / "review_state.json").read_bytes(), review_state)

    def test_cli_defaults_to_paddle_and_writes_existing_output_schema(self):
        # Other tests reload this module; patch and call the same live module.
        module = pipeline
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ocr"
            with patch.object(sys, "argv", ["jokbo_ocr.py", "sample.jpg", "--output", str(output)]):
                args = module.parse_args()
                self.assertEqual(args.paddle_lang, "chinese_cht")
                self.assertFalse(hasattr(args, "ocr_engine"))
                result = {
                    "source_image": "sample.jpg", "rows": [], "people_candidates": [],
                    "relationship_candidates": [], "paddle_metrics": {}, "elapsed_seconds": 0.1,
                    "ocr_engine": "paddleocr", "ocr_language": args.paddle_lang,
                }
                with patch("ocr.jokbo_ocr.collect_images", return_value=[Path("sample.jpg")]), \
                     patch("ocr.jokbo_ocr.initialize_paddle_ocr", return_value=object()), \
                     patch("ocr.jokbo_ocr.ocr_one_image", return_value=result) as recognize:
                    self.assertEqual(module.main(), 0)
                self.assertEqual(recognize.call_args.args[2], output)
                self.assertEqual(json.loads((output / "sample/page.json").read_text())["ocr_engine"], "paddleocr")
                self.assertFalse((output / "paddleocr_metrics_pages.csv").exists())
                self.assertFalse((output / "people_candidates.csv").exists())
                self.assertFalse((output / "relationship_candidates.csv").exists())

    def test_column_match_requires_vertical_overlap(self):
        geometry = {"bbox": {"x": 100, "y": 200, "width": 25, "height": 90}, "center_x": 112.5}
        same_x_wrong_y = {
            "bbox": {"x": 100, "y": 20, "width": 25, "height": 70},
            "text": "正文", "mean_confidence": 98,
        }
        correct = {
            "bbox": {"x": 101, "y": 210, "width": 24, "height": 75},
            "text": "子之逢", "mean_confidence": 96,
        }
        self.assertIs(find_matching_ocr_column(geometry, [same_x_wrong_y, correct]), correct)
        self.assertIsNone(find_matching_ocr_column(geometry, [same_x_wrong_y]))

    def test_paddle_name_fallback_stops_after_first_good_variant(self):
        image = np.full((300, 160, 3), 255, dtype=np.uint8)
        cv2.putText(image, "X", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        backend = CountingPaddle()
        with patch("ocr.jokbo_ocr.cv2.createCLAHE", wraps=cv2.createCLAHE):
            text, variants, crop = run_name_ocr_variants(
                image, {"x": 30, "y": 30, "width": 40, "height": 80},
                paddle_ocr=backend,
                paddle_min_confidence=70,
            )
        self.assertEqual(text, "子之逢")
        self.assertEqual(backend.calls, 1)
        self.assertEqual(len(variants), 1)
        self.assertGreater(crop.size, 0)


if __name__ == "__main__":
    unittest.main()
