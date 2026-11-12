"""Conservative table rectification and original-image evidence coordinates."""
from __future__ import annotations

from copy import deepcopy
import math

import cv2
import numpy as np


def transform_points(points, matrix):
    return cv2.perspectiveTransform(np.asarray(points, dtype=np.float64).reshape(1, -1, 2),
                                    np.asarray(matrix, dtype=np.float64))[0]


def transform_box(box, matrix, image_size):
    """Map all four corners, retaining the polygon and a clipped enclosing bbox."""
    x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
    points = transform_points([[x, y], [x+w, y], [x+w, y+h], [x, y+h]], matrix)
    width, height = image_size
    lo = np.maximum([0, 0], np.floor(points.min(axis=0) + 1e-7)).astype(int)
    hi = np.minimum([width, height], np.ceil(points.max(axis=0) - 1e-7)).astype(int)
    lo = np.minimum(lo, [width, height])
    hi = np.maximum(hi, lo)
    return dict(x=int(lo[0]), y=int(lo[1]), width=int(hi[0]-lo[0]), height=int(hi[1]-lo[1])), points.tolist()


def map_evidence(value, inverse, image_size):
    """Map nested row/column/token/name/component boxes without changing text."""
    if isinstance(value, list):
        return [map_evidence(item, inverse, image_size) for item in value]
    if not isinstance(value, dict):
        return value
    result = {k: map_evidence(v, inverse, image_size) for k, v in value.items()}
    for key in ("bbox", "region_bbox"):
        box = value.get(key)
        if isinstance(box, dict) and all(k in box for k in ("x", "y", "width", "height")):
            result["ocr_" + key] = deepcopy(box)
            result[key], result["source_polygon" if key == "bbox" else "source_region_polygon"] = transform_box(
                box, inverse, image_size)
    return result


def layout_evidence(value):
    """Restore saved corrected boxes for layout calculations and recovery."""
    if isinstance(value, list):
        return [layout_evidence(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {k: layout_evidence(v) for k, v in value.items()}
    for key in ("bbox", "region_bbox"):
        if "ocr_" + key in value:
            result[key] = deepcopy(value["ocr_" + key])
    return result


def _quad(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    binary = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 0, 255,
                           cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not width*height*0.22 <= area <= width*height*0.95:
            continue
        approx = cv2.approxPolyDP(contour, 0.015*cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        points = approx.reshape(4, 2).astype(np.float32)
        # Small document tilts only: sorting top/bottom pairs avoids duplicate corners.
        by_y = points[np.argsort(points[:, 1])]
        top, bottom = by_y[:2], by_y[2:]
        tl, tr = top[np.argsort(top[:, 0])]
        bl, br = bottom[np.argsort(bottom[:, 0])]
        q = np.asarray([tl, tr, br, bl], dtype=np.float32)
        horizontal = [np.linalg.norm(tr-tl), np.linalg.norm(br-bl)]
        vertical = [np.linalg.norm(bl-tl), np.linalg.norm(br-tr)]
        if min(horizontal+vertical) < 40 or not 0.4 <= np.mean(horizontal)/np.mean(vertical) <= 1.05:
            continue
        angles = [math.degrees(math.atan2(*(tr-tl)[::-1])), math.degrees(math.atan2(*(br-bl)[::-1]))]
        side_tilts = [math.degrees(math.atan2(*(bl-tl)[::-1]))-90,
                      math.degrees(math.atan2(*(br-tr)[::-1]))-90]
        if max(abs(a) for a in angles+side_tilts) <= 8:
            candidates.append((area, q, horizontal, vertical, angles, side_tilts))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def estimate_skew(image):
    """Require long horizontal lines in at least three separate height bands."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 35, 110)
    lines = cv2.HoughLinesP(edges, 1, np.pi/1800, threshold=max(40, width//8),
                            minLineLength=max(40, int(width*0.30)), maxLineGap=max(12, width//30))
    entries = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = (math.degrees(math.atan2(float(y2-y1), float(x2-x1)))+90) % 180-90
            if abs(angle) <= 8:
                # Hough can join prose strokes into a long apparent line.
                # A table rule must carry dark ink continuously along its length.
                count = max(20, int(abs(x2-x1)))
                xs = np.rint(np.linspace(x1, x2, count)).astype(int)
                ys = np.rint(np.linspace(y1, y2, count)).astype(int)
                samples = np.stack([gray[np.clip(ys+d, 0, height-1), xs] for d in (-2, -1, 0, 1, 2)])
                if np.mean(samples.min(axis=0) < 180) >= 0.85:
                    entries.append((angle, (int(y1)+int(y2))/2))
    if not entries:
        return None, 0
    angle = float(np.median([e[0] for e in entries]))
    inliers = [e for e in entries if abs(e[0]-angle) <= 0.7]
    bands = []
    for _, y in sorted(inliers, key=lambda e: e[1]):
        if not bands or y-bands[-1] > max(6, height*0.015):
            bands.append(y)
    if (len(bands) < 3 or bands[-1]-bands[0] < height*0.2
            or len(inliers) < len(entries)*0.6):
        return None, len(bands)
    return float(np.median([e[0] for e in inliers])), len(bands)


def correct_page_geometry(image, mode="auto", roi=None):
    """Return working image and reversible transform; skip uncertain geometry.

    Auto rectifies a credible trapezoidal table, otherwise deskews parallel
    rules. It does not flatten curved pages or perform learned restoration.
    A manual ROI limits angle estimation and is still specified in source pixels.
    """
    if mode not in {"auto", "deskew", "none"}:
        raise ValueError("Unknown geometry correction mode")
    height, width = image.shape[:2]
    identity = np.eye(3, dtype=np.float64)
    meta = {"mode": mode, "applied": False, "method": "none", "angle_degrees": 0.0,
            "source_to_ocr": identity.tolist(), "ocr_to_source": identity.tolist(),
            "ocr_image_size": {"width": width, "height": height}, "line_bands": 0,
            "reason": "disabled" if mode == "none" else "insufficient_table_lines"}
    if mode == "none":
        return image, meta
    candidate = _quad(image) if roi is None else None
    area_roi = roi
    if area_roi is None and candidate:
        area_roi = cv2.boundingRect(candidate[1])
    if area_roi:
        rx, ry, rw, rh = area_roi
        sample = image[ry:ry+rh, rx:rx+rw]
    else:
        sample = image
    angle, bands = estimate_skew(sample)
    meta["line_bands"] = bands
    if angle is None:
        return image, meta
    meta["angle_degrees"] = round(angle, 5)
    matrix = None
    if mode == "auto" and candidate:
        _, q, horizontal, vertical, angles, sides = candidate
        taper = max(abs(horizontal[0]-horizontal[1])/max(horizontal), abs(vertical[0]-vertical[1])/max(vertical))
        if taper > 0.015 or abs(angles[0]-angles[1]) > 0.5 or abs(sides[0]-sides[1]) > 0.5:
            tw, th = float(np.mean(horizontal)), float(np.mean(vertical))
            tx, ty = q.min(axis=0)
            target = np.float32([[tx, ty], [tx+tw, ty], [tx+tw, ty+th], [tx, ty+th]])
            matrix = cv2.getPerspectiveTransform(q, target)
            meta.update(method="perspective", table_corners_source=q.tolist())
    if matrix is None:
        if abs(angle) < 0.10:
            meta["reason"] = "already_aligned"
            return image, meta
        matrix = np.vstack([cv2.getRotationMatrix2D((width/2, height/2), angle, 1.0), [0, 0, 1]])
        meta["method"] = "deskew"
    # Expand the canvas rather than clipping names near the original page edges.
    corners = np.float64([[0, 0], [width, 0], [width, height], [0, height]])
    denominators = np.c_[corners, np.ones(4)] @ matrix[2]
    if np.any(denominators <= 0.1):
        meta.update(method="none", reason="unsafe_perspective")
        return image, meta
    projected = transform_points(corners, matrix)
    low, high = np.floor(projected.min(axis=0)), np.ceil(projected.max(axis=0))
    size = (high-low).astype(int)
    if np.any(size <= 0) or np.any(size > np.array([width, height])*1.7):
        meta.update(method="none", reason="excessive_canvas_expansion")
        return image, meta
    shift = np.array([[1, 0, -low[0]], [0, 1, -low[1]], [0, 0, 1]])
    matrix = shift @ matrix
    corrected = cv2.warpPerspective(image, matrix, tuple(int(v) for v in size),
                                    flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
                                    borderValue=(255, 255, 255) if image.ndim == 3 else 255)
    meta.update(applied=True, reason="supported_by_table_lines", source_to_ocr=matrix.tolist(),
                ocr_to_source=np.linalg.inv(matrix).tolist(),
                ocr_image_size={"width": int(size[0]), "height": int(size[1])})
    return corrected, meta
