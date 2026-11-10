#!/usr/bin/env python3
"""LLM-free OCR and rule-based extraction for Korean genealogy (jokbo) scans.

Uses OpenCV for page/row/column geometry, PaddleOCR for text and character
boxes, and deterministic Python rules for reviewable genealogy candidates.
No generative AI, API key, network request, or remote model is used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from .storage import check_page_target, load_ocr_output, save_page_result

HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
CHINESE_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "兩": 2, "两": 2,
    "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}
GENERATION_RE = re.compile(r"([一二三四五六七八九十百千零〇○兩两]+)世")
MARKERS = {
    "繼配": "secondary_spouse_marker", "嗣子": "adopted_heir_marker",
    "出繼": "adoption_out_marker", "入繼": "adoption_in_marker",
    "諱": "personal_name_marker", "字": "courtesy_name_marker",
    "號": "pen_name_marker", "配": "spouse_marker", "子": "child_marker",
    "父": "father_marker", "母": "mother_marker", "生": "birth_marker",
    "卒": "death_marker", "墓": "tomb_marker",
}


@dataclass
class LineBoundary:
    y: int
    detected: bool
    coverage: float
    method: str


def is_hanzi(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in HAN_RANGES)


def clean_hanzi_text(text: str) -> str:
    return "".join(char for char in text if is_hanzi(char))


def chinese_number_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if all(char in CHINESE_DIGITS for char in value):
        return int("".join(str(CHINESE_DIGITS[char]) for char in value))
    total = 0
    number = 0
    for char in value:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
        elif char in CHINESE_UNITS:
            unit = CHINESE_UNITS[char]
            if number == 0:
                number = 1
            total += number * unit
            number = 0
        else:
            return None
    return total + number


def parse_generation(text: str) -> dict[str, Any] | None:
    compact = re.sub(r"\s+", "", text)
    matches = []
    for match in GENERATION_RE.finditer(compact):
        number = chinese_number_to_int(match.group(1))
        if number is not None:
            matches.append({"generation_text": match.group(0), "generation_number": number})
    if not matches:
        return None
    unique_numbers = {item["generation_number"] for item in matches}
    if len(unique_numbers) == 1:
        return {
            "generation_text": matches[0]["generation_text"],
            "generation_number": matches[0]["generation_number"],
            "all_matches": matches,
        }
    return {"generation_text": None, "generation_number": None, "all_matches": matches, "ambiguous": True}


def extract_rule_markers(text: str) -> list[dict[str, str]]:
    compact = re.sub(r"\s+", "", text)
    found: list[dict[str, str]] = []
    occupied: set[int] = set()
    # Match longer terms first so 嗣子 is not double-counted as 子.
    for marker in sorted(MARKERS, key=len, reverse=True):
        start = 0
        while True:
            index = compact.find(marker, start)
            if index < 0:
                break
            positions = set(range(index, index + len(marker)))
            if not positions.intersection(occupied):
                found.append({"marker": marker, "type": MARKERS[marker], "index": str(index)})
                occupied.update(positions)
            start = index + len(marker)
    found.sort(key=lambda item: int(item["index"]))
    return found


def parse_person_name(column: dict[str, Any], min_font_size_ratio: float = 1.22) -> dict[str, Any] | None:
    """Create a cautious candidate from a short Hanzi column printed larger than body text."""
    hanzi = clean_hanzi_text(column.get("text", ""))
    ratio = float(column.get("font_size_ratio", 0.0))
    raw_conf = column.get("mean_confidence")
    confidence = float(raw_conf) if raw_conf is not None else 0.0
    if not (2 <= len(hanzi) <= 4 and ratio >= min_font_size_ratio):
        return None
    excluded = {"杜陵杜氏", "世譜", "世譜卷", "杜陵杜氏世譜", "卷二", "一世", "二世", "三世", "四世", "五世", "六世"}
    if hanzi in excluded or "世" in hanzi or "卷" in hanzi:
        return None
    if hanzi.startswith("子"):
        if confidence < 28.0:
            return None
        rule_class = "name_like_prefix_子"
    else:
        if confidence < 48.0 or ratio < max(min_font_size_ratio, 1.35):
            return None
        rule_class = "large_font_high_confidence"
    return {
        "name_hanja_candidate": hanzi,
        "evidence_text": column.get("text", ""),
        "source_column_id": column.get("column_id"),
        "source_row_id": column.get("row_id"),
        "bbox": column.get("bbox"),
        "font_size_ratio": round(ratio, 3),
        "ocr_confidence": raw_conf,
        "rule_class": rule_class,
        "review_status": "needs_review",
        "candidate_type": "large_font_vertical_column",
    }



def detect_large_printed_name_regions(
    band: np.ndarray, page_x: int, page_y: int,
    min_component_width: int = 18, min_component_height: int = 18,
    min_component_area: int = 100, x_cluster_tolerance: float = 8.0,
    right_margin_exclusion: int = 45, min_vertical_glyph_gap: int = 27,
) -> list[dict[str, Any]]:
    """Detect prominent vertical name columns from image geometry, not OCR text.

    First merges horizontally adjacent connected components belonging to one
    printed glyph, then groups large glyphs along a vertical axis. Requiring a
    minimum vertical gap rejects short adjacent prose fragments such as 親族也.
    Results are review candidates, never confirmed genealogy records.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band.copy()
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # Remove horizontal table rules before connected-component analysis.
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(25, band.shape[1] // 5), 1)
    )
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    cleaned = cv2.subtract(binary, horizontal_lines)

    count, _, stats, centroids = cv2.connectedComponentsWithStats(cleaned, 8)
    components: list[dict[str, float | int]] = []
    for index in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[index])
        # Keep small fragments initially; separate strokes of one large Hanzi
        # may each be narrow and need to be joined before size filtering.
        if area < 15 or width < 4 or height < 4 or width > 40 or height > 50:
            continue
        components.append({
            "x": x, "y": y, "width": width, "height": height, "area": area,
            "center_x": float(centroids[index][0]),
            "center_y": float(centroids[index][1]),
        })

    # Merge horizontally adjacent ink fragments on the same character row.
    glyphs: list[dict[str, float | int]] = []
    for component in sorted(components, key=lambda item: (float(item["center_y"]), int(item["x"]))):
        match = None
        for glyph in reversed(glyphs[-30:]):
            glyph_center_y = float(glyph["y"]) + float(glyph["height"]) / 2.0
            glyph_right = int(glyph["x"]) + int(glyph["width"])
            component_right = int(component["x"]) + int(component["width"])
            horizontal_gap = max(
                0, max(int(glyph["x"]), int(component["x"]))
                - min(glyph_right, component_right)
            )
            if abs(float(component["center_y"]) - glyph_center_y) <= 8.0 and horizontal_gap <= 5:
                match = glyph
                break
        if match is None:
            glyphs.append(dict(component))
        else:
            left = min(int(match["x"]), int(component["x"]))
            top = min(int(match["y"]), int(component["y"]))
            right = max(
                int(match["x"]) + int(match["width"]),
                int(component["x"]) + int(component["width"]),
            )
            bottom = max(
                int(match["y"]) + int(match["height"]),
                int(component["y"]) + int(component["height"]),
            )
            match.update(
                x=left, y=top, width=right-left, height=bottom-top,
                area=int(match["area"]) + int(component["area"]),
                center_x=(left+right)/2.0, center_y=(top+bottom)/2.0,
            )

    # Some printed characters (e.g. 吉) are split into an upper and lower
    # component. Horizontal-only merging leaves both shorter than the minimum
    # glyph height. Join tightly stacked, aligned fragments before filtering.
    merged_glyphs: list[dict[str, float | int]] = []
    for glyph in sorted(glyphs, key=lambda item: int(item["y"])):
        match = None
        for previous in reversed(merged_glyphs):
            gap = int(glyph["y"]) - (int(previous["y"]) + int(previous["height"]))
            overlap = min(int(previous["x"]) + int(previous["width"]), int(glyph["x"]) + int(glyph["width"])) - max(int(previous["x"]), int(glyph["x"]))
            combined_height = int(glyph["y"]) + int(glyph["height"]) - int(previous["y"])
            combined_width = max(int(previous["x"]) + int(previous["width"]), int(glyph["x"]) + int(glyph["width"])) - min(int(previous["x"]), int(glyph["x"]))
            if (0 <= gap <= 3 and int(previous["height"]) < min_component_height
                    and int(glyph["height"]) < min_component_height
                    # Wider fragments often join neighboring prose columns.
                    and min_component_width <= combined_width <= min(30, min_component_width * 1.7)
                    and overlap >= 0.6 * min(int(previous["width"]), int(glyph["width"]))
                    and abs(float(previous["center_x"]) - float(glyph["center_x"])) <= x_cluster_tolerance
                    and min_component_height <= combined_height <= 35):
                match = previous
                break
        if match is None:
            merged_glyphs.append(dict(glyph))
        else:
            left = min(int(match["x"]), int(glyph["x"]))
            right = max(int(match["x"]) + int(match["width"]), int(glyph["x"]) + int(glyph["width"]))
            bottom = int(glyph["y"]) + int(glyph["height"])
            match.update(x=left, width=right-left, height=bottom-int(match["y"]),
                         area=int(match["area"]) + int(glyph["area"]),
                         center_x=(left+right)/2, center_y=(int(match["y"])+bottom)/2)

    large_glyphs = [
        glyph for glyph in merged_glyphs
        if int(glyph["width"]) >= min_component_width
        and int(glyph["height"]) >= min_component_height
        and int(glyph["area"]) >= min_component_area
        and int(glyph["width"]) <= 35 and int(glyph["height"]) <= 45
    ]

    # Group glyphs into vertical columns by their horizontal centers.
    groups: list[list[dict[str, float | int]]] = []
    for glyph in sorted(large_glyphs, key=lambda item: float(item["center_x"])):
        matching = None
        for group in groups:
            center = float(np.median([float(item["center_x"]) for item in group]))
            if abs(float(glyph["center_x"]) - center) <= x_cluster_tolerance:
                matching = group
                break
        if matching is None:
            groups.append([glyph])
        else:
            matching.append(glyph)

    results: list[dict[str, Any]] = []
    for group in groups:
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda item: float(item["center_y"]))
        y_centers = [float(item["center_y"]) for item in group]
        y_gaps = [int(round(b-a)) for a, b in zip(y_centers, y_centers[1:])]
        # Name characters are vertically spaced; neighboring prose fragments
        # in the same paragraph tend to be much closer together.
        if not any(gap >= min_vertical_glyph_gap for gap in y_gaps):
            continue
        center_x_local = float(np.median([float(item["center_x"]) for item in group]))
        # The far-right strip is the recurring book-title/generation header.
        if center_x_local >= band.shape[1] - right_margin_exclusion:
            continue
        left = min(int(item["x"]) for item in group)
        top = min(int(item["y"]) for item in group)
        right = max(int(item["x"]) + int(item["width"]) for item in group)
        bottom = max(int(item["y"]) + int(item["height"]) for item in group)
        results.append({
            "center_x": round(page_x + center_x_local, 2),
            "bbox": {
                "x": page_x + left, "y": page_y + top,
                "width": right - left, "height": bottom - top,
            },
            "component_count": len(group),
            "median_component_width": round(float(np.median([int(item["width"]) for item in group])), 2),
            "median_component_height": round(float(np.median([int(item["height"]) for item in group])), 2),
            "components": [
                {
                    "bbox": {
                        "x": page_x + int(item["x"]), "y": page_y + int(item["y"]),
                        "width": int(item["width"]), "height": int(item["height"]),
                    },
                    "area": int(item["area"]),
                }
                for item in group
            ],
        })
    return sorted(results, key=lambda item: item["center_x"], reverse=True)

def find_matching_ocr_column(
    geometry: dict[str, Any], columns: list[dict[str, Any]], max_distance: float = 24.0
) -> dict[str, Any] | None:
    """Match a row-level OCR column to a geometry name box using 2D overlap.

    The previous implementation matched on x distance only. That could attach
    body text from the same vertical column to a nearby person name. Requiring
    vertical overlap makes row OCR reuse much safer.
    """
    target = geometry.get("bbox") or {}
    tx0, ty0 = float(target.get("x", 0)), float(target.get("y", 0))
    tx1 = tx0 + float(target.get("width", 0))
    ty1 = ty0 + float(target.get("height", 0))
    ranked: list[tuple[float, float, dict[str, Any]]] = []
    for column in columns:
        bbox = column.get("bbox") or {}
        cx0, cy0 = float(bbox.get("x", 0)), float(bbox.get("y", 0))
        cx1 = cx0 + float(bbox.get("width", 0))
        cy1 = cy0 + float(bbox.get("height", 0))
        overlap_x = max(0.0, min(tx1, cx1) - max(tx0, cx0))
        overlap_y = max(0.0, min(ty1, cy1) - max(ty0, cy0))
        center_distance = abs((cx0 + cx1) / 2.0 - (tx0 + tx1) / 2.0)
        if overlap_x <= 0 or overlap_y <= 0 or center_distance > max_distance:
            continue
        intersection = overlap_x * overlap_y
        target_area = max(1.0, (tx1 - tx0) * (ty1 - ty0))
        column_area = max(1.0, (cx1 - cx0) * (cy1 - cy0))
        overlap_score = intersection / min(target_area, column_area)
        ranked.append((overlap_score, -center_distance, column))
    if not ranked:
        return None
    return max(ranked, key=lambda item: (item[0], item[1]))[2]


def crop_name_region(image: np.ndarray, bbox: dict[str, int], padding: int = 7) -> np.ndarray:
    """Return the source-resolution crop for a detected name region."""
    y_max, x_max = image.shape[:2]
    x0 = max(0, int(bbox["x"]) - padding)
    y0 = max(0, int(bbox["y"]) - padding)
    x1 = min(x_max, int(bbox["x"]) + int(bbox["width"]) + padding)
    y1 = min(y_max, int(bbox["y"]) + int(bbox["height"]) + padding)
    return image[y0:y1, x0:x1]

def _paddle_payload(result_item: Any) -> dict[str, Any]:
    """Normalize PaddleOCR 3.x result objects/dicts to their inner `res` dict."""
    payload: Any = result_item
    if hasattr(result_item, "json"):
        payload = result_item.json
        if callable(payload):
            payload = payload()
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected PaddleOCR result type: {type(payload).__name__}")
    if isinstance(payload.get("res"), dict):
        payload = payload["res"]
    return payload


def run_paddle_ocr_image(
    paddle_ocr: Any,
    image: np.ndarray,
    coordinate_scale: float = 1.0,
    reading_order: str = "vertical",
) -> tuple[str, float | None, list[dict[str, Any]]]:
    """Run PaddleOCR 3.x on an ndarray and normalize its polygons to our token schema."""
    if paddle_ocr is None:
        raise RuntimeError("PaddleOCR backend was not initialized")
    source = image
    if source.ndim == 2:
        source = cv2.cvtColor(source, cv2.COLOR_GRAY2BGR)
    elif source.ndim == 3 and source.shape[2] == 4:
        source = cv2.cvtColor(source, cv2.COLOR_BGRA2BGR)

    try:
        raw_results = paddle_ocr.predict(source)
    except TypeError:
        # Compatibility fallback for early PaddleOCR 3.x builds.
        raw_results = paddle_ocr.predict(input=source)
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, (list, tuple)):
        raw_results = list(raw_results)

    tokens: list[dict[str, Any]] = []
    for result_item in raw_results:
        payload = _paddle_payload(result_item)
        texts = payload.get("rec_texts")
        scores = payload.get("rec_scores")
        boxes = payload.get("rec_polys")
        if texts is None:
            texts = []
        if scores is None:
            scores = []
        if boxes is None:
            boxes = payload.get("rec_boxes")
        if boxes is None:
            boxes = payload.get("dt_polys")
        if boxes is None:
            boxes = []

        for index, raw_text in enumerate(texts):
            token_text = str(raw_text or "").strip()
            if not token_text:
                continue
            score = None
            if index < len(scores):
                try:
                    score = float(scores[index]) * 100.0
                except (TypeError, ValueError):
                    score = None

            left = top = 0.0
            right = bottom = 0.0
            try:
                box = np.asarray(boxes[index], dtype=float)
                if box.ndim == 2 and box.shape[1] >= 2:
                    left, top = float(np.min(box[:, 0])), float(np.min(box[:, 1]))
                    right, bottom = float(np.max(box[:, 0])), float(np.max(box[:, 1]))
                elif box.size >= 4:
                    flat = box.reshape(-1)
                    left, top, right, bottom = map(float, flat[:4])
            except (IndexError, TypeError, ValueError):
                pass

            scale = max(float(coordinate_scale), 1e-6)
            tokens.append({
                "text": token_text,
                "confidence": round(score, 2) if score is not None else None,
                "left": round(left / scale),
                "top": round(top / scale),
                "width": max(1, round((right - left) / scale)),
                "height": max(1, round((bottom - top) / scale)),
                "block_num": 1,
                "par_num": 1,
                "line_num": index + 1,
                "word_num": 1,
            })

    if reading_order == "horizontal":
        tokens.sort(key=lambda item: (item["top"], item["left"]))
    else:
        # Korean jokbo columns are read from right to left; text within a
        # detected vertical line is already returned by the recognizer.
        tokens.sort(key=lambda item: (-(item["left"] + item["width"] / 2), item["top"]))

    texts = [item["text"] for item in tokens]
    confidences = [item["confidence"] for item in tokens if item["confidence"] is not None]
    mean_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    return "\n".join(texts), mean_confidence, tokens


def run_name_ocr_variants(
    image: np.ndarray,
    bbox: dict[str, int],
    scale: float = 3.0,
    padding: int = 7,
    paddle_ocr: Any = None,
    paddle_min_confidence: float = 70.0,
) -> tuple[str, list[dict[str, Any]], np.ndarray]:
    """OCR a geometry-detected name crop with PaddleOCR.

    The source crop uses CLAHE, Otsu, adaptive thresholding and a 90-degree
    counter-clockwise variant. All hypotheses are retained for review.
    """
    crop = crop_name_region(image, bbox, padding)
    if crop.size == 0:
        return "", [], crop

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(enlarged)
    otsu = cv2.threshold(cv2.GaussianBlur(clahe, (3, 3), 0), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive_block = max(15, min(41, (min(enlarged.shape[:2]) // 2) * 2 - 1))
    adaptive = cv2.adaptiveThreshold(
        clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        adaptive_block, 9,
    )

    variants: list[dict[str, Any]] = []
    # Fallback is deliberately staged: one fast CLAHE pass first, then
    # progressively more expensive variants only when the result is weak.
    pass_specs = [
        ("clahe_vertical", clahe, "vertical"),
        ("otsu_vertical", otsu, "vertical"),
        ("adaptive_vertical", adaptive, "vertical"),
        ("clahe_rotated_ccw", cv2.rotate(clahe, cv2.ROTATE_90_COUNTERCLOCKWISE), "horizontal"),
    ]
    for label, prepared, order in pass_specs:
        try:
            text, confidence, _ = run_paddle_ocr_image(
                paddle_ocr, prepared, coordinate_scale=1.0, reading_order=order
            )
            cleaned = clean_hanzi_text(text)
            variants.append({
                "variant": label, "engine": "paddleocr", "language": "chinese_cht",
                "model": "PP-OCRv5", "text": text, "hanja_text": cleaned,
                "mean_confidence": confidence, "character_count": len(cleaned),
                "status": "ok" if cleaned else "empty",
            })
        except Exception as exc:
            variants.append({
                "variant": label, "engine": "paddleocr", "language": "chinese_cht",
                "model": "PP-OCRv5", "text": "", "hanja_text": "",
                "mean_confidence": None, "character_count": 0,
                "status": f"error: {type(exc).__name__}: {exc}",
            })
        # A plausible 2–4-character name with a good score is sufficient;
        # do not run the remaining preprocessing variants.
        current = variants[-1]
        if (2 <= current["character_count"] <= 4
                and float(current.get("mean_confidence") or 0) >= paddle_min_confidence):
            break
    usable = [v for v in variants if v["hanja_text"]]
    if usable:
        best = max(usable, key=lambda v: (
            float(v["mean_confidence"] or 0),
            1 if 2 <= v["character_count"] <= 4 else 0,
            v["character_count"],
        ))
        best_text = best["hanja_text"]
    else:
        best_text = ""
    return best_text, variants, crop


def parse_roi(value: str, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    try:
        x, y, w, h = [int(item.strip()) for item in value.split(",")]
    except Exception as exc:
        raise ValueError("--roi must be x,y,width,height") from exc
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image_width or y + h > image_height:
        raise ValueError("--roi rectangle is outside the image or has invalid dimensions")
    return x, y, w, h


def detect_table_roi(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Find the dominant table frame, then trim a connected page-side title."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_h, image_w = gray.shape[:2]
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_h * image_w * 0.22:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(contour)
            if 0.45 <= w / max(h, 1) <= 0.95:
                candidates.append((area, (x, y, w, h)))
    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    x, y, w, h = candidates[0][1]
    inset_x, inset_y = max(1, round(w * 0.006)), max(1, round(h * 0.006))
    x, y, w, h = x + inset_x, y + inset_y, w - 2 * inset_x, h - 2 * inset_y

    # On some scans, the left-side vertical title joins the frame contour.
    roi_gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image[y:y+h, x:x+w].copy()
    roi_binary = cv2.threshold(cv2.GaussianBlur(roi_gray, (3, 3), 0), 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, int(h * 0.55))))
    vertical = cv2.morphologyEx(roi_binary, cv2.MORPH_OPEN, kernel)
    projection = np.sum(vertical > 0, axis=0)
    left_limit = max(1, int(w * 0.15))
    right_start = min(w - 2, int(w * 0.85))
    left_peak = int(np.argmax(projection[:left_limit]))
    right_peak = right_start + int(np.argmax(projection[right_start:]))
    original_width = w
    left_shift = 0
    if left_peak > 8 and projection[left_peak] >= h * 0.45:
        left_shift = left_peak
        x += left_shift
        w -= left_shift
    if right_peak < original_width - 4 and projection[right_peak] >= h * 0.45:
        w = max(1, right_peak - left_shift)
    return x, y, max(1, w), h


def _cluster_hough_segments(segments: list[tuple[float, float, int, int]], max_gap: float = 5.0):
    groups: list[list[tuple[float, float, int, int]]] = []
    for segment in sorted(segments, key=lambda item: item[0]):
        if not groups or segment[0] - groups[-1][-1][0] > max_gap:
            groups.append([segment])
        else:
            groups[-1].append(segment)
    return groups


def _union_coverage(segments: list[tuple[float, float, int, int]]) -> int:
    intervals = sorted((item[2], item[3]) for item in segments)
    if not intervals:
        return 0
    total = 0
    left, right = intervals[0]
    for next_left, next_right in intervals[1:]:
        if next_left <= right:
            right = max(right, next_right)
        else:
            total += right - left
            left, right = next_left, next_right
    return total + right - left


def detect_horizontal_boundaries(table: np.ndarray, rows: int) -> list[LineBoundary]:
    """Detect internal horizontal rules using Hough lines near expected row cuts."""
    height, width = table.shape[:2]
    gray = cv2.cvtColor(table, cv2.COLOR_BGR2GRAY) if table.ndim == 3 else table.copy()
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 35, 110)
    hough = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(45, int(width * 0.12)),
                            minLineLength=max(40, int(width * 0.18)), maxLineGap=max(20, int(width * 0.08)))
    segments: list[tuple[float, float, int, int]] = []
    if hough is not None:
        # OpenCV versions/builds may return HoughLinesP as either (N, 1, 4)
        # or (N, 4). Indexing hough[:, 0] only works for the former; with
        # the latter it yields scalar numpy.int32 values and causes:
        # TypeError: 'numpy.int32' object is not iterable.
        # Normalize both layouts to a predictable sequence of (x1,y1,x2,y2).
        hough_segments = np.asarray(hough).reshape(-1, 4)
        for line in hough_segments:
            x1, y1, x2, y2 = (int(value) for value in line)
            dx, dy = x2 - x1, y2 - y1
            if not dx:
                continue
            angle = abs(float(np.degrees(np.arctan2(dy, dx))))
            length = float(np.hypot(dx, dy))
            if angle <= 3.0 and length >= width * 0.18:
                segments.append(((y1 + y2) / 2.0, length, min(x1, x2), max(x1, x2)))

    boundaries = [LineBoundary(0, True, 1.0, "table_top")]
    for index in range(1, rows):
        target = height * index / rows
        tolerance = height / rows * 0.20
        nearby = [segment for segment in segments if abs(segment[0] - target) <= tolerance]
        clusters = _cluster_hough_segments(nearby)
        best = None
        best_score = -1.0
        for cluster in clusters:
            center = sum(item[0] * item[1] for item in cluster) / max(sum(item[1] for item in cluster), 1.0)
            coverage = _union_coverage(cluster)
            score = coverage - abs(center - target) / max(tolerance, 1.0) * width * 0.12
            if score > best_score:
                best_score, best = score, cluster
        if best:
            y = int(round(sum(item[0] * item[1] for item in best) / max(sum(item[1] for item in best), 1.0)))
            coverage = min(1.0, _union_coverage(best) / max(width, 1))
            boundaries.append(LineBoundary(y, coverage >= 0.25, round(coverage, 3), "hough"))
        else:
            boundaries.append(LineBoundary(int(round(target)), False, 0.0, "equal_spacing_fallback"))

    boundaries.append(LineBoundary(height, True, 1.0, "table_bottom"))
    boundaries.sort(key=lambda item: item.y)
    fixed = [boundaries[0]]
    for boundary in boundaries[1:-1]:
        if boundary.y - fixed[-1].y >= max(25, height // (rows * 3)):
            fixed.append(boundary)
    fixed.append(boundaries[-1])
    return fixed


def _fill_short_projection_gaps(active: np.ndarray, max_gap: int = 2) -> np.ndarray:
    result = active.copy()
    for gap in range(1, max_gap + 1):
        if len(result) <= 2 * gap:
            break
        mask = (~result[gap:-gap]) & result[:-2*gap] & result[2*gap:]
        result[gap:-gap][mask] = True
    return result


def detect_vertical_columns(band: np.ndarray, ink_ratio: float = 0.08, min_width: int = 5) -> list[tuple[int, int]]:
    """Find vertical text-column x-ranges from the dark-pixel projection."""
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band.copy()
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    projection = np.sum(binary > 0, axis=0).astype(np.float32)
    smoothed = np.convolve(projection, np.ones(3, dtype=np.float32) / 3.0, mode="same")
    threshold = max(2.0, band.shape[0] * ink_ratio)
    active = _fill_short_projection_gaps(smoothed >= threshold, 2)
    margin = max(2, int(band.shape[1] * 0.012))
    active[:margin] = False
    active[-margin:] = False
    indices = np.flatnonzero(active)
    regions: list[tuple[int, int]] = []
    if not len(indices):
        return regions
    start = previous = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value > previous + 1:
            if previous - start + 1 >= min_width:
                regions.append((start, previous + 1))
            start = value
        previous = value
    if previous - start + 1 >= min_width:
        regions.append((start, previous + 1))
    return regions


def preprocess(image: np.ndarray, mode: str) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    if mode == "gray":
        return gray
    if mode == "clahe":
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    if mode == "adaptive":
        block = 41 if min(gray.shape[:2]) > 45 else max(3, (min(gray.shape[:2]) // 2) * 2 - 1)
        return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 11)
    if mode == "otsu":
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    raise ValueError(f"Unsupported preprocessing mode: {mode}")


def extract_text_and_confidence(
    image: np.ndarray, scale: float, preprocess_mode: str, paddle_ocr: Any = None,
) -> tuple[str, float | None, np.ndarray, list[dict[str, Any]]]:
    """Run PaddleOCR and normalize output to the existing token schema."""
    prepared = preprocess(image, preprocess_mode)
    if scale != 1.0:
        prepared = cv2.resize(prepared, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)

    text, mean_confidence, tokens = run_paddle_ocr_image(
        paddle_ocr, prepared, coordinate_scale=scale, reading_order="vertical"
    )
    return text, mean_confidence, prepared, tokens


def build_column_records(
    tokens: list[dict[str, Any]], regions: list[tuple[int, int]], band: np.ndarray,
    row_id: str, page_x: int, page_y: int, row_height: int, columns_dir: Path,
) -> list[dict[str, Any]]:
    """Map vertical OCR lines to OpenCV-projected column areas."""
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    line_order: list[tuple[int, int, int]] = []
    for token in tokens:
        key = (int(token["block_num"]), int(token["par_num"]), int(token["line_num"]))
        if key not in grouped:
            grouped[key] = []
            line_order.append(key)
        grouped[key].append(token)

    line_records = []
    for key in line_order:
        items = sorted(grouped[key], key=lambda item: (item["word_num"], item["top"], item["left"]))
        left = min(item["left"] for item in items)
        top = min(item["top"] for item in items)
        right = max(item["left"] + item["width"] for item in items)
        bottom = max(item["top"] + item["height"] for item in items)
        center_x = (left + right) / 2.0
        nearest = None
        nearest_distance = float("inf")
        for region in regions:
            center = (region[0] + region[1]) / 2.0
            distance = 0.0 if region[0] <= center_x <= region[1] else min(abs(center_x - region[0]), abs(center_x - region[1]))
            if distance < nearest_distance:
                nearest, nearest_distance = region, distance
        if nearest_distance > max(16, band.shape[1] * 0.035):
            nearest = None
        heights = [item["height"] for item in items if item["height"] > 0]
        font_height = float(np.median(heights)) if heights else 0.0
        valid_conf = [item["confidence"] for item in items if item["confidence"] is not None]
        line_conf = round(sum(valid_conf) / len(valid_conf), 2) if valid_conf else None
        line_records.append({
            "center_x": center_x, "left": left, "top": top, "right": right, "bottom": bottom,
            "items": items, "text": "".join(item["text"] for item in items),
            "font_height_px": font_height, "mean_confidence": line_conf, "region": nearest,
        })

    line_records.sort(key=lambda item: item["center_x"], reverse=True)
    positive_heights = [item["font_height_px"] for item in line_records if item["font_height_px"] > 0]
    median_font_height = float(np.median(positive_heights)) if positive_heights else 1.0
    records: list[dict[str, Any]] = []
    for order, item in enumerate(line_records, start=1):
        region = item["region"]
        if region:
            crop_left = max(0, region[0] - 2)
            crop_right = min(band.shape[1], region[1] + 2)
        else:
            crop_left = max(0, item["left"] - 3)
            crop_right = min(band.shape[1], item["right"] + 3)
        image_file = columns_dir / f"{row_id}_col_{order:02d}.png"
        cv2.imwrite(str(image_file), band[:, crop_left:crop_right])
        records.append({
            "column_id": f"{row_id}_col_{order:02d}",
            "row_id": row_id,
            "order_right_to_left": order,
            "bbox": {
                "x": page_x + item["left"], "y": page_y + item["top"],
                "width": max(1, item["right"] - item["left"]),
                "height": max(1, item["bottom"] - item["top"]),
            },
            "region_bbox": {
                "x": page_x + crop_left, "y": page_y,
                "width": crop_right - crop_left, "height": row_height,
            },
            "font_height_px": round(item["font_height_px"], 2),
            "font_size_ratio": round(item["font_height_px"] / max(median_font_height, 1.0), 3),
            "text": item["text"],
            "normalized_hanzi": clean_hanzi_text(item["text"]),
            "mean_confidence": item["mean_confidence"],
            "image_file": str(image_file),
            "ocr_status": "from_row_ocr",
            "token_boxes": [
                {"text": token["text"], "bbox": {
                    "x": page_x + token["left"], "y": page_y + token["top"],
                    "width": token["width"], "height": token["height"],
                }, "confidence": token["confidence"]}
                for token in item["items"]
            ],
        })
    for record in records:
        record["median_font_height_px"] = round(median_font_height, 2)
    return records


def parse_rule_mentions(row: dict[str, Any]) -> list[dict[str, Any]]:
    mentions = []
    for marker in extract_rule_markers(row.get("band_text", "")):
        mentions.append({
            **marker, "source_column_id": None, "source_row_id": row["row_id"],
            "evidence_text": row.get("band_text", ""), "bbox": row.get("bbox"),
            "review_status": "needs_review",
        })
    for column in row.get("columns", []):
        for marker in extract_rule_markers(column.get("text", "")):
            mentions.append({
                **marker, "source_column_id": column["column_id"], "source_row_id": row["row_id"],
                "evidence_text": column.get("text", ""), "bbox": column.get("bbox"),
                "review_status": "needs_review",
            })
    return mentions


def _person_center_x(person: dict[str, Any], table_x: int) -> float:
    box = person.get("bbox") or {}
    return float(box.get("x", table_x)) + float(box.get("width", 0)) / 2.0 - table_x


def parse_relationships(
    rows: list[dict[str, Any]], page_width: int, table_x: int = 0,
    direct_alignment_ratio: float = 0.04, branch_boundary_margin: float = 10.0,
) -> list[dict[str, Any]]:
    """Infer review-pending parent/child links from the user's page-layout rule.

    The generation labels are intentionally ignored. People in the next
    horizontal band are assigned to the prior-band parent's horizontal branch:
    - first son is immediately below/aligned with the father;
    - later sons are to the left of the first son;
    - daughters, when present, are to the right of the sons.

    Parent branch bounds are midpoints between neighboring parent anchors.
    All edges remain review-pending because layout is evidence, not proof.
    """
    suggestions: list[dict[str, Any]] = []
    alignment_tolerance = max(16.0, page_width * direct_alignment_ratio)

    for previous, current in zip(rows, rows[1:]):
        parents = previous.get("person_candidates", [])
        children = current.get("person_candidates", [])
        if not parents or not children:
            continue

        parent_entries = sorted(
            [( _person_center_x(parent, table_x), parent) for parent in parents],
            key=lambda item: item[0], reverse=True,
        )
        # Build a branch interval around each parent anchor. A child's x within
        # this interval belongs to that parent unless it is too close to a split.
        branches: list[dict[str, Any]] = []
        for index, (parent_x, parent) in enumerate(parent_entries):
            right_bound = (parent_x + parent_entries[index - 1][0]) / 2.0 if index > 0 else float(page_width)
            left_bound = (parent_x + parent_entries[index + 1][0]) / 2.0 if index + 1 < len(parent_entries) else 0.0
            branches.append({
                "parent": parent, "parent_x": parent_x,
                "left_bound": left_bound, "right_bound": right_bound,
            })

        assigned: dict[str, list[dict[str, Any]]] = {str(b["parent"]["person_id"]): [] for b in branches}
        for child in children:
            child_x = _person_center_x(child, table_x)
            containing = [b for b in branches if b["left_bound"] <= child_x <= b["right_bound"]]
            if len(containing) != 1:
                # Keep a non-link candidate rather than invent a parent.
                ranked = sorted(branches, key=lambda b: min(
                    abs(child_x - b["left_bound"]), abs(child_x - b["right_bound"]),
                    abs(child_x - b["parent_x"]),
                ))
                suggestions.append({
                    "relationship_id": f"R{len(suggestions)+1:04d}",
                    "type": "unresolved_parent_child_candidate",
                    "parent_candidate_id": None,
                    "parent_name_hanja_candidate": None,
                    "candidate_parent_ids": [b["parent"]["person_id"] for b in ranked[:2]],
                    "child_candidate_id": child.get("person_id"),
                    "child_name_hanja_candidate": child.get("name_hanja_candidate"),
                    "relationship_basis": "next_row_branch_position_ambiguous",
                    "placement_role": "unresolved",
                    "horizontal_distance_px": None,
                    "evidence_text": f"{previous['row_id']} -> {current['row_id']}; child lies on/near branch boundary",
                    "source_row_ids": [previous["row_id"], current["row_id"]],
                    "confidence": 0.2,
                    "review_status": "needs_review",
                    "warning": "Parent branch was ambiguous under the horizontal layout rule.",
                })
                continue
            branch = containing[0]
            boundary_distance = min(child_x - branch["left_bound"], branch["right_bound"] - child_x)
            child_copy = {"person": child, "x": child_x,
                          "near_branch_boundary": boundary_distance <= branch_boundary_margin}
            assigned[str(branch["parent"]["person_id"])].append(child_copy)

        for branch in branches:
            parent = branch["parent"]
            parent_id = str(parent["person_id"])
            parent_x = float(branch["parent_x"])
            child_group = assigned[parent_id]
            if not child_group:
                continue

            # Eldest son anchor: the child closest to the father's x coordinate.
            aligned = [item for item in child_group if abs(item["x"] - parent_x) <= alignment_tolerance]
            first_son = min(aligned, key=lambda item: abs(item["x"] - parent_x)) if aligned else None
            first_son_x = first_son["x"] if first_son else None

            # Determine each child's positional role using the user's ordering rule.
            left_sons = sorted(
                [item for item in child_group if first_son_x is not None and item["x"] < first_son_x - alignment_tolerance],
                key=lambda item: item["x"], reverse=True,
            )
            right_daughters = sorted(
                [item for item in child_group if first_son_x is not None and item["x"] > first_son_x + alignment_tolerance],
                key=lambda item: item["x"], reverse=True,
            )
            for item in child_group:
                child = item["person"]
                child_x = item["x"]
                if item is first_son:
                    role, inferred_sex, order = "first_son_aligned_under_father", "male_candidate", 1
                elif first_son is not None and child_x < first_son_x - alignment_tolerance:
                    order = 2 + left_sons.index(item)
                    role, inferred_sex = f"additional_son_left_of_first_{order}", "male_candidate"
                elif first_son is not None and child_x > first_son_x + alignment_tolerance:
                    order = 1 + right_daughters.index(item)
                    role, inferred_sex = f"daughter_right_of_sons_{order}", "female_candidate"
                elif first_son is None and child_x < parent_x - alignment_tolerance:
                    role, inferred_sex, order = "son_left_of_alignment_first_son_not_found", "male_candidate", None
                elif child_x > parent_x + alignment_tolerance:
                    role, inferred_sex, order = "daughter_right_of_father_axis", "female_candidate", None
                else:
                    role, inferred_sex, order = "child_near_father_axis_unresolved", "unknown", None

                ambiguous = item["near_branch_boundary"]
                suggestions.append({
                    "relationship_id": f"R{len(suggestions)+1:04d}",
                    "type": "possible_parent_child",
                    "parent_candidate_id": parent_id,
                    "parent_name_hanja_candidate": parent.get("name_hanja_candidate"),
                    "candidate_parent_ids": [],
                    "child_candidate_id": child.get("person_id"),
                    "child_name_hanja_candidate": child.get("name_hanja_candidate"),
                    "relationship_basis": "successive_row_branch_and_user_position_rule",
                    "placement_role": role,
                    "inferred_child_sex": inferred_sex,
                    "child_order": order,
                    "parent_center_x": round(parent_x, 2),
                    "child_center_x": round(child_x, 2),
                    "horizontal_distance_px": round(abs(child_x - parent_x), 2),
                    "branch_bounds_x": [round(float(branch["left_bound"]), 2), round(float(branch["right_bound"]), 2)],
                    "evidence_text": f"{previous['row_id']} -> {current['row_id']}; parent branch x={branch['left_bound']:.1f}..{branch['right_bound']:.1f}",
                    "source_row_ids": [previous["row_id"], current["row_id"]],
                    "confidence": 0.65 if not ambiguous and (first_son is not None or inferred_sex != "unknown") else 0.4,
                    "review_status": "needs_review",
                    "warning": "Inferred from the user-provided layout rule; verify against the original genealogy page." if not ambiguous else "Child is near a parent-branch boundary; parent assignment needs review.",
                })

    return suggestions


def ocr_one_image(path: Path, args: argparse.Namespace, output_dir: Path, paddle_ocr: Any = None) -> dict[str, Any]:
    page_started = time.perf_counter()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    image_h, image_w = image.shape[:2]
    if args.roi:
        roi = parse_roi(args.roi, image_w, image_h)
        roi_method = "manual"
    elif args.no_auto_roi:
        roi = (0, 0, image_w, image_h)
        roi_method = "full_image"
    else:
        roi = detect_table_roi(image)
        roi_method = "detected" if roi else "full_image_fallback"
        roi = roi or (0, 0, image_w, image_h)

    x, y, width, height = roi
    table = image[y:y+height, x:x+width]
    boundaries = detect_horizontal_boundaries(table, args.rows)
    page_dir = output_dir / path.stem
    rows_dir, columns_dir = page_dir / "rows", page_dir / "columns"
    rows_dir.mkdir(parents=True, exist_ok=True)
    columns_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(page_dir / "table_roi.jpg"), table)

    debug_image = table.copy()
    all_rows, legacy_blocks, all_people = [], [], []
    paddle_metrics = {
        "row_inferences": 0, "name_reused_from_row": 0,
        "name_fallback_regions": 0, "name_fallback_inferences": 0,
    }
    line_margin = 3
    for row_index, (top_boundary, bottom_boundary) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        top = min(height - 1, top_boundary.y + (line_margin if row_index > 1 else 2))
        bottom = max(top + 1, bottom_boundary.y - (line_margin if row_index < len(boundaries) - 1 else 2))
        band = table[top:bottom, :]
        if band.size == 0:
            continue
        row_id = f"{path.stem}_row_{row_index:02d}"
        cv2.imwrite(str(rows_dir / f"{row_id}.png"), band)
        band_text, band_confidence, prepared, tokens = extract_text_and_confidence(
            band, args.scale, args.preprocess, paddle_ocr=paddle_ocr,
        )
        paddle_metrics["row_inferences"] += 1
        cv2.imwrite(str(rows_dir / f"{row_id}_ocr_input.png"), prepared)

        regions = detect_vertical_columns(band, args.column_ink_ratio, args.min_column_width)
        columns = build_column_records(tokens, regions, band, row_id, x, y+top, bottom-top, columns_dir)
        for left, right in regions:
            cv2.rectangle(debug_image, (left, top), (right, bottom), (255, 0, 0), 1)

        generation = parse_generation(band_text + "\n" + "\n".join(col["text"] for col in columns))
        row = {
            "row_id": row_id, "row_number": row_index,
            "bbox": {"x": x, "y": y+top, "width": width, "height": bottom-top},
            "band_text": band_text, "band_confidence": band_confidence,
            "generation_text": generation.get("generation_text") if generation else None,
            "generation_number": generation.get("generation_number") if generation else None,
            "generation_matches": generation.get("all_matches", []) if generation else [],
            "columns": columns, "person_candidates": [], "rule_mentions": [],
        }
        # Detect prominent name columns from the printed glyph geometry. This
        # catches large names even when row OCR misses them.
        name_regions = detect_large_printed_name_regions(
            band, x, y + top,
            min_component_width=args.person_min_component_width,
            min_component_height=args.person_min_component_height,
            min_component_area=args.person_min_component_area,
            x_cluster_tolerance=args.person_x_cluster_tolerance,
            right_margin_exclusion=args.person_right_margin_exclusion,
            min_vertical_glyph_gap=args.person_min_vertical_glyph_gap,
        )
        for region_index, geometry in enumerate(name_regions, start=1):
            matched_column = find_matching_ocr_column(geometry, columns)
            name_crop = crop_name_region(image, geometry["bbox"], args.name_crop_padding)
            source_column_id = f"{row_id}_name_region_{region_index:02d}"
            image_file_path = columns_dir / f"{source_column_id}.png"
            image_file = str(image_file_path)
            ocr_variants: list[dict[str, Any]] = []
            best_text = ""

            row_text = clean_hanzi_text((matched_column or {}).get("text", ""))
            row_confidence = (matched_column or {}).get("mean_confidence")
            row_is_usable = (
                2 <= len(row_text) <= 4
                and row_confidence is not None
                and float(row_confidence) >= args.paddle_name_min_confidence
            )
            if row_is_usable:
                # Reuse the page-row inference result; no extra model call.
                best_text = row_text
                ocr_variants.append({
                    "variant": "row_ocr_reuse", "engine": "paddleocr",
                    "language": args.paddle_lang, "model": args.paddle_version,
                    "text": (matched_column or {}).get("text", ""),
                    "hanja_text": row_text, "mean_confidence": row_confidence,
                    "character_count": len(row_text), "status": "reused_from_row_ocr",
                })
                paddle_metrics["name_reused_from_row"] += 1
            else:
                # Name crop inference is only a fallback. It starts with
                # CLAHE and expands to other variants only if still weak.
                best_text, ocr_variants, _ = run_name_ocr_variants(
                    image, geometry["bbox"], scale=max(args.scale, 3.0),
                    padding=args.name_crop_padding,
                    paddle_ocr=paddle_ocr,
                    paddle_min_confidence=args.paddle_name_min_confidence,
                )
                paddle_metrics["name_fallback_regions"] += 1
                paddle_metrics["name_fallback_inferences"] += len(ocr_variants)
                if matched_column and matched_column.get("text"):
                    ocr_variants.insert(0, {
                        "variant": "row_ocr_reference", "engine": "paddleocr",
                        "language": args.paddle_lang, "model": args.paddle_version,
                        "text": matched_column.get("text", ""),
                        "hanja_text": row_text,
                        "mean_confidence": row_confidence,
                        "character_count": len(row_text), "status": "reference_only",
                    })
            cv2.imwrite(str(image_file_path), name_crop)
            usable_variants = [v for v in ocr_variants if v.get("hanja_text")]
            ranked_variants = sorted(
                usable_variants,
                key=lambda v: float(v.get("mean_confidence") or 0),
                reverse=True,
            )
            hanzi_text = best_text or (ranked_variants[0]["hanja_text"] if ranked_variants else "")
            best_conf_variant = next((v for v in ocr_variants if v.get("hanja_text") == hanzi_text), None)
            column_confidence = best_conf_variant.get("mean_confidence") if best_conf_variant else None
            if any(v.get("status") == "reused_from_row_ocr" for v in ocr_variants):
                ocr_status = "row_ocr_reused"
            elif usable_variants:
                ocr_status = "name_crop_staged_fallback"
            else:
                ocr_status = "geometry_only_manual_review"
            raw_ocr_text = hanzi_text
            candidate = {
                "name_hanja_candidate": hanzi_text,
                "evidence_text": raw_ocr_text,
                "source_column_id": source_column_id,
                "source_row_id": row_id,
                "bbox": geometry["bbox"],
                "image_file": image_file,
                "ocr_variants": ocr_variants,
                "ranked_ocr_hypotheses": [
                    {"text": v["hanja_text"], "variant": v["variant"], "confidence": v.get("mean_confidence")}
                    for v in ranked_variants
                ],
                "best_ocr_variant": best_conf_variant.get("variant") if best_conf_variant else None,
                "ocr_confidence": column_confidence,
                "recognition_status": "ocr_text_available" if hanzi_text else "manual_transcription_required",
                "rule_class": "large_glyph_column_geometry",
                "candidate_type": "geometry_detected_person_name_region",
                "geometry": {
                    "component_count": geometry["component_count"],
                    "median_component_width": geometry["median_component_width"],
                    "median_component_height": geometry["median_component_height"],
                    "components": geometry["components"],
                },
                "ocr_status": ocr_status,
                "review_status": "needs_review",
            }
            candidate["person_id"] = f"{path.stem}_P{len(all_people)+1:04d}"
            candidate["source_page"] = path.name
            candidate["generation_number"] = row["generation_number"]
            candidate["transcribed_name_hanja"] = None
            candidate["transcription_status"] = "pending_manual_verification"
            # Add a visible numbered outline to layout_debug.jpg.
            person_box = geometry["bbox"]
            px1 = max(0, int(person_box["x"] - x))
            py1 = max(0, int(person_box["y"] - y))
            px2 = min(width - 1, px1 + int(person_box["width"]))
            py2 = min(height - 1, py1 + int(person_box["height"]))
            cv2.rectangle(debug_image, (px1, py1), (px2, py2), (0, 140, 255), 2)
            cv2.putText(
                debug_image, f"P{len(all_people)+1}", (px1, max(12, py1 - 3)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 80, 255), 1, cv2.LINE_AA
            )
            # This is a geometric ranking score, not a probability that the name
            # or its OCR transcription is correct.
            candidate["detection_score"] = round(
                min(1.0, 0.45 + geometry["component_count"] * 0.08
                    + geometry["median_component_height"] / 100.0), 3
            )
            row["person_candidates"].append(candidate)
            all_people.append(candidate)
        row["rule_mentions"] = parse_rule_mentions(row)
        all_rows.append(row)
        legacy_blocks.append({
            "block_id": row_id, "page": path.name, "band": row_index,
            "bbox": row["bbox"], "text": band_text, "mean_confidence": band_confidence,
        })

    relationships = parse_relationships(all_rows, width, table_x=x)
    for boundary in boundaries[1:-1]:
        color = (0, 180, 0) if boundary.detected else (0, 0, 255)
        cv2.line(debug_image, (0, boundary.y), (width-1, boundary.y), color, 2)
    cv2.imwrite(str(page_dir / "layout_debug.jpg"), debug_image)

    return {
        "source_image": str(path), "image_size": {"width": image_w, "height": image_h},
        "table_roi": {"x": x, "y": y, "width": width, "height": height}, "roi_method": roi_method,
        "ocr_engine": "paddleocr",
        "ocr_language": args.paddle_lang,
        "ocr_model": args.paddle_version,
        "elapsed_seconds": round(time.perf_counter() - page_started, 3),
        "paddle_metrics": paddle_metrics,
        "rows_expected": args.rows,
        "row_boundaries": [asdict(item) for item in boundaries], "rows": all_rows,
        "blocks": legacy_blocks, "people_candidates": all_people,
        "relationship_candidates": relationships, "page_output_dir": str(page_dir),
    }


def collect_images(inputs: list[str]) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
    found = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            found.extend(item for item in path.rglob("*") if item.suffix.lower() in extensions)
        elif path.is_file() and path.suffix.lower() in extensions:
            found.append(path)
        else:
            print(f"[WARN] Skipping unsupported or missing input: {path}", file=sys.stderr)
    return sorted(set(found), key=lambda item: str(item).lower())


def initialize_paddle_ocr(args: argparse.Namespace) -> Any:
    """Initialize PaddleOCR 3.x once; its first run may download model weights."""
    try:
        import paddle
        import paddleocr
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR is not installed. Follow the PaddleOCR 3.x CPU install steps in README.md."
        ) from exc
    try:
        print(
            f"[PADDLE] paddleocr={getattr(paddleocr, '__version__', 'unknown')} "
            f"paddlepaddle={getattr(paddle, '__version__', 'unknown')} "
            f"model={args.paddle_version} lang={args.paddle_lang} device={args.paddle_device} "
            f"oneDNN={'on' if args.paddle_enable_mkldnn else 'off'}"
        )
        return PaddleOCR(
            lang=args.paddle_lang,
            ocr_version=args.paddle_version,
            device=args.paddle_device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            cpu_threads=args.paddle_cpu_threads,
            # PaddlePaddle 3.3.x has a known CPU PIR/oneDNN inference bug.
            # Keep oneDNN disabled by default; opt in only after confirming
            # that the installed PaddlePaddle build contains the upstream fix.
            enable_mkldnn=args.paddle_enable_mkldnn,
        )
    except Exception as exc:
        raise RuntimeError(
            "PaddleOCR 초기화에 실패했습니다. PaddleOCR/PaddlePaddle 버전과 모델 다운로드 상태를 확인하세요. "
            f"원인: {type(exc).__name__}: {exc}"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-free jokbo OCR using PaddleOCR with rule-based genealogy extraction.")
    parser.add_argument("inputs", nargs="+", help="Input image files or directories")
    parser.add_argument("-o", "--output", default="jokbo-output", help="Output directory")
    parser.add_argument("--paddle-lang", default="chinese_cht", help="PaddleOCR language; default chinese_cht (Traditional Chinese)")
    parser.add_argument("--paddle-version", choices=["PP-OCRv5", "PP-OCRv4"], default="PP-OCRv5",
                        help="PaddleOCR model family; PP-OCRv5 is recommended for Traditional Chinese and vertical text")
    parser.add_argument("--paddle-device", default="cpu", help="Paddle device, e.g. cpu or gpu:0")
    parser.add_argument("--paddle-cpu-threads", type=int, default=4, help="Paddle CPU inference threads")
    parser.add_argument(
        "--paddle-name-min-confidence", type=float, default=70.0,
        help="Minimum Paddle confidence for reusing row OCR / stopping staged name fallback (default 70)",
    )
    parser.add_argument(
        "--paddle-enable-mkldnn", action="store_true", default=False,
        help="Enable Paddle oneDNN CPU acceleration (disabled by default due to a known PIR compatibility bug)",
    )
    parser.add_argument("--rows", type=int, default=6, help="Expected horizontal row count (default 6)")
    parser.add_argument("--scale", type=float, default=3.0, help="OCR image enlargement factor")
    parser.add_argument("--preprocess", choices=["clahe", "gray", "adaptive", "otsu"], default="clahe")
    parser.add_argument("--roi", help="Manual table ROI x,y,width,height in original image coordinates")
    parser.add_argument("--no-auto-roi", action="store_true", help="Use full image; do not detect the table frame")
    parser.add_argument("--column-ink-ratio", type=float, default=0.08, help="Column projection threshold relative to row height")
    parser.add_argument("--min-column-width", type=int, default=5, help="Minimum detected column width in pixels")
    parser.add_argument("--min-name-font-ratio", type=float, default=1.22, help="Deprecated legacy option; person candidates are now detected from image geometry")
    parser.add_argument("--person-min-component-width", type=int, default=18, help="Minimum width of a large printed component for person-region detection")
    parser.add_argument("--person-min-component-height", type=int, default=18, help="Minimum height of a large printed component for person-region detection")
    parser.add_argument("--person-min-component-area", type=int, default=100, help="Minimum ink area of a large printed component for person-region detection")
    parser.add_argument("--person-x-cluster-tolerance", type=float, default=8.0, help="Horizontal tolerance for grouping large components into a vertical column")
    parser.add_argument("--person-right-margin-exclusion", type=int, default=45, help="Exclude the recurring book-title strip at the far right of a page band")
    parser.add_argument("--person-min-vertical-glyph-gap", type=int, default=27, help="Minimum vertical gap between large glyphs in a person-name column")
    parser.add_argument("--name-crop-padding", type=int, default=7, help="Padding around geometry-detected name crop in source pixels")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rows < 1:
        print("[ERROR] --rows must be at least 1", file=sys.stderr)
        return 2
    if not 0 <= args.paddle_name_min_confidence <= 100:
        print("[ERROR] --paddle-name-min-confidence must be between 0 and 100", file=sys.stderr)
        return 2
    images = collect_images(args.inputs)
    if not images:
        print("[ERROR] No supported image files found.", file=sys.stderr)
        return 2
    output_dir = Path(args.output).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        load_ocr_output(output_dir)
        if len({image.stem for image in images}) != len(images):
            raise ValueError("같은 파일 stem을 가진 스캔은 서로 다른 출력 폴더에 저장하세요.")
        for image_path in images:
            check_page_target(output_dir, image_path)
        paddle_ocr = initialize_paddle_ocr(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    results = []
    for image_path in images:
        print(f"[OCR:paddleocr] {image_path}")
        try:
            result = ocr_one_image(image_path, args, output_dir, paddle_ocr)
            save_page_result(output_dir, result)
            results.append(result)
            print(
                f"[OK:paddleocr] {image_path.name}: {len(result['rows'])} rows, "
                f"{sum(len(row['columns']) for row in result['rows'])} OCR columns, "
                f"{len(result['people_candidates'])} person candidates, "
                f"{len(result['relationship_candidates'])} relationship candidates, "
                f"{result['elapsed_seconds']:.2f}s"
            )
            metrics = result.get("paddle_metrics") or {}
            total_calls = metrics.get("row_inferences", 0) + metrics.get("name_fallback_inferences", 0)
            print(
                f"[PADDLE-STATS] calls={total_calls} "
                f"(row={metrics.get('row_inferences', 0)}, "
                f"name_reused={metrics.get('name_reused_from_row', 0)}, "
                f"fallback_regions={metrics.get('name_fallback_regions', 0)}, "
                f"fallback_calls={metrics.get('name_fallback_inferences', 0)})"
            )
        except Exception as exc:
            print(f"[ERROR:paddleocr] {image_path}: {exc}", file=sys.stderr)

    if not results:
        print("[ERROR] No pages were processed; existing page JSON files were left unchanged.", file=sys.stderr)
        return 1
    try:
        _, _, _, warnings = load_ocr_output(output_dir)
        for warning in warnings:
            print(f"[WARN] {warning}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[ERROR] OCR output could not be loaded: {exc}", file=sys.stderr)
        return 2

    print(f"\nDone. No LLM/API was used. Results: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
