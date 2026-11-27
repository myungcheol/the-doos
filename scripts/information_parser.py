#!/usr/bin/env python3
"""Conservative, source-preserving information candidates with local era-year lookup."""
import argparse
import json
import re
from pathlib import Path

from era_dates import CYCLE, ERA_NAME, normalize_date

NUM = r'[0-9〇零一二三四五六七八九十百千廿卅元]+'
ERA_YEAR = rf'(?P<era>{ERA_NAME})(?:(?P<accession>卽位|即位)|(?P<ordinal>{NUM}))年'
YEAR = rf'(?:(?:{ERA_YEAR}|(?:西紀)?{NUM}年)(?:(?:歲次)?(?P<cycle>{CYCLE}))?|(?P<cycle_only>{CYCLE})年?)'
DATE = re.compile(rf'(?P<calendar_mark>[陰陽農][曆歷])?(?P<year>{YEAR})?(?P<leap>閏|闰)?(?P<month>(?:正|□+|{NUM})月)?(?P<day>初?(?:□+|{NUM})日)?')
OFFICES = ('兵部尚書', '中書舍人', '左議政', '右議政', '領議政', '判書', '參判', '郡守', '縣監', '縣令', '知郡事', '學士', '學正', '將軍')
EDUCATION = ('進士', '生員', '文科', '武科', '及第', '登科')
EVENTS = {'生': 'birth', '卒': 'death', '歿': 'death', '殁': 'death', '逝': 'death'}
POSITIONAL_YEAR = re.compile(r'[一二12][0-9〇零一二三四五六七八九。○ＯO]{3}(?=年)')


def number(text):
    if text == '正':
        return 1
    if text is None:
        return None
    text = text.replace('初', '').replace('廿', '二十').replace('卅', '三十')
    if text.isdigit():
        return int(text)
    digits = dict(zip('〇零一二三四五六七八九元', (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 1)))
    digits.update({str(n): n for n in range(10)})
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
    # Matching text has identical character offsets to the untouched source.
    date_text = POSITIONAL_YEAR.sub(lambda m: m.group().translate(str.maketrans('。○ＯO', '〇〇〇〇')), text)
    offsets = []
    cursor = 0
    for index, region in enumerate(regions):
        offsets.append((cursor, cursor + len(region['text']), index))
        cursor += len(region['text'])
    claimed = [False] * len(text)
    items = []

    def emit(kind, start, end, **extra):
        refs = [{'region_index': i, 'start': max(start, a)-a, 'end': min(end, b)-a,
                 'bbox': regions[i]['bbox']} for a, b, i in offsets if max(start, a) < min(end, b)]
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
        if identity:
            label = identity.group()
        else:
            # PaddleOCR sometimes drops 氏. Preserve the Han designation in
            # the same OCR region as the marker instead of inventing 氏.
            containing = next(((a, b) for a, b, _ in offsets if a <= marker.start() < b), None)
            local_end = min(end, containing[1]) if containing else marker.end()
            fallback = re.match(r'[\u3400-\u9fff]{2,8}', text[marker.end():local_end])
            label = fallback.group() if fallback else '姓名未詳'
        relation = 'concubine' if marker.group().startswith('妾') else 'spouse'
        scoped_regions, mapping = [], []
        for a, b, i in offsets:
            if max(start, a) < min(end, b):
                left, right = max(start,a)-a, min(end,b)-a
                scoped_regions.append(dict(regions[i], text=regions[i]['text'][left:right]))
                mapping.append((i,left))
        nested = parse_candidate({'information_candidates': scoped_regions}, subject_id, resolve_scopes=False)
        for item in nested['items']:
            item['start'] += start
            item['end'] += start
            for correction in item.get('date', {}).get('ocr_corrections', []):
                correction['offset'] += start
            item['source_owner_id'] = owner_id
            for ref in item['source_refs']:
                original_index, shift = mapping[ref['region_index']]
                ref['region_index'] = original_index
                ref['start'] += shift
                ref['end'] += shift
        emit('spouse_information', start, end, subject={'id':subject_id, 'label':label,
             'relation_type':relation, 'marker_raw':marker.group()}, items=nested['items'])

    for match in DATE.finditer(date_text[:limit]):
        if not match.group() or not any(match.group(k) for k in ('year', 'month', 'day')):
            continue
        a, b = match.span()
        before = text[a-1:a] if a else ''
        after = text[b:b+1]
        # 生員 is a credential; 卒業 is not a death marker.
        suffix = EVENTS.get(after) if text[b:b+2] not in ('生員', '卒業') else None
        prefix = EVENTS.get(before) if text[max(0,a-1):a+1] not in ('生員', '卒業') else None
        inferred_death_marker = after == '辛' and any(text[b+1:limit].startswith(word) for word in ('遷葬', '移葬', '葬'))
        if inferred_death_marker:
            suffix = 'death'
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
        elif match.group('era') or match.group('year') and re.fullmatch(r'(?:西紀)?[一二12][0-9〇零一二三四五六七八九]{3}年(?:' + CYCLE + r')?', match.group('year')):
            kind, start, end = 'date_unspecified', a, b
        else:
            continue
        if any(claimed[start:end]):
            continue
        year, month, day = match.group('year', 'month', 'day')
        parts = [label for label, value in (('year', year), ('month', month), ('day', day)) if value]
        month_value = number(month[:-1]) if month else None
        day_value = number(day[:-1]) if day else None
        mark = match.group('calendar_mark') or ''
        calendar = 'unknown'
        if mark.startswith('陽'):
            calendar = 'solar'
        elif mark or match.group('leap'):
            calendar = 'lunar'
        max_day = 30 if calendar == 'lunar' else 31
        warnings = []
        if ((month_value is not None and not 1 <= month_value <= 12)
                or (day_value is not None and not 1 <= day_value <= max_day)):
            warnings.append('date components out of range')
        if (month and month_value is None) or (day and day_value is None):
            warnings.append('unreadable date component')
        if inferred_death_marker:
            warnings.append('OCR 辛 interpreted as likely 卒 because burial text follows')
        year_digits = re.match(r'(?:西紀)?([一二12][0-9〇零一二三四五六七八九]{3})年', year or '')
        corrections = [{'raw':text[pos], 'interpreted_as':date_text[pos], 'offset':pos}
                       for pos in range(a,b) if text[pos] != date_text[pos]]
        date = {'year_text': text[match.start('year'):match.end('year')] if year else None, 'month_text': month, 'day_text': day,
                'year_number': number(year_digits.group(1)) if year_digits else None,
                'normalized_year_text': year, 'ocr_corrections': corrections,
                'month': month_value, 'day': day_value, 'precision': '_'.join(parts),
                'leap_month': True if match.group('leap') else None,
                'calendar': calendar}
        date = normalize_date(date, era=match.group('era'), ordinal=number(match.group('ordinal')),
                              accession=bool(match.group('accession')),
                              cycle=match.group('cycle') or match.group('cycle_only'))
        emit(kind, start, end, date=date,
             warnings=warnings,
             ocr_marker_interpretation={'raw':'辛', 'interpreted_as':'卒'} if inferred_death_marker else None)

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
    document['information_parser_version'] = 4
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('people', type=Path, nargs='?')
    parser.add_argument('--samples', type=Path, help='parse labeled rule examples without OCR')
    parser.add_argument('--text', help='inspect a transcription without running OCR')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if sum(x is not None for x in (args.people, args.samples, args.text)) != 1:
        parser.error('provide people JSON, --samples or --text')
    if args.text is not None:
        if args.output:
            parser.error('--text prints to stdout')
        result = parse_candidate({'information_candidates': [{'text': args.text, 'bbox': None}]}, 'sample')
        print(json.dumps(result['items'], indent=2, ensure_ascii=False))
        return
    if not args.output:
        parser.error('--output is required for file inputs')
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
