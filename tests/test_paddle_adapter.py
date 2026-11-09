import unittest

import numpy as np

from jokbo_ocr import run_paddle_ocr_image, clean_hanzi_text


class FakeResult:
    def __init__(self, payload):
        self.json = {"res": payload}


class FakePaddleOCR:
    def predict(self, image):
        # Paddle-style polygon output. First polygon is farther left.
        return [FakeResult({
            "rec_texts": ["子之逢", "杜慶章"],
            "rec_scores": np.asarray([0.91, 0.88]),
            "rec_polys": np.asarray([
                [[20, 10], [40, 10], [40, 90], [20, 90]],
                [[100, 10], [120, 10], [120, 90], [100, 90]],
            ]),
        })]


class PaddleAdapterTests(unittest.TestCase):
    def test_vertical_order_is_right_to_left_and_boxes_are_rescaled(self):
        image = np.zeros((300, 450, 3), dtype=np.uint8)
        text, confidence, tokens = run_paddle_ocr_image(
            FakePaddleOCR(), image, coordinate_scale=3.0, reading_order="vertical"
        )
        self.assertEqual(text, "杜慶章\n子之逢")
        self.assertAlmostEqual(confidence, 89.5, places=1)
        self.assertEqual(tokens[0]["left"], 33)
        self.assertEqual(tokens[0]["width"], 7)
        self.assertEqual(clean_hanzi_text(text), "杜慶章子之逢")

    def test_horizontal_order_is_left_to_right(self):
        image = np.zeros((300, 450, 3), dtype=np.uint8)
        text, _, _ = run_paddle_ocr_image(
            FakePaddleOCR(), image, coordinate_scale=1.0, reading_order="horizontal"
        )
        self.assertEqual(text, "子之逢\n杜慶章")


if __name__ == "__main__":
    unittest.main()
