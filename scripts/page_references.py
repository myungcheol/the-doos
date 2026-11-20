"""Extract page-reference candidates; resolve only explicit references and names."""
import re
from pathlib import Path

REFERENCE = re.compile(r'^(上|下|F)([0-9]{1,3})$')


def extract_references(ocr, people, scan_dir):
    references = []
    for region in ocr['regions']:
        match = REFERENCE.fullmatch(region['text'].strip())
        if not match or not region.get('polygon'):
            continue
        points = region['polygon']
        bbox = [min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points)]
        x = (bbox[0]+bbox[2])/2
        candidates = [(i,p) for i,p in enumerate(people['candidates'])
                      if p['name_bbox'][0] <= x <= p['name_bbox'][2]
                      and ((match.group(1) in ('下','F') and p['name_bbox'][3] <= bbox[1]) or
                           (match.group(1) == '上' and bbox[3] <= p['name_bbox'][1]))]
        candidates.sort(key=lambda ip: abs((ip[1]['name_bbox'][3] if match.group(1) in ('下','F') else ip[1]['name_bbox'][1]) - (bbox[1] if match.group(1) in ('下','F') else bbox[3])))
        page = int(match.group(2))
        exists = (Path(scan_dir) / f'{page:03}.jpg').is_file()
        references.append({'raw':region['text'], 'bbox':bbox, 'target_page':page,
                           'direction':'up' if match.group(1) == '上' else 'down',
                           'ocr_direction_uncertain':match.group(1) == 'F',
                           'person':candidates[0][0] if candidates else None,
                           'status':'unprocessed' if exists else 'scan_missing', 'needs_review':True})
    return references


def resolve_reference(reference, source_person, target_people):
    if reference['status'] == 'scan_missing':
        return dict(reference)
    if target_people is None:
        return dict(reference, status='unprocessed')
    def name(p):
        return p['name_text'].lstrip('子女女').replace('□','')
    wanted = name(source_person)
    matches = [i for i,p in enumerate(target_people['candidates']) if wanted and name(p) == wanted]
    return dict(reference, status='candidate' if len(matches)==1 else 'ambiguous' if matches else 'name_not_found',
                target_person=matches[0] if len(matches)==1 else None, matches=matches)
