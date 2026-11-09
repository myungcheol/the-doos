"""Rule-based extraction of person-specific genealogy fields from existing OCR columns.

No new OCR inference is performed here. The extractor assigns OCR columns to the
nearest person-name region to their right, then returns keyword-context drafts.
All returned values are unverified and must be reviewed against the scan.
"""
from __future__ import annotations

import re
from typing import Any


FIELD_PATTERNS: dict[str, str] = {
    "birth_text": r"生|誕生|降生",
    "death_text": r"卒|薨|歿|殁|終|终|逝世",
    "office_title": (
        r"官至|進士|进士|登科|中書|中书|舍人|侍郎|刺史|尚書|尚书|"
        r"平章|知郡事|御史|功臣|寶文殿|宝文殿|大夫|判書|判书|郎中|"
        r"太守|縣令|县令|參知政事|参知政事|門下侍郎|门下侍郎"
    ),
    "spouse_text": r"配|夫人|淑夫人|宜人|貞夫人|贞夫人",
    "burial_text": r"葬|墓|塋|茔|墳|坟|壙|圹|坐之原|同原|設壇|设坛|合封|附右|祔",
    "courtesy_name_hanja": r"字",
    "pen_name_hanja": r"號|号",
}

FIELD_LABELS = {
    "birth_text": "출생 정보",
    "death_text": "사망 정보",
    "office_title": "관직·품계·봉호",
    "spouse_text": "배우자",
    "burial_text": "묘소·장지",
    "courtesy_name_hanja": "자(字)",
    "pen_name_hanja": "호(號)",
}


def _box_center_x(item: dict[str, Any]) -> float:
    box = item.get("bbox") or {}
    return float(box.get("x", 0)) + float(box.get("width", 0)) / 2


def get_person_section_columns(
    person: dict[str, Any], row: dict[str, Any], row_people: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assign the text columns immediately to the left of a person's name.

    Traditional genealogy pages generally place each person's name at the right
    edge of that person's record block. When multiple names share a row, the
    right edge of the next name to the left bounds the current person's block.
    This is a geometric heuristic, not a guaranteed semantic segmentation.
    """
    target_id = person.get("person_id")
    ordered_people = sorted(row_people, key=_box_center_x, reverse=True)
    try:
        position = next(i for i, p in enumerate(ordered_people) if p.get("person_id") == target_id)
    except StopIteration:
        position = 0
    own_box = person.get("bbox") or {}
    upper = float(own_box.get("x", 0)) - 1.0
    lower = 0.0
    if position + 1 < len(ordered_people):
        left_box = ordered_people[position + 1].get("bbox") or {}
        lower = float(left_box.get("x", 0)) + float(left_box.get("width", 0)) + 1.0

    columns = []
    for column in row.get("columns", []) or []:
        box = column.get("bbox") or {}
        if not box:
            continue
        center = float(box.get("x", 0)) + float(box.get("width", 0)) / 2
        text = str(column.get("text") or "").strip()
        if lower < center < upper and text and text not in {"|", "||", "|||", "||||"}:
            columns.append({
                "column_id": column.get("column_id"),
                "text": text,
                "bbox": box,
                "mean_confidence": column.get("mean_confidence"),
                "center_x": center,
            })
    columns.sort(key=lambda c: c["center_x"], reverse=True)
    return columns


def _merge_context_ranges(indices: list[int], count: int, radius: int = 1) -> list[tuple[int, int]]:
    ranges = sorted((max(0, i - radius), min(count - 1, i + radius)) for i in indices)
    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _extract_context(columns: list[dict[str, Any]], pattern: str, radius: int = 1) -> tuple[str | None, list[str]]:
    indices = [i for i, col in enumerate(columns) if re.search(pattern, col["text"], flags=re.IGNORECASE)]
    if not indices:
        return None, []
    snippets = []
    for start, end in _merge_context_ranges(indices, len(columns), radius=radius):
        snippets.append(" / ".join(col["text"] for col in columns[start:end + 1]))
    # Keep order as encountered in the traditional right-to-left reading flow.
    value = "\n".join(dict.fromkeys(s for s in snippets if s.strip()))
    return value or None, snippets


def extract_person_info_draft(
    person: dict[str, Any], page_result: dict[str, Any], page_people: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return prefill values and evidence from OCR columns already present in JSON."""
    row_id = person.get("source_row_id")
    row = next((r for r in page_result.get("rows", []) or [] if r.get("row_id") == row_id), None)
    if row is None:
        return {
            "draft_values": {}, "evidence": {}, "source_record_ocr_text": "",
            "message": "해당 인물의 OCR 행을 찾지 못했습니다.", "source_row_id": row_id,
        }
    row_people = [p for p in page_people if p.get("source_row_id") == row_id]
    columns = get_person_section_columns(person, row, row_people)
    section_text = "\n".join(col["text"] for col in columns).strip()
    if not columns:
        return {
            "draft_values": {}, "evidence": {}, "source_record_ocr_text": "",
            "message": "인물 이름 왼쪽의 OCR 텍스트 열을 분리하지 못했습니다. 행 전체 OCR은 참고용으로 확인하세요.",
            "source_row_id": row_id,
        }

    draft_values: dict[str, str] = {"biography_text": section_text}
    evidence: dict[str, list[str]] = {"biography_text": [section_text]}
    for field, pattern in FIELD_PATTERNS.items():
        value, snippets = _extract_context(columns, pattern, radius=1)
        if value:
            draft_values[field] = value
            evidence[field] = snippets

    return {
        "draft_values": draft_values,
        "evidence": evidence,
        "source_record_ocr_text": section_text,
        "source_row_id": row_id,
        "source_column_ids": [col["column_id"] for col in columns if col.get("column_id")],
        "message": "기존 OCR 열의 위치와 키워드를 이용해 추출한 검수용 초안입니다.",
        "method": "row_columns_bbox_keyword_context_v1",
        "needs_review": True,
    }
