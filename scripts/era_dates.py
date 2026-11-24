"""Normalize the year label and preserve the calendar of the recorded month/day."""
import json
import re
from pathlib import Path

TABLE = json.loads((Path(__file__).resolve().parents[1] / 'data/era-years.json').read_text(encoding='utf-8'))
BY_NAME = {}
for entry in TABLE['entries']:
    for alias in entry['aliases']:
        BY_NAME.setdefault(alias, []).append(entry)
ERA_NAME = '|'.join(map(re.escape, sorted(BY_NAME, key=len, reverse=True)))
STEMS = '甲乙丙丁戊己庚辛壬癸'
BRANCHES = '子丑寅卯辰巳午未申酉戌亥'
CYCLE = f'[{STEMS}][{BRANCHES}]'


def cycle_of(year):
    return STEMS[(year - 4) % 10] + BRANCHES[(year - 4) % 12]


def normalize_date(date, *, era=None, ordinal=None, accession=False, cycle=None):
    """Return a new date. Candidate years for a lone cycle span Goryeo to publication."""
    candidates = []
    if era:
        for row in BY_NAME.get(era, []):
            if accession:
                year = row.get('accession')
            elif ordinal and 1 <= ordinal <= row['last'] - row['first'] + 1:
                year = row['first'] + ordinal - 1
            else:
                year = None
            if year is not None:
                candidates.append({'year': year, 'entry': row['id'], 'source': row['source']})
    elif date.get('year_number') is not None:
        candidates.append({'year': date['year_number']})
    elif cycle and re.fullmatch(CYCLE + '年?', date.get('year_text') or ''):
        candidates = [{'year': y} for y in range(918, 1988) if cycle_of(y) == cycle]

    matching = sorted({c['year'] for c in candidates if not cycle or cycle_of(c['year']) == cycle})
    if len(matching) == 1:
        status = 'resolved'
    elif matching:
        status = 'ambiguous'
    elif candidates:
        status = 'conflict'
    else:
        status = 'unresolved'
    result = dict(date, gregorian_year=matching[0] if len(matching) == 1 else None,
                  conversion_status=status, date_details={'table_version': TABLE['version'],
                  'era': era, 'ordinal': ordinal, 'accession': accession, 'cycle': cycle,
                  'evidence': candidates, 'candidate_years': matching})
    for part, maximum in [('month', 12), ('day', 30 if date.get('calendar') == 'lunar' else 31)]:
        assumed = date.get(part + '_text') is None and date.get(part) is None
        value = date.get(part)
        result[part + '_assumed'] = assumed
        if assumed:
            value = 1
        elif value is None or not 1 <= value <= maximum:
            value = None
        result['normalized_' + part] = value
    return result
