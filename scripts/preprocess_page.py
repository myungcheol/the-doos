#!/usr/bin/env python3
"""Propose ruled page bands and text columns, retaining original pixel coordinates."""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


def deskew(image):
    """Estimate skew from long, nearly horizontal rules; retain all pixels."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    lines = cv2.HoughLinesP(ink, 1, np.pi / 1800, threshold=int(w * .25),
                            minLineLength=int(w * .5), maxLineGap=int(w * .08))
    angles = []
    for x1, y1, x2, y2 in ([] if lines is None else lines[:, 0]):
        dx, dy = int(x2)-int(x1), int(y2)-int(y1)
        if abs(dx) >= w * .5 and abs(dy) <= abs(dx) * .06:
            angles.append(math.degrees(math.atan2(dy * (1 if dx > 0 else -1), abs(dx))))
    identity = [[1., 0., 0.], [0., 1., 0.]]
    if len(angles) < 3:
        return image, {'applied': False, 'reason': 'insufficient horizontal rules', 'angle_degrees': None, 'matrix': identity, 'inverse_matrix': identity}
    angle = float(np.median(angles))
    if np.median(np.abs(np.array(angles) - angle)) > .35:
        return image, {'applied': False, 'reason': 'inconsistent rule angles', 'angle_degrees': angle, 'matrix': identity, 'inverse_matrix': identity}
    if abs(angle) < .15:
        return image, {'applied': False, 'reason': 'angle below 0.15 degrees', 'angle_degrees': angle, 'matrix': identity, 'inverse_matrix': identity}
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
    corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]]) @ matrix.T
    lower, upper = corners.min(axis=0), corners.max(axis=0)
    matrix[:, 2] -= lower
    size = np.ceil(upper-lower).astype(int)
    rotated = cv2.warpAffine(image, matrix, tuple(size), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return rotated, {'applied': True, 'reason': 'estimated from horizontal rules', 'angle_degrees': angle,
                     'matrix': matrix.tolist(), 'inverse_matrix': cv2.invertAffineTransform(matrix).tolist()}


def clusters(values, gap):
    groups = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(float(np.median(group))) for group in groups]


def preprocess(image):
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = []
    vertical = []
    vertical_segments = []
    for threshold in (150, 180, 200):
        line_ink = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
        lines = cv2.HoughLinesP(line_ink, 1, np.pi / 1800, threshold=int(width * .25),
                                minLineLength=int(width * .5), maxLineGap=int(width * .08))
        for line in ([] if lines is None else lines[:, 0]):
            x1, y1, x2, y2 = map(int, line)
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) >= width * .5 and abs(dy) <= abs(dx) * .06:
                horizontal.append((y1 + y2) / 2)
            if abs(dy) >= height * .5 and abs(dx) <= abs(dy) * .06:
                vertical.append((x1 + x2) / 2)
                vertical_segments.append(((x1 + x2) / 2, abs(dy)))
    ys = [y for y in clusters(horizontal, 8) if height * .03 < y < height * .98]
    xs = [x for x in clusters(vertical, 8) if width * .025 < x < width * .975]
    # Prefer the longest ruling segment in a cluster: text strokes can shift
    # a median boundary inward on dense pages such as 005.
    xs = sorted(set(round(max((s for s in vertical_segments if abs(s[0]-x) <= 16),
                              key=lambda s: s[1])[0]) for x in xs))
    if len(xs) < 2 or len(ys) < 2:
        return {'status': 'failed', 'reason': 'page borders or horizontal rules not detected',
                'width': width, 'height': height, 'bands': []}
    left = xs[0]
    # Typical scanned page width is roughly 0.62 times its height; selecting
    # among detected borders is a heuristic and can fail on other page shapes.
    right = min((x for x in xs[1:] if x - left >= width * .5),
                key=lambda x: abs((x-left) - height * .62), default=xs[-1])
    # Ignore tiny doubled border lines; never interpolate missing rules.
    ys = [y for i, y in enumerate(ys) if i == 0 or y - ys[i - 1] > height * .025]
    # Keep the best-supported near-regular sequence as a proposal, retaining
    # ambiguity in warnings. This assumption must be checked on other layouts.
    original_ys = ys[:]
    options = []
    for a in ys:
        for b in ys:
            step = b - a
            if not height * .10 <= step <= height * .20:
                continue
            selected = [y for y in ys if abs((y-a)/step - round((y-a)/step)) < .09]
            options.append((len(selected), -sum(abs((y-a)/step-round((y-a)/step)) for y in selected), selected))
    if options:
        ys = max(options, key=lambda item: item[:2])[2]
    if right - left < width * .5 or len(ys) < 2:
        return {'status': 'failed', 'reason': 'invalid page border geometry',
                'width': width, 'height': height, 'bands': []}
    gaps = np.diff(ys)
    typical_gap = float(np.median(gaps))
    warnings = ['rule and column boundaries are estimates; inspect before use',
                'projection may merge or split columns and detect show-through',
                'frame selection assumes an approximately 0.62 width-to-height ratio']
    if ys != original_ys:
        warnings.append(f'near-regular spacing selected; discarded rule candidates: {sorted(set(original_ys) - set(ys))}')
    if any(gap < typical_gap * .65 or gap > typical_gap * 1.35 for gap in gaps):
        warnings.append('irregular rule spacing: possible missed or false rule; do not use bands without review')
    bands = []
    for top, bottom in zip(ys, ys[1:]):
        # Ignore ruling pixels; leave all bands, including empty ones.
        x0, x1, y0, y1 = left + 4, right - 4, top + 4, bottom - 4
        if x1 <= x0 or y1 <= y0:
            continue
        roi = ink[y0:y1, x0:x1]
        count, labels, stats, _ = cv2.connectedComponentsWithStats(roi, 8)
        mask = np.zeros(roi.shape, dtype=np.uint8)
        for label, (x, y, w, h, area) in enumerate(stats[1:count], 1):
            if 3 <= area and w < roi.shape[1] * .15 and h < roi.shape[0] * .85:
                mask[y:y+h, x:x+w] |= (labels[y:y+h, x:x+w] == label).astype(np.uint8)
        projection = mask.sum(axis=0)
        active = np.flatnonzero(projection >= 3)
        groups = []
        for x in active:
            if not groups or x - groups[-1][-1] > 3:
                groups.append([int(x)])
            else:
                groups[-1].append(int(x))
        columns = []
        for group in groups:
            a, b = group[0], group[-1] + 1
            if mask[:, a:b].sum() < 12:
                continue
            columns.append({'bbox': [x0 + a, y0, x0 + b, y1], 'status': 'candidate'})
        bands.append({'bbox': [x0, y0, x1, y1], 'columns': list(reversed(columns))})
    return {'status': 'candidate', 'width': width, 'height': height,
            'frame': [left, ys[0], right, ys[-1]], 'rule_y': ys, 'bands': bands,
            'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--crop-dir', type=Path, help='save proposed bands as PNGs')
    parser.add_argument('--deskew-output', type=Path, help='write corrected image when correction is applied')
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f'cannot read image: {args.image}')
    if args.output.resolve() == args.image.resolve() or (args.overlay and args.overlay.resolve() in (args.image.resolve(), args.output.resolve())):
        parser.error('image, output and overlay must be different files')
    if args.deskew_output and args.deskew_output.resolve() in (args.image.resolve(), args.output.resolve(), args.overlay.resolve() if args.overlay else args.image.resolve()):
        parser.error('corrected image must not overwrite input or other output')
    if args.deskew_output:
        image, rotation = deskew(image)
        if rotation['applied']:
            ok, encoded = cv2.imencode(args.deskew_output.suffix, image)
            if not ok:
                raise RuntimeError('corrected image encoding failed')
            args.deskew_output.parent.mkdir(parents=True, exist_ok=True)
            with args.deskew_output.open('xb') as f:
                f.write(encoded.tobytes())
    else:
        rotation = {'applied': False, 'reason': 'not requested'}
    result = preprocess(image)
    result['rotation'] = rotation
    result['image'] = str(args.image)
    result['coordinates'] = 'processed image pixels; bbox [left, top, right, bottom), origin top-left'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    if args.crop_dir:
        args.crop_dir.mkdir(parents=True, exist_ok=True)
        for i, band in enumerate(result['bands']):
            x0, y0, x1, y1 = band['bbox']
            ok, encoded = cv2.imencode('.png', image[y0:y1, x0:x1])
            if not ok:
                raise RuntimeError('crop encoding failed')
            with (args.crop_dir / f'band-{i + 1:02}.png').open('xb') as f:
                f.write(encoded.tobytes())
    if args.overlay:
        for band in result['bands']:
            x0, y0, x1, y1 = band['bbox']
            cv2.rectangle(image, (x0, y0), (x1, y1), (0, 0, 255), 2)
            for column in band['columns']:
                x0, y0, x1, y1 = column['bbox']
                cv2.rectangle(image, (x0, y0), (x1, y1), (255, 0, 0), 1)
        ok, encoded = cv2.imencode(args.overlay.suffix, image)
        if not ok:
            raise RuntimeError('overlay encoding failed')
        args.overlay.parent.mkdir(parents=True, exist_ok=True)
        with args.overlay.open('xb') as f:
            f.write(encoded.tobytes())
    print(f"{result['status']}: {len(result['bands'])} bands -> {args.output}")
    return 0 if result['status'] != 'failed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
