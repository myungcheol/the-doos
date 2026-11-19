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
    regions = []
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
                'mode': 'bands' if args.layout else 'whole_image',
                'initialization_seconds': round(inference_started - started, 3),
                'inference_seconds': round(elapsed - inference_started, 3)},
        'regions': regions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"Saved {len(regions)} regions to {args.output}")


if __name__ == '__main__':
    main()
