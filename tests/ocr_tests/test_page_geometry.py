"""Table geometry correction and source-coordinate provenance regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from ocr import jokbo_ocr as pipeline
from ocr.page_geometry import (correct_page_geometry, estimate_skew, layout_evidence,
                               map_evidence, transform_box, transform_points)
from ocr.refresh_relationships import refreshed_relationships
from review.core import get_page_image
from review.extensions import recover_name_candidates
from review.extensions import orphan_columns
from review.data_model import build_raw_data
from review.person_info import extract_person_info_draft


def table_image():
    image = np.full((800, 650, 3), 255, np.uint8)
    cv2.rectangle(image, (50, 50), (600, 750), (0, 0, 0), 2)
    for y in range(150, 750, 100):
        cv2.line(image, (50, y), (600, y), (0, 0, 0), 2)
    return image


class PageGeometryTests(unittest.TestCase):
    def test_positive_negative_rotation_and_no_clipped_page_corners(self):
        image = table_image()
        for angle in (2.0, -3.0):
            with self.subTest(angle=angle):
                skewed = cv2.warpAffine(image, cv2.getRotationMatrix2D((325, 400), angle, 1),
                                        (650, 800), borderValue=(255, 255, 255))
                corrected, meta = correct_page_geometry(skewed)
                self.assertEqual(meta["method"], "deskew")
                self.assertAlmostEqual(meta["angle_degrees"], -angle, delta=0.2)
                self.assertAlmostEqual(estimate_skew(corrected)[0], 0, delta=0.15)
                points = transform_points([[0, 0], [650, 0], [650, 800], [0, 800]], meta["source_to_ocr"])
                self.assertTrue(np.all(points >= -1e-6))
                self.assertTrue(np.all(points <= [corrected.shape[1], corrected.shape[0]]))
                np.testing.assert_allclose(transform_points(points, meta["ocr_to_source"]),
                                           [[0, 0], [650, 0], [650, 800], [0, 800]], atol=1e-6)

    def test_perspective_rectifies_four_frame_corners(self):
        source = np.float32([[50, 50], [600, 50], [600, 750], [50, 750]])
        target = np.float32([[85, 75], [570, 50], [615, 740], [45, 765]])
        image = cv2.warpPerspective(table_image(), cv2.getPerspectiveTransform(source, target),
                                    (650, 800), borderValue=(255, 255, 255))
        corrected, meta = correct_page_geometry(image)
        self.assertEqual(meta["method"], "perspective")
        corners = transform_points(meta["table_corners_source"], meta["source_to_ocr"])
        self.assertAlmostEqual(corners[0, 1], corners[1, 1], places=4)
        self.assertAlmostEqual(corners[2, 1], corners[3, 1], places=4)
        self.assertAlmostEqual(corners[0, 0], corners[3, 0], places=4)
        self.assertAlmostEqual(estimate_skew(corrected)[0], 0, delta=0.2)
        _, rotation_only = correct_page_geometry(image, "deskew")
        self.assertNotEqual(rotation_only["method"], "perspective")

    def test_disabled_aligned_blank_and_single_line_are_not_resampled(self):
        aligned = table_image()
        blank = np.full_like(aligned, 255)
        single = blank.copy()
        cv2.line(single, (50, 90), (590, 120), (0, 0, 0), 2)
        for image, mode in ((aligned, "auto"), (aligned, "none"), (blank, "auto"), (single, "auto")):
            with self.subTest(mode=mode):
                result, meta = correct_page_geometry(image, mode)
                self.assertFalse(meta["applied"])
                self.assertIs(result, image)

    def test_nested_boxes_roundtrip_without_changing_text_or_roi_offset(self):
        for matrix in (np.eye(3), np.array([[1.02, 0.03, 59], [-0.02, 1.01, 88], [0.0001, 0.0002, 1]])):
            with self.subTest(matrix=matrix.tolist()):
                box = {"x": 200, "y": 300, "width": 20, "height": 70}
                evidence = {"bbox": box, "region_bbox": box, "text": "子甲", "confidence": 77,
                            "token_boxes": [{"bbox": box, "text": "甲"}],
                            "geometry": {"components": [{"bbox": box}]}}
                before = deepcopy(evidence)
                mapped = map_evidence(evidence, np.linalg.inv(matrix), (800, 950))
                self.assertEqual(evidence, before)
                self.assertEqual(mapped["text"], "子甲")
                self.assertEqual(mapped["confidence"], 77)
                self.assertEqual(mapped["ocr_bbox"], box)
                working = transform_points(mapped["source_polygon"], matrix)
                np.testing.assert_allclose(working, [[200, 300], [220, 300], [220, 370], [200, 370]], atol=1e-6)
                self.assertEqual(layout_evidence(mapped)["token_boxes"][0]["bbox"], box)
                self.assertEqual(mapped["geometry"]["components"][0]["bbox"], mapped["bbox"])

    def test_pipeline_maps_all_evidence_and_saves_original_roi_fallback(self):
        # Both ROI paths run the real segmentation/serialization orchestration
        # with deterministic OCR/name fixtures in corrected page coordinates.
        for manual in (False, True):
            with self.subTest(manual=manual), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "sample.png"
                image = table_image()
                image = cv2.warpAffine(image, cv2.getRotationMatrix2D((325, 400), 2, 1),
                                       (650, 800), borderValue=(255, 255, 255))
                cv2.imwrite(str(source), image)
                argv = ["ocr", str(source), "--rows", "1", "--scale", "2"]
                argv += ["--roi", "40,40,570,720"] if manual else []
                with patch.object(sys, "argv", argv):
                    args = pipeline.parse_args()
                box = {"x": 400, "y": 150, "width": 25, "height": 75}
                column = {"column_id": "c1", "text": "子甲", "mean_confidence": 96, "bbox": box,
                          "region_bbox": box, "token_boxes": [{"text": "子甲", "bbox": box}]}
                region = {"bbox": box, "component_count": 2, "median_component_width": 22,
                          "median_component_height": 22, "components": [{"bbox": box}]}
                prose_box = {"x": 250, "y": 150, "width": 35, "height": 90}
                prose_region = {**region, "bbox": prose_box}
                prose = {**column, "bbox": prose_box, "text": "墓所未詳有設壇", "mean_confidence": 95}
                token = {"text": "子甲", "left": 20, "top": 10, "width": 20, "height": 70}
                with patch("ocr.jokbo_ocr.extract_text_and_confidence", return_value=("子甲", 96, image, [token])) as recognize, \
                     patch("ocr.jokbo_ocr.recover_missing_column_tokens", side_effect=lambda b, r, t, a, p: (t, 0)), \
                     patch("ocr.jokbo_ocr.build_column_records", return_value=[column, prose]), \
                     patch("ocr.jokbo_ocr.detect_row_name_regions", return_value=[region, prose_region]), \
                     patch("ocr.jokbo_ocr.run_name_ocr_variants", return_value=(prose["text"], [{
                         "hanja_text": prose["text"], "variant": "fixture", "mean_confidence": 95}], image)):
                    page = pipeline.ocr_one_image(source, args, root / "output", object())
                self.assertTrue(page["page_geometry"]["applied"])
                self.assertEqual(recognize.call_args.args[1], 2)
                person = page["people_candidates"][0]
                self.assertEqual(len(page["people_candidates"]), 1)
                excluded = page["rows"][0]["excluded_name_regions"][0]
                self.assertEqual(excluded["name_hanja_candidate"], prose["text"])
                self.assertEqual(excluded["ocr_variants"][-1]["hanja_text"], prose["text"])
                self.assertEqual(excluded["ocr_bbox"], prose_box)
                self.assertEqual(person["ocr_bbox"], box)
                expected, polygon = transform_box(box, page["page_geometry"]["ocr_to_source"], (650, 800))
                self.assertEqual(person["bbox"], expected)
                self.assertEqual(page["rows"][0]["columns"][0]["token_boxes"][0]["bbox"], expected)
                raw = build_raw_data(person, page, {}, {})
                self.assertEqual(raw["image"]["source_polygon"], polygon)
                json.dumps(page)  # every matrix/coordinate is JSON-serializable
                page["source_image"] = str(root / "unavailable.png")
                fallback, offset, _ = get_page_image(page, root / "output/sample")
                roi = page["table_roi"]
                self.assertEqual(offset, (roi["x"], roi["y"]))
                self.assertEqual(fallback.shape[:2], (roi["height"], roi["width"]))
                self.assertFalse((root / "output/sample/rows").exists())
                self.assertFalse((root / "output/sample/columns").exists())

    def test_refresh_uses_working_columns_and_original_marker_evidence(self):
        matrix = np.array([[1, 0.12, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        rows = [{"row_id": "r1", "person_candidates": [{"person_id": "father", "name_hanja_candidate": "甲",
                 "bbox": {"x": 390, "y": 100, "width": 20, "height": 70}}]},
                {"row_id": "r2", "person_candidates": [{"person_id": "son", "name_hanja_candidate": "子乙",
                 "bbox": {"x": 390, "y": 300, "width": 20, "height": 70}}]}]
        page = {"source_image": "001.jpg", "image_size": {"width": 800, "height": 950},
                "rows": map_evidence(rows, np.linalg.inv(matrix), (800, 950)), "relationship_candidates": [],
                "page_geometry": {"applied": True, "ocr_table_roi": {"x": 0, "width": 600},
                                  "ocr_to_source": np.linalg.inv(matrix).tolist()}}
        rel = refreshed_relationships(page, {})[0]
        self.assertEqual(rel["parent_center_x"], 400)
        self.assertEqual(rel["child_center_x"], 400)
        self.assertEqual(rel["sex_marker_evidence"][0]["bbox"], page["rows"][1]["person_candidates"][0]["bbox"])

    def test_name_recovery_recreates_working_image_from_source_or_offset_roi(self):
        source = table_image()
        source = cv2.warpAffine(source, cv2.getRotationMatrix2D((325, 400), 2, 1),
                                (650, 800), borderValue=(255, 255, 255))
        _, meta = correct_page_geometry(source)
        box = {"x": 400, "y": 150, "width": 25, "height": 75}
        rows = [{"row_id": "r1", "bbox": {"x": 50, "y": 100, "width": 550, "height": 650},
                 "columns": [{"column_id": "c1", "text": "子甲", "mean_confidence": 96, "bbox": box}],
                 "excluded_name_regions": [{"bbox": {"x": 250, "y": 150, "width": 35, "height": 90}}]}]
        page = {"source_image": "001.jpg", "image_size": {"width": 650, "height": 800},
                "page_geometry": meta, "rows": map_evidence(rows, meta["ocr_to_source"], (650, 800))}
        for image, offset in ((source, (0, 0)), (source[30:780, 30:630], (30, 30))):
            with self.subTest(offset=offset), patch("ocr.jokbo_ocr.detect_row_name_regions", return_value=[
                    {"bbox": box}, rows[0]["excluded_name_regions"][0]]):
                people = recover_name_candidates(image, page, [], offset)
                self.assertEqual(len(people), 1)
                self.assertEqual(people[0]["ocr_bbox"], box)
                self.assertEqual(people[0]["raw_name_ocr"], "子甲")
                self.assertEqual(people[0]["bbox"], transform_box(box, meta["ocr_to_source"], (650, 800))[0])

    def test_field_partition_uses_layout_boxes_but_exports_source_evidence(self):
        person = {"person_id": "p", "source_row_id": "r", "bbox": {"x": 200, "width": 30},
                  "ocr_bbox": {"x": 400, "width": 20}}
        column = {"column_id": "c", "text": "甲子年生", "bbox": {"x": 250, "y": 500, "width": 30, "height": 90},
                  "ocr_bbox": {"x": 350, "y": 100, "width": 20, "height": 90},
                  "source_polygon": [[250, 500], [280, 500], [280, 590], [250, 590]]}
        row = {"row_id": "r", "columns": [column]}
        draft = extract_person_info_draft(person, {"rows": [row]}, [person])
        evidence = draft["field_sources"]["birth_text"][0]
        self.assertEqual(evidence["bbox"], column["bbox"])
        self.assertEqual(evidence["source_polygon"], column["source_polygon"])
        self.assertEqual(evidence["ocr_bbox"], column["ocr_bbox"])
        self.assertEqual(orphan_columns(row, [person]), [])
