"""Rule-based extraction of person-specific genealogy fields from existing OCR columns.

No new OCR inference is performed here. The extractor assigns OCR columns to the
nearest person-name region to their right, then returns keyword-context drafts.
All returned values are unverified and must be reviewed against the scan.
"""
from __future__ import annotations

import re
from typing import Any

from historical_dates import date_parts_draft


FIELD_PATTERNS: dict[str, str] = {
    "birth_text": r"生|誕生|降生",
    "death_text": r"卒|薨|歿|殁|終|终|逝世",
    "office_title": (
        r"官至|進士|进士|登科|中書|中书|舍人|侍郎|刺史|尚書|尚书|"
        r"平章|知郡事|御史|功臣|寶文殿|宝文殿|大夫|判書|判书|郎中|"
        r"太守|縣令|县令|參知政事|参知政事|門下侍郎|门下侍郎"
    ),
    "spouse_text": r"配|夫人|淑夫人|宜人|貞夫人|贞夫人|妾|媵|側室|侧室",
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
                "token_boxes": column.get("token_boxes") or [],
                "order_right_to_left": column.get("order_right_to_left"),
                "center_x": center,
            })
    columns.sort(key=lambda c: c["center_x"], reverse=True)
    return columns


def _field_indices(columns: list[dict[str, Any]], continuation: bool = False) -> dict[str, list[int]]:
    """Keep spouse biographies separate from the subject's keyword matches."""
    spouse_pattern = FIELD_PATTERNS["spouse_text"]
    spouse_start = next((i for i, col in enumerate(columns)
                         if re.search(spouse_pattern, col["text"])), len(columns))
    own_columns = columns[:spouse_start]
    matches: dict[str, list[int]] = {}
    for field, pattern in FIELD_PATTERNS.items():
        if field == "spouse_text":
            matches[field] = list(range(spouse_start, len(columns))) if spouse_start < len(columns) else []
            continue
        if continuation and field == "office_title":
            pattern += r"|拜為|拜爲|邑封|學士|学士"
        matches[field] = [i for i, col in enumerate(own_columns)
                          if re.search(pattern, col["text"], flags=re.IGNORECASE)
                          and not (field == "pen_name_hanja" and re.search(r"因[號号]", col["text"]))]

    claimed = {i for field, indices in matches.items()
               if field != "spouse_text" for i in indices}
    if continuation:
        # Consecutive OCR columns can carry one phrase whose keyword occurs
        # again after a single unmarked column.
        for field in ("office_title", "burial_text"):
            anchors = matches[field]
            matches[field] = sorted(set(anchors) | {
                a + 1 for a, b in zip(anchors, anchors[1:])
                if b == a + 2 and a + 1 not in claimed
            })
    for field in ("birth_text", "death_text"):
        indices = matches[field]
        matches[field] = sorted(set(indices) | {
            i - 1 for i in indices if i > 0 and i - 1 not in claimed
        })
    if continuation and matches["burial_text"]:
        first = matches["burial_text"][0]
        used = claimed | set(matches["birth_text"]) | set(matches["death_text"])
        if first > 0 and first - 1 not in used and first - 1 not in matches["office_title"]:
            matches["burial_text"] = [first - 1, *matches["burial_text"]]
    # A burial sentence often continues into the following vertical column.
    burial = matches["burial_text"]
    if burial:
        last = burial[-1]
        if (last + 1 < spouse_start and last + 1 not in claimed
                and re.search(r"葬|墓|塋|茔|墳|坟|壙|圹", columns[last]["text"])
                and not re.search(r"坐之原|同原|附右|祔", columns[last]["text"])):
            burial = [*burial, last + 1]
    matches["burial_text"] = burial
    return matches


def extract_continuation_info_draft(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify linked page columns while keeping every original evidence box."""
    ordered = sorted((col for col in columns if str(col.get("text") or "").strip()),
                     key=_box_center_x, reverse=True)
    values: dict[str, str] = {}
    sources: dict[str, list[dict[str, Any]]] = {}
    if ordered:
        values["biography_text"] = "\n".join(str(col["text"]) for col in ordered)
    for field, indices in _field_indices(ordered, continuation=True).items():
        selected = [(ordered[i], _field_column_text(field, str(ordered[i]["text"]))) for i in indices]
        selected = [(col, text) for col, text in selected if text]
        if selected:
            values[field] = " / ".join(text for _, text in selected)
            sources[field] = [col for col, _ in selected]
    return {"draft_values": values, "field_sources": sources}


def _field_column_text(field: str, text: str) -> str:
    """Split a shared death/burial OCR column without inventing a smaller bbox."""
    if field not in {"death_text", "burial_text"} or "葬" not in text:
        return text
    # The printed death statement may end immediately before 禮葬/葬.
    match = re.search(r"禮?葬", text)
    if not match:
        return text
    if field == "death_text":
        return text[:match.start()].strip()
    prefix = text[:match.start()]
    return text[match.start():].strip() if re.search(FIELD_PATTERNS["death_text"], prefix) else text


def get_field_source_columns(draft: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Return OCR source columns for one field, preserving their bboxes directly.

    Do not resolve these objects by column_id: OCR output from older pages may
    have missing or regenerated identifiers while still retaining valid boxes.
    """
    sources = (draft.get("field_sources") or {}).get(field) or []
    return [item for item in sources if isinstance(item, dict) and item.get("bbox")]


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

    draft_values: dict[str, Any] = {"biography_text": section_text}
    evidence: dict[str, list[str]] = {"biography_text": [section_text]}
    field_sources: dict[str, list[dict[str, Any]]] = {}
    for field, indices in _field_indices(columns).items():
        selected = [(columns[i], _field_column_text(field, columns[i]["text"])) for i in indices]
        selected = [(col, text) for col, text in selected if text]
        if not selected:
            continue
        value = " / ".join(text for _, text in selected)
        draft_values[field] = value
        evidence[field] = [value]
        field_sources[field] = [
            {
                "column_id": col.get("column_id"), "text": col.get("text"),
                "bbox": col.get("bbox"), "token_boxes": col.get("token_boxes") or [],
                "mean_confidence": col.get("mean_confidence"),
            }
            for col, _ in selected
        ]

    for event in ("birth", "death"):
        value = draft_values.get(f"{event}_text")
        parts = date_parts_draft(value, event)
        if parts:
            draft_values[f"{event}_date"] = parts

    return {
        "draft_values": draft_values,
        "evidence": evidence,
        "field_sources": field_sources,
        "columns": [
            {
                "column_id": col.get("column_id"), "text": col.get("text"),
                "bbox": col.get("bbox"), "token_boxes": col.get("token_boxes") or [],
                "mean_confidence": col.get("mean_confidence"),
            }
            for col in columns
        ],
        "source_record_ocr_text": section_text,
        "source_row_id": row_id,
        "source_column_ids": [col["column_id"] for col in columns if col.get("column_id")],
        "message": "기존 OCR 열의 위치와 키워드를 이용해 추출한 검수용 초안입니다.",
        "method": "row_columns_bbox_field_boundaries_v2",
        "needs_review": True,
    }
