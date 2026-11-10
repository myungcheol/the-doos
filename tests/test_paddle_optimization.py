import unittest
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from jokbo_ocr import (
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
    def test_cli_defaults_to_paddle_and_writes_existing_output_schema(self):
        # Other tests reload this module; patch and call the same live module.
        module = sys.modules["jokbo_ocr"]
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
                with patch("jokbo_ocr.collect_images", return_value=[Path("sample.jpg")]), \
                     patch("jokbo_ocr.initialize_paddle_ocr", return_value=object()), \
                     patch("jokbo_ocr.ocr_one_image", return_value=result) as recognize:
                    self.assertEqual(module.main(), 0)
                self.assertEqual(recognize.call_args.args[2], output)
                self.assertEqual(json.loads((output / "ocr_results.json").read_text())[0]["ocr_engine"], "paddleocr")
                self.assertTrue((output / "paddleocr_metrics_pages.csv").exists())

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
        with patch("jokbo_ocr.cv2.createCLAHE", wraps=cv2.createCLAHE):
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
