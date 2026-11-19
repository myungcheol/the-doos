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
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error(f'image not found: {args.image}')
    if args.image.resolve() == args.output.resolve():
        parser.error('output must not overwrite the input image')

    from PIL import Image
    from paddleocr import PaddleOCR

    config = dict(device='cpu', lang='chinese_cht', ocr_version='PP-OCRv5',
                  use_doc_orientation_classify=False, use_doc_unwarping=False,
                  use_textline_orientation=False)
    started = time.perf_counter()
    ocr = PaddleOCR(**config)
    inference_started = time.perf_counter()
    results = ocr.predict(str(args.image), text_rec_score_thresh=0.0)
    elapsed = time.perf_counter()
    if len(results) != 1:
        raise RuntimeError(f'Expected one image result, received {len(results)}')
    result = results[0]
    texts, scores, polys = result['rec_texts'], result['rec_scores'], result['rec_polys']
    if not (len(texts) == len(scores) == len(polys)):
        raise RuntimeError('OCR result lengths do not match')
    with Image.open(args.image) as image:
        width, height = image.size
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
                'initialization_seconds': round(inference_started - started, 3),
                'inference_seconds': round(elapsed - inference_started, 3)},
        'regions': [{'text': text, 'score': float(score), 'polygon': poly.tolist()}
                    for text, score, poly in zip(texts, scores, polys)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"Saved {len(texts)} regions to {args.output}")


if __name__ == '__main__':
    main()
