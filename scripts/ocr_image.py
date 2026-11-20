#!/usr/bin/env python3
"""Run the baseline OCR pipeline on one image and save its raw results."""
import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


def vertical_retry_windows(regions, band):
    """Retry columns crossed by horizontal OCR boxes; coordinates are on page."""
    columns = sorted(band['columns'], key=lambda c: c['bbox'][0])
    x0, y0, x1, y1 = band['bbox']
    windows = []
    for index, column in enumerate(columns):
        a, _, b, _ = column['bbox']
        center = (a+b)/2
        crossed = any(len(r['text']) > 1 and
                      max(p[0] for p in r['polygon'])-min(p[0] for p in r['polygon']) >
                      (max(p[1] for p in r['polygon'])-min(p[1] for p in r['polygon'])) * 1.5 and
                      min(p[0] for p in r['polygon']) <= center <= max(p[0] for p in r['polygon'])
                      for r in regions)
        if crossed:
            left = max(x0, a-2, (columns[index-1]['bbox'][2]+a)//2 if index else x0)
            right = min(x1, b+2, (b+columns[index+1]['bbox'][0])//2 if index+1 < len(columns) else x1)
            windows.append([left, y0, right, y1])
    return windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--layout', type=Path, help='OCR each detected band instead of the whole image')
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error(f'image not found: {args.image}')
    if args.image.resolve() == args.output.resolve():
        parser.error('output must not overwrite the input image')

    from PIL import Image
    from paddleocr import PaddleOCR
    import cv2

    config = dict(device='cpu', lang='chinese_cht', ocr_version='PP-OCRv5',
                  use_doc_orientation_classify=False, use_doc_unwarping=False,
                  use_textline_orientation=False)
    started = time.perf_counter()
    ocr = PaddleOCR(**config)
    inference_started = time.perf_counter()
    with Image.open(args.image) as image:
        width, height = image.size
    if args.layout:
        with args.layout.open(encoding='utf-8') as f:
            layout = json.load(f)
        if layout.get('status') != 'candidate' or (layout.get('width'), layout.get('height')) != (width, height) or not layout.get('bands'):
            raise ValueError('layout failed, is empty, or does not match image dimensions')
        image_data = cv2.imread(str(args.image))
        if image_data is None:
            raise ValueError('cannot load image for band OCR')
        inputs = []
        for band in layout['bands']:
            x0, y0, x1, y1 = band['bbox']
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError('band outside image')
            inputs.append((image_data[y0:y1, x0:x1], x0, y0))
    else:
        inputs = [(str(args.image), 0, 0)]
    regions, retries = [], []
    for band_index, (input_image, x0, y0) in enumerate(inputs):
        results = ocr.predict(input_image, text_rec_score_thresh=0.0)
        if len(results) != 1:
            raise RuntimeError(f'Expected one image result, received {len(results)}')
        result = results[0]
        texts, scores, polys = result['rec_texts'], result['rec_scores'], result['rec_polys']
        if not (len(texts) == len(scores) == len(polys)):
            raise RuntimeError('OCR result lengths do not match')
        for text, score, poly in zip(texts, scores, polys):
            region = {'text': text, 'score': float(score),
                      'polygon': [[int(x) + x0, int(y) + y0] for x, y in poly]}
            if args.layout:
                region['band'] = band_index + 1
            regions.append(region)
    if args.layout:
        for band_index, band in enumerate(layout['bands'], 1):
            original = [r for r in regions if r.get('band') == band_index]
            windows = vertical_retry_windows(original, band)
            if not windows:
                continue
            replaced = [r for r in original if any(
                left <= sum(p[0] for p in r['polygon'])/len(r['polygon']) < right
                for left, _, right, _ in windows)]
            # Retain original OCR for auditing. Re-read the full vertical strips
            # so glyphs above/below a horizontal box keep their reading order.
            reread, empty_windows = [], []
            for left, top, right, bottom in windows:
                crop = cv2.resize(image_data[top:bottom, left:right], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                count_before = len(reread)
                for result in ocr.predict(crop, text_rec_score_thresh=0.0):
                    for text, score, poly in zip(result['rec_texts'], result['rec_scores'], result['rec_polys']):
                        if not text:
                            continue
                        reread.append({'text':text, 'score':float(score), 'band':band_index,
                                        'polygon':[[round(x/2)+left, round(y/2)+top] for x,y in poly],
                                        'recognition_pass':'vertical_column_retry', 'crop_bbox':[left,top,right,bottom]})
                if len(reread) == count_before:
                    empty_windows.append([left,top,right,bottom])
            if not empty_windows:
                replaced_ids = {id(r) for r in replaced}
                regions = [r for r in regions if id(r) not in replaced_ids] + reread
            retries.append({'band':band_index, 'windows':windows, 'original_regions':replaced,
                            'applied':not empty_windows, 'empty_windows':empty_windows})
    elapsed = time.perf_counter()
    output = {
        'schema_version': 1,
        'image': {'path': str(args.image), 'sha256': hashlib.sha256(args.image.read_bytes()).hexdigest(),
                  'width': width, 'height': height},
        'run': {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'argv': sys.argv, 'python': platform.python_version(), 'platform': platform.platform(),
                'paddleocr': version('paddleocr'), 'paddlepaddle': version('paddlepaddle'),
                'paddlex': version('paddlex'), 'config': config,
                'resolved_models': {
                    'detection': ocr._merged_paddlex_config['SubModules']['TextDetection']['model_name'],
                    'recognition': ocr._merged_paddlex_config['SubModules']['TextRecognition']['model_name'],
                }, 'text_rec_score_thresh': 0.0,
                'mode': 'bands_with_vertical_retry' if args.layout else 'whole_image',
                'initialization_seconds': round(inference_started - started, 3),
                'inference_seconds': round(elapsed - inference_started, 3)},
        'regions': regions,
        'vertical_retries': retries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"Saved {len(regions)} regions to {args.output}")


if __name__ == '__main__':
    main()
