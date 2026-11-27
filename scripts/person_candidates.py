#!/usr/bin/env python3
"""Extract review-only person and left-hand information candidates from OCR JSON."""
import argparse
import json
import re
import statistics
import math
from pathlib import Path

HAN = r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]'
NAME = re.compile(r'^[子女女](' + HAN + r'{1,3})$')
BARE_NAME = re.compile('^' + HAN + r'{1,3}$')


def dimensions(region):
    """Measure oriented OCR edges, avoiding inflated bounds of tilted glyphs."""
    p = region['polygon']
    return ((math.dist(p[0], p[1]) + math.dist(p[2], p[3])) / 2,
            (math.dist(p[1], p[2]) + math.dist(p[3], p[0])) / 2)


def name_regions(regions):
    """Use typography as well as markers; all returned names require review."""
    widths = [dimensions(r)[0] for r in regions
              if len(r['text']) >= 4 and r['bbox'][3]-r['bbox'][1] > r['bbox'][2]-r['bbox'][0]]
    small = statistics.median(widths) if widths else 20
    names = []
    used = []
    # Short horizontal OCR boxes may contain the final glyphs of adjacent
    # vertical names. Split only with aligned name stems above each glyph;
    # equal-width glyph boxes are estimates and retain the original OCR source.
    expanded = []
    for r in regions:
        x0, y0, x1, y1 = r['bbox']
        count = len(r['text'])
        if BARE_NAME.fullmatch(r['text']) and count >= 2 and x1-x0 > (y1-y0)*1.4:
            step = (x1-x0)/count
            cells = []
            for i, char in enumerate(r['text']):
                a, c = x0+i*step, x0+(i+1)*step
                stems = [s for s in regions if s is not r and (s['text'] in ('子','女','女') or NAME.fullmatch(s['text']))
                         and abs((s['bbox'][0]+s['bbox'][2])/2-(a+c)/2) <= step*.45
                         and 0 < y0-s['bbox'][1] < step*4]
                if stems:
                    cells.append(dict(r, text=char, bbox=[a,y0,c,y1],
                                      polygon=[[a,y0],[c,y0],[c,y1],[a,y1]],
                                      geometry_estimated=True, source_ocr_text=r['text'], source_ocr_bbox=r['bbox']))
            if len(cells)==count:
                expanded.extend(cells)
                continue
        expanded.append(r)
    regions = expanded
    for r in regions:
        if r['bbox'] in used:
            continue
        rw, rh = dimensions(r)
        marker_seed = r['text'] in ('子', '女', '女', '子系') or (NAME.fullmatch(r['text']) and len(r['text']) < 4)
        bare_seed = (BARE_NAME.fullmatch(r['text']) and len(r['text']) == 1
                     and r['text'] not in ('子', '女', '女', '世') and rw >= small*1.25 and rh >= small*1.15)
        if not (marker_seed or bare_seed):
            continue
        parts = [r]
        x0, y0, x1, y1 = r['bbox']
        for s in sorted(regions, key=lambda v: v['bbox'][1]):
            a, b, c, d = s['bbox']
            if (s is not r and s['bbox'] not in used and BARE_NAME.fullmatch(s['text']) and len(s['text']) <= 3
                and b > parts[-1]['bbox'][1] and b >= y1-(x1-x0)*.5 and b-y1 <= (x1-x0)*1.5
                and abs((a+c)/2-(x0+x1)/2) <= (x1-x0)*.35
                and c-a >= (x1-x0)*.7 and (d-b)/len(s['text']) >= (x1-x0)*.7
                and sum(len(p['text']) for p in parts)+len(s['text']) <= 4):
                parts.append(s)
                y1 = d
        if len(parts) > 1:
            bounds = [min(p['bbox'][0] for p in parts), y0, max(p['bbox'][2] for p in parts), y1]
            names.append(dict(r, text=''.join(p['text'] for p in parts), bbox=bounds,
                              detection_reason='split_marker' if marker_seed else 'split_large_text_without_marker',
                              source_boxes=[p.get('source_ocr_bbox',p['bbox']) for p in parts],
                              geometry_estimated=any(p.get('geometry_estimated',False) for p in parts),
                              source_regions=parts))
            used.extend(p['bbox'] for p in parts)
    for r in regions:
        if r['bbox'] in used:
            continue
        text = r['text']
        w, h = dimensions(r)
        if text == '子系':
            continue
        if NAME.fullmatch(text):
            names.append(dict(r, detection_reason='marker'))
        elif (BARE_NAME.fullmatch(text) and text not in ('子', '女', '女', '祖始', '始祖')
              and not text.endswith(('世', '氏', '譜', '卷'))
              and w <= h * 1.1 and w >= small * 1.25 and h / len(text) >= small * 1.15):
            names.append(dict(r, detection_reason='large_text_without_marker'))
    return names


def box(region):
    points = region['polygon']
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def vertical_reading_order(regions):
    """Group slightly wandering OCR boxes into columns, then read top-down."""
    columns = []
    for region in sorted(regions, key=lambda r: -(r['bbox'][0] + r['bbox'][2]) / 2):
        x0, _, x1, _ = region['bbox']
        center = (x0 + x1) / 2
        match = next((column for column in columns
                      if abs(center - column['center']) <= max(x1-x0, column['width']) * .65), None)
        if match is None:
            columns.append({'center': center, 'width': x1-x0, 'regions': [region]})
        else:
            match['regions'].append(region)
            count = len(match['regions'])
            match['center'] = (match['center'] * (count-1) + center) / count
            match['width'] = max(match['width'], x1-x0)
    ordered = []
    for column in sorted(columns, key=lambda c: -c['center']):
        ordered.extend(sorted(column['regions'], key=lambda r: (r['bbox'][1], r['bbox'][0])))
    return ordered


def extract(ocr, layout):
    regions = [dict(region, bbox=box(region)) for region in ocr['regions'] if region['polygon']]
    candidates = []
    for band_index, band in enumerate(layout['bands']):
        bx0, by0, bx1, by1 = band['bbox']
        inside = [r for r in regions if r.get('band', band_index + 1) == band_index + 1 and bx0 <= (r['bbox'][0]+r['bbox'][2])/2 < bx1
                  and by0 <= (r['bbox'][1]+r['bbox'][3])/2 < by1]
        names = sorted(name_regions(inside),
                       key=lambda r: r['bbox'][0], reverse=True)
        for i, name in enumerate(names):
            left_limit = names[i+1]['bbox'][2] if i+1 < len(names) else bx0
            name_boxes = [b for n in names for b in n.get('source_boxes', [n['bbox']])]
            info = [r for r in inside if r['bbox'] not in name_boxes and left_limit <= r['bbox'][0]
                    and r['bbox'][2] <= name['bbox'][0] and not NAME.fullmatch(r['text'])]
            info = vertical_reading_order(info)
            name_text = name['text'][2:] if name['text'].startswith('子系') else name['text']
            rw, rh = dimensions(name)
            expected_chars = min(4, max(len(name_text), round(rh / max(rw, 1))))
            missing_chars = expected_chars - len(name_text) if name['detection_reason'] == 'marker' else 0
            if missing_chars:
                name_text += '□' * missing_chars
            candidates.append({'band': band_index + 1,
                               'name_text': name_text,
                               'raw_name_text': name['text'],
                               'name_bbox': name['bbox'],
                               'marker': '子系' if name['text'].startswith('子系') else name['text'][0] if name['detection_reason'] in ('marker', 'split_marker') else None,
                               'detection_reason': name['detection_reason'],
                               'lineage_marker': '子系' if name['text'].startswith('子系') else None,
                               'geometry_estimated': name.get('geometry_estimated', False),
                               'missing_name_characters': missing_chars,
                               'source_regions': name.get('source_regions', [name]),
                               'needs_review': True, 'information_candidates': info})
    return {'status': 'candidate', 'image': ocr['image'], 'candidates': candidates,
            'warnings': ['OCR and layout errors propagate; ownership is unverified',
                         'name-shaped text in body may be misclassified']}


def analyze(ocr, layout, scan_dir):
    result = extract(ocr, layout)
    from information_parser import enrich
    result = enrich(result)
    from spouse_parser import enrich_spouses
    result = enrich_spouses(result)
    from korean_explanations import enrich_explanations
    result = enrich_explanations(result)
    from parent_candidates import extract_parent_candidates
    result = extract_parent_candidates(result)
    from page_references import extract_references
    result['page_references'] = extract_references(ocr, result, scan_dir)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ocr', type=Path)
    parser.add_argument('layout', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with args.ocr.open(encoding='utf-8') as f:
        ocr = json.load(f)
    with args.layout.open(encoding='utf-8') as f:
        layout = json.load(f)
    result = analyze(ocr, layout, Path('scan/genealogy'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"{len(result['candidates'])} candidates -> {args.output}")


if __name__ == '__main__':
    main()
