"""Conservative Korean sentence templates for classified genealogy facts."""

import re

DATE_EVENTS = {
    'birth': '태어남',
    'death': '사망함',
    'burial_date': '매장·이장 날짜로 기록됨',
    'date_unspecified': '날짜로 기록됨 (사건 종류 미상)',
    'ambiguous_event': '생몰 표지가 불명확함',
}


def date_phrase(date):
    """Express only components actually read from the source text."""
    if not date or not any(date.get(key) for key in ('year_text', 'month_text', 'day_text')):
        return None
    year = date.get('year_text')
    if date.get('year_number') and year:
        year = f"{date['year_number']}년 (원문 {year})"
    month = date.get('month')
    day = date.get('day')
    if date.get('month_text'):
        month_part = f"{'윤' if date.get('leap_month') else ''}{month}월" if month is not None else f"{'윤' if date.get('leap_month') else ''}{date['month_text']}"
    else:
        month_part = None
    day_part = (f'{day}일' if day is not None else date['day_text']) if date.get('day_text') else None
    parts = [part for part in (year, month_part, day_part) if part]
    missing = []
    if not year:
        missing.append('연도')
    if not month_part:
        missing.append('월')
    if not day_part:
        missing.append('일')
    suffix = f" ({'·'.join(missing)} 미상)" if missing else ''
    return ' '.join(parts) + suffix


def automatic_explanation(item):
    """Return an explanation only where classification supports a safe template."""
    kind = item.get('kind')
    if kind in DATE_EVENTS:
        phrase = date_phrase(item.get('date'))
        if phrase is None or item.get('warnings'):
            return None
        return f"{phrase} {DATE_EVENTS[kind]}."
    if kind == 'spouse_information':
        subject = item.get('subject') or {}
        label = subject.get('label')
        if not label:
            return None
        relation = '첩' if subject.get('relation_type') == 'concubine' else '배우자'
        if label == '姓名未詳' or re.search(r'[生卒歿殁逝年月日]', label):
            return f'{relation} 이름 미상으로 기록됨.'
        return f'{relation} {label}로 기록됨.'
    if kind == 'office':
        return f"관직 기록: {item['raw']}."
    if kind == 'education':
        return f"과거·학력 기록: {item['raw']}."
    return None


def explain_item(item):
    """Keep reviewer's wording and automatic text in distinct fields."""
    existing = item.get('explanation') or {}
    manual = existing.get('manual')
    if manual is None:
        manual = item.get('manual_explanation')
    return {'automatic': automatic_explanation(item), 'manual': manual}


def enrich_explanations(document):
    for person in document['candidates']:
        for item in person['information']['items']:
            item['explanation'] = explain_item(item)
            for nested in item.get('items', []):
                nested['explanation'] = explain_item(nested)
    document['explanation_template_version'] = 1
    return document
