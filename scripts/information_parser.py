#!/usr/bin/env python3
"""Conservative, source-preserving information candidates; no era conversion."""
import argparse
import json
import re
from pathlib import Path

NUM = r'[0-9〇零一二三四五六七八九十百千廿卅元]+'
CYCLE = r'[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]'
DATE = re.compile(r'(?P<year>' + NUM + r'年(?:' + CYCLE + r')?|' + CYCLE + r'年?)?'
                  r'(?P<leap>閏|闰)?(?P<month>' + NUM + r'月)?(?P<day>初?' + NUM + r'日)?')
OFFICES = ('兵部尚書', '中書舍人', '左議政', '右議政', '領議政', '判書', '參判', '郡守', '縣監', '縣令', '知郡事', '學士', '學正', '將軍')
EDUCATION = ('進士', '生員', '文科', '武科', '及第', '登科')
EVENTS = {'生': 'birth', '卒': 'death', '歿': 'death', '殁': 'death', '逝': 'death'}


def number(text):
    if text is None:
        return None
    text = text.replace('初', '').replace('廿', '二十').replace('卅', '三十')
    if text.isdigit():
        return int(text)
    digits = dict(zip('〇零一二三四五六七八九元', (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 1)))
    if all(c in digits for c in text):
        return int(''.join(str(digits[c]) for c in text))
    total = current = 0
    for c in text:
        if c in digits:
            current = digits[c]
        elif c in '十百千':
            total += (current or 1) * {'十': 10, '百': 100, '千': 1000}[c]
            current = 0
        else:
            return None
    return total + current


def parse_candidate(person, owner_id, resolve_scopes=True):
    regions = person['information_candidates']
    text = ''.join(r['text'] for r in regions)
    offsets = []
    cursor = 0
    for index, region in enumerate(regions):
        offsets.append((cursor, cursor + len(region['text']), index))
        cursor += len(region['text'])
    claimed = [False] * len(text)
    items = []

    def emit(kind, start, end, **extra):
        refs = [{'region_index': i, 'start': max(start, a)-a, 'end': min(end, b)-a,
                 'bbox': regions[i]['bbox']} for a, b, i in offsets if a < end and start < b]
        items.append({'kind': kind, 'owner_id': owner_id, 'raw': text[start:end],
                      'start': start, 'end': end, 'source_refs': refs, 'needs_review': True, **extra})
        claimed[start:end] = [True] * (end-start)

    # Keep A's whole description, but attach dates inside each spouse scope to
    # a separate temporary subject. T009 builds person/marriage candidates.
    markers = list(re.finditer(r'[配妾](?:夫[人入])?|夫[人入]', text)) if resolve_scopes else []
    limit = markers[0].start() if markers else len(text)
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index+1].start() if index+1 < len(markers) else len(text)
        subject_id = f'{owner_id}:spouse-{index}'
        identity = re.match(r'[\u3400-\u9fff]{1,8}?氏', text[marker.end():end])
        label = identity.group() if identity else '姓名未詳'
        relation = 'concubine' if marker.group().startswith('妾') else 'spouse'
        scoped_regions, mapping = [], []
        for a, b, i in offsets:
            if a < end and start < b:
                left, right = max(start,a)-a, min(end,b)-a
                scoped_regions.append(dict(regions[i], text=regions[i]['text'][left:right]))
                mapping.append((i,left))
        nested = parse_candidate({'information_candidates': scoped_regions}, subject_id, resolve_scopes=False)
        for item in nested['items']:
            item['start'] += start
            item['end'] += start
            item['source_owner_id'] = owner_id
            for ref in item['source_refs']:
                original_index, shift = mapping[ref['region_index']]
                ref['region_index'] = original_index
                ref['start'] += shift
                ref['end'] += shift
        emit('spouse_information', start, end, subject={'id':subject_id, 'label':label,
             'relation_type':relation, 'marker_raw':marker.group()}, items=nested['items'])

    for match in DATE.finditer(text[:limit]):
        if not match.group() or not any(match.group(k) for k in ('year', 'month', 'day')):
            continue
        a, b = match.span()
        before = text[a-1:a] if a else ''
        after = text[b:b+1]
        # 生員 is a credential; 卒業 is not a death marker.
        suffix = EVENTS.get(after) if text[b:b+2] not in ('生員', '卒業') else None
        prefix = EVENTS.get(before) if text[max(0,a-1):a+1] not in ('生員', '卒業') else None
        if a and claimed[a-1]:
            prefix = None
        burial = next((word for word in ('遷葬', '移葬', '葬') if text[:a].endswith(word)), None)
        burial_suffix = next((word for word in ('遷葬', '移葬', '葬') if text[b:limit].startswith(word)), None)
        if burial:
            kind, start, end = 'burial_date', a-len(burial), b
        elif burial_suffix:
            kind, start, end = 'burial_date', a, b+len(burial_suffix)
        elif suffix or prefix:
            kind = 'ambiguous_event' if prefix and suffix and prefix != suffix else suffix or prefix
            start, end = (a-1 if prefix else a), (b+1 if suffix else b)
        else:
            continue
        if any(claimed[start:end]):
            continue
        year, month, day = match.group('year', 'month', 'day')
        parts = [label for label, value in (('year', year), ('month', month), ('day', day)) if value]
        month_value = number(month[:-1]) if month else None
        day_value = number(day[:-1]) if day else None
        emit(kind, start, end, date={'year_text': year, 'month_text': month, 'day_text': day,
                                    'month': month_value, 'day': day_value,
                                    'precision': '_'.join(parts), 'leap_month': True if match.group('leap') else None,
                                    'gregorian_year': None, 'calendar': 'unknown', 'conversion_status': 'not_attempted'},
             warnings=['date components out of range'] if (month_value is not None and not 1 <= month_value <= 12) or (day_value is not None and not 1 <= day_value <= 30) else [])

    for kind, words in (('office', OFFICES), ('education', EDUCATION)):
        for word in sorted(words, key=len, reverse=True):
            for match in re.finditer(word, text[:limit]):
                a, b = match.span()
                if not any(claimed[a:b]):
                    emit(kind, a, b)

    # Preserve burial notes without interpreting locations or inferring dates.
    for match in re.finditer(r'(?:遷葬|移葬|葬|墓|塋|墳)[^。○〇\n]*', text[:limit]):
        a, b = match.span()
        while a < b:
            if claimed[a]:
                a += 1
                continue
            end = a+1
            while end < b and not claimed[end]:
                end += 1
            emit('burial_note', a, end)
            a = end

    a = 0
    while a < len(text):
        if claimed[a]:
            a += 1
            continue
        b = a+1
        while b < len(text) and not claimed[b]:
            b += 1
        emit('general_information' if re.search(r'字|號|号|孝行', text[a:b]) else 'unclassified', a, b)
        a = b
    return {'owner_id': owner_id, 'source_text': text, 'items': sorted(items, key=lambda i: i['start'])}


def enrich(document):
    for index, person in enumerate(document['candidates']):
        person['information'] = parse_candidate(person, f'candidate-{index}')
    document['information_parser_version'] = 2
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('people', type=Path, nargs='?')
    parser.add_argument('--samples', type=Path, help='parse labeled rule examples without OCR')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if bool(args.people) == bool(args.samples):
        parser.error('provide either people JSON or --samples')
    if args.samples:
        with args.samples.open(encoding='utf-8') as f:
            cases = json.load(f)['cases']
        document = {'samples': [dict(id=case['id'], kind='confirmed_fragment' if case['id']=='p032-confirmed' else 'synthetic',
                                    **parse_candidate({'information_candidates': [{'text':t,'bbox':None} for t in case['fragments']]}, case['id']))
                                for case in cases]}
    else:
        with args.people.open(encoding='utf-8') as f:
            document = enrich(json.load(f))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(document, f, ensure_ascii=False, indent=2)
    print(f"Saved parsed information -> {args.output}")


if __name__ == '__main__':
    main()
