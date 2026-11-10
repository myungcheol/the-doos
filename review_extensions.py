"""Review-only additions: recovered candidates and cross-page record evidence.

OCR input files stay immutable. New evidence and links are stored additively in
review_state.json and can be exported by either review interface.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import uuid

from person_data_model import ensure_person_uid, make_source_occurrence
from person_info_extractor import extract_continuation_info_draft


def page_name(page):
    return str(page.get("source_page") or Path(page.get("source_image", "page")).name)


def page_sort_key(page):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", page_name(page))]


def merge_review_sources(people, relationships, pages, state):
    """Include explicitly imported/recovered records without renumbering OCR IDs."""
    people, relationships, pages = list(people), list(relationships), list(pages)
    person_keys = {(p.get("source_page"), p.get("person_id")) for p in people}
    rel_keys = {(r.get("source_page"), r.get("relationship_id")) for r in relationships}
    page_keys = {page_name(p) for p in pages}
    for extra in state.get("supplemental_pages", []):
        page = extra["page_result"]
        if page_name(page) not in page_keys:
            pages.append(page)
            page_keys.add(page_name(page))
        for person in extra.get("people", []):
            key = (person.get("source_page"), person.get("person_id"))
            if key not in person_keys:
                people.append(person)
                person_keys.add(key)
        for rel in extra.get("relationships", []):
            key = (rel.get("source_page"), rel.get("relationship_id"))
            if key not in rel_keys:
                relationships.append(rel)
                rel_keys.add(key)
    for person in state.get("additional_people", []):
        key = (person.get("source_page"), person.get("person_id"))
        if key not in person_keys:
            people.append(person)
            person_keys.add(key)
    return people, relationships, pages


def previous_row_people(page, row, pages, people, state):
    """Suggest previous-page people in the same physical row, last RTL first."""
    ordered = sorted(pages, key=page_sort_key)
    index = next((i for i, p in enumerate(ordered) if page_name(p) == page_name(page)), -1)
    if index <= 0:
        return []
    previous = ordered[index - 1]
    current_number = re.search(r"(\d+)$", Path(page_name(page)).stem)
    previous_number = re.search(r"(\d+)$", Path(page_name(previous)).stem)
    if current_number and previous_number and int(current_number[1]) != int(previous_number[1]) + 1:
        return []
    previous_row = next((r for r in previous.get("rows", []) if r.get("row_number") == row.get("row_number")), None)
    if previous_row is None:
        return []
    candidates = [p for p in people if p.get("source_page") == page_name(previous)
                  and p.get("source_row_id") == previous_row.get("row_id")
                  and state.get("people_updates", {}).get(p.get("person_id"), {}).get("review_status", p.get("review_status")) != "rejected"]
    if not candidates:
        # A biography may span several otherwise nameless pages. Continue only
        # through links that the reviewer has already confirmed on the prior row.
        target_ids = {link.get("target_person_id") for link in state.get("continuation_links", [])
                      if link.get("review_status") == "confirmed" and link.get("source_page") == page_name(previous)
                      and link.get("source_row_id") == previous_row.get("row_id")}
        candidates = [p for p in people if p.get("person_id") in target_ids]
    return sorted(candidates, key=lambda p: float((p.get("bbox") or {}).get("x", 0)))


def orphan_columns(row, people, state=None):
    """Suggest columns preceding the first name, or all text on a nameless row.

    This is a review suggestion, not a claim of authorship. New names may still
    be missing. The reviewer chooses the actual columns before linking them.
    """
    state = state or {}
    row_people = [p for p in people if p.get("source_row_id") == row.get("row_id")
                  and state.get("people_updates", {}).get(p.get("person_id"), {}).get("review_status", p.get("review_status")) != "rejected"]
    right_edge = max(((p.get("bbox") or {}).get("x", 0) + (p.get("bbox") or {}).get("width", 0)
                      for p in row_people), default=None)
    attached_boxes = [column.get("bbox") for link in state.get("continuation_links", [])
                      if link.get("review_status") == "confirmed" and link.get("source_row_id") == row.get("row_id")
                      for column in link.get("columns", [])]
    columns = []
    for column in row.get("columns", []):
        b = column.get("bbox") or {}
        text = str(column.get("text") or "")
        compact = re.sub(r"\s+", "", text)
        if not b.get("width") or not b.get("height") or not compact.strip("|"):
            continue
        if b in attached_boxes:
            continue
        if re.fullmatch(r"[一二三四五六七八九十百〇零0-9]+世", compact):
            continue
        if right_edge is not None and b.get("x", 0) + b["width"] / 2 < right_edge:
            continue
        columns.append(deepcopy(column))
    return sorted(columns, key=lambda c: c["bbox"]["x"], reverse=True)


def orphan_regions(row, people, state=None):
    """Group adjacent unassigned OCR columns for review without changing evidence."""
    regions = []
    for column in orphan_columns(row, people, state):
        box = column["bbox"]
        if not regions or regions[-1]["left"] - (box["x"] + box["width"]) > 32:
            regions.append({"columns": [], "left": box["x"], "top": box["y"],
                            "right": box["x"] + box["width"], "bottom": box["y"] + box["height"]})
        region = regions[-1]
        region["columns"].append(column)
        region["left"] = min(region["left"], box["x"])
        region["top"] = min(region["top"], box["y"])
        region["right"] = max(region["right"], box["x"] + box["width"])
        region["bottom"] = max(region["bottom"], box["y"] + box["height"])
    return [{"columns": region["columns"],
             "bbox": {"x": region["left"], "y": region["top"],
                      "width": region["right"] - region["left"],
                      "height": region["bottom"] - region["top"]},
             "text": "\n".join(str(column.get("text") or "") for column in region["columns"])}
            for region in regions]


def make_continuation(page, row, columns, target, state):
    if not columns:
        raise ValueError("이어진 기록의 OCR 열을 선택하세요.")
    if target.get("source_page") == page_name(page):
        raise ValueError("이전 페이지의 인물을 선택하세요.")
    for link in state.get("continuation_links", []):
        if link.get("review_status") != "confirmed" or link.get("source_page") != page_name(page):
            continue
        for a in link.get("columns", []):
            if any(a.get("bbox") == b.get("bbox") and link.get("source_row_id") == row.get("row_id") for b in columns):
                raise ValueError("이미 연결된 OCR 열이 포함되어 있습니다. 기존 연결을 해제한 뒤 다시 연결하세요.")
    uid = ensure_person_uid(target, state)
    boxes = [c["bbox"] for c in columns]
    left, top = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    right = max(b["x"] + b["width"] for b in boxes)
    bottom = max(b["y"] + b["height"] for b in boxes)
    link_id = "CONT_" + uuid.uuid4().hex.upper()
    source = {"source_page": page_name(page), "source_row_id": row.get("row_id"),
              "source_column_id": None, "bbox": {"x": left, "y": top, "width": right-left, "height": bottom-top}}
    occurrence = make_source_occurrence(source, page, state.get("edition"), state.get("page_metadata", {}).get(page_name(page)))
    occurrence.update(source_occurrence_id="OCC_" + uuid.uuid5(uuid.NAMESPACE_URL, link_id).hex.upper(),
                      occurrence_type="record_continuation")
    return {"continuation_id": link_id, "source_page": page_name(page), "source_row_id": row.get("row_id"),
            "target_person_id": target["person_id"], "target_person_uid": uid,
            "review_status": "confirmed", "columns": deepcopy(columns),
            "text": "\n".join(str(c.get("text") or "") for c in columns),
            "source_occurrence": occurrence}


def continuation_field_parts(person, state):
    """Return unverified field snippets from confirmed links to this person."""
    matching = [link for link in state.get("continuation_links", [])
                if link.get("review_status") == "confirmed"
                and (link.get("target_person_id") == person.get("person_id")
                     or (person.get("person_uid") and link.get("target_person_uid") == person.get("person_uid")))]
    matching.sort(key=lambda link: (page_sort_key({"source_page": link.get("source_page")}),
                                    str(link.get("source_row_id") or "")))
    result = {}
    for link in matching:
        draft = extract_continuation_info_draft(link.get("columns") or [])
        for field, value in draft["draft_values"].items():
            result.setdefault(field, []).append({
                "continuation_id": link.get("continuation_id"),
                "source_page": link.get("source_page"),
                "source_row_id": link.get("source_row_id"),
                "text": value,
                "columns": draft["field_sources"].get(field, link.get("columns") or []),
            })
    return result


def append_continuation_text(value, parts, suppressed=(), separator=" / "):
    """Show linked OCR after the existing text, once per source snippet."""
    result = str(value or "")
    for part in parts:
        snippet = str(part.get("text") or "").strip()
        if snippet and part.get("continuation_id") not in suppressed and snippet not in result:
            result = f"{result}{separator if result else ''}{snippet}"
    return result


def append_continuation_spouses(spouses, parts, suppressed=()):
    """Offer linked spouse text as separate unverified entries for review."""
    result = deepcopy(spouses) if isinstance(spouses, list) else []
    for part in parts:
        snippet = str(part.get("text") or "").strip()
        if (not snippet or part.get("continuation_id") in suppressed
                or any(snippet in str(item.get("name_and_record") or item.get("name_text") or "")
                       for item in result if isinstance(item, dict))):
            continue
        result.append({"type": "other", "name_and_record": snippet,
                       "notes": f"이어진 OCR 초안 · {part.get('source_page') or '출처 미상'} · 유형 검수 필요",
                       "review_status": "needs_review"})
    return result


def continuation_suppressions_for_save(previous, values, spouses, parts):
    """Remember reviewer removal of an offered snippet across later reloads."""
    suppressed = {field: set(ids) for field, ids in (previous or {}).items()}
    for field, items in parts.items():
        if field not in values and field != "spouse_text":
            continue
        saved = str(values.get(field) or "")
        for item in items:
            link_id = item.get("continuation_id")
            if not link_id:
                continue
            target = suppressed.setdefault(field, set())
            if item.get("text") and item["text"] in saved:
                target.discard(link_id)
            else:
                target.add(link_id)
    for item in parts.get("spouse_text", []):
        link_id = item.get("continuation_id")
        if not link_id:
            continue
        target = suppressed.setdefault("spouses", set())
        if any(str(item.get("text") or "") in str(spouse.get("name_and_record") or spouse.get("name_text") or "")
               for spouse in spouses if isinstance(spouse, dict)):
            target.discard(link_id)
        else:
            target.add(link_id)
    return {field: sorted(ids) for field, ids in suppressed.items() if ids}


def continuation_needs_review(parts, update):
    """A newly attached snippet needs a fresh information review decision."""
    suppressed = update.get("continuation_field_suppressions") or {}
    spouses = update.get("spouses") or []
    for field, items in parts.items():
        saved = str(update.get(field) or "")
        if field == "spouse_text":
            saved += " ".join(str(item.get("name_and_record") or item.get("name_text") or "")
                              for item in spouses if isinstance(item, dict))
        for item in items:
            if (item.get("continuation_id") not in suppressed.get(field, [])
                    and item.get("text") not in saved):
                return True
    return False


def apply_continuations(person, state):
    """Export additional evidence separately; never rewrite a reviewed biography."""
    links = [deepcopy(link) for link in state.get("continuation_links", [])
             if link.get("review_status") == "confirmed" and link.get("target_person_uid") == person.get("person_uid")]
    if not links:
        return
    person["raw_data"]["record_ocr"]["continuations"] = links
    person["source_occurrences"].extend(link["source_occurrence"] for link in links)
    raw_fields = person["raw_data"].setdefault("field_ocr", {})
    for link in links:
        draft = extract_continuation_info_draft(link.get("columns") or [])
        for field, value in draft["draft_values"].items():
            if field == "biography_text":
                continue
            raw_fields.setdefault(field, {"text": [], "columns": []}).setdefault("continuations", []).append({
                "continuation_id": link.get("continuation_id"),
                "source_page": link.get("source_page"),
                "source_row_id": link.get("source_row_id"),
                "text": value,
                "columns": draft["field_sources"].get(field, []),
            })


def recover_name_candidates(image, page, people, offset=(0, 0)):
    """Geometry-only rescan using existing OCR text; never invokes an OCR engine."""
    from jokbo_ocr import detect_large_printed_name_regions, find_matching_ocr_column, clean_hanzi_text

    additions = []
    height, width = image.shape[:2]
    for row in page.get("rows", []):
        b = row.get("bbox") or {}
        x, y = max(0, int(b.get("x", 0) - offset[0])), max(0, int(b.get("y", 0) - offset[1]))
        right = min(width, int(b.get("x", 0) + b.get("width", 0) - offset[0]))
        bottom = min(height, int(b.get("y", 0) + b.get("height", 0) - offset[1]))
        if right <= x or bottom <= y:
            continue
        for region in detect_large_printed_name_regions(image[y:bottom, x:right], x + offset[0], y + offset[1]):
            box = region["bbox"]
            center_x, center_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            if any((other := p.get("bbox") or {}) and other.get("x", 0) - 5 <= center_x <= other.get("x", 0) + other.get("width", 0) + 5
                   and other.get("y", 0) - 5 <= center_y <= other.get("y", 0) + other.get("height", 0) + 5 for p in people + additions):
                continue
            column = find_matching_ocr_column(region, row.get("columns", [])) or {}
            text = str(column.get("text") or "")
            normalized = clean_hanzi_text(text)
            if not 2 <= len(normalized) <= 4 or normalized == "親族也":
                text = ""
            candidate_id = Path(page_name(page)).stem + "_RECOVERED_" + uuid.uuid4().hex[:12].upper()
            additions.append({"person_id": candidate_id, "source_page": page_name(page),
                              "source_row_id": row.get("row_id"), "source_column_id": column.get("column_id") or candidate_id,
                              "bbox": box, "raw_name_ocr": text, "name_hanja_candidate": clean_hanzi_text(text),
                              "ocr_confidence": column.get("mean_confidence") if text else None,
                              "review_status": "needs_review", "candidate_type": "review_geometry_recovery",
                              "recognition_status": "existing_ocr_reference" if text else "manual_transcription_required",
                              "geometry": region, "ocr_status": "no_new_ocr_inference"})
    return additions
