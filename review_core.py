"""Shared persistence and source-image helpers for the desktop review app."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ocr_storage import has_ocr_output

from historical_dates import date_parts_with_solar
from person_data_model import (
    build_raw_data, build_reviewed_data, ensure_person_uid,
    make_source_occurrence, person_local_key, strip_name_marker,
)
from person_info_extractor import extract_person_info_draft
from review_extensions import (
    continuation_field_parts, continuation_needs_review,
)


def find_output_root(raw_path: str) -> Path | None:
    path = Path(raw_path).expanduser().resolve()
    candidates = [path, path / "paddleocr"]
    for candidate in candidates:
        if has_ocr_output(candidate):
            return candidate
    return None


def effective_name(person: dict[str, Any], state: dict[str, Any]) -> str:
    update = state.get("people_updates", {}).get(person.get("person_id"), {})
    candidate = (update.get("transcribed_name_hanja")
                 or person.get("transcribed_name_hanja")
                 or person.get("name_hanja_candidate") or "")
    normalized, _, _ = strip_name_marker(candidate)
    return normalized or "(이름 미인식)"


def relationship_key(rel: dict[str, Any]) -> str:
    return f"{rel.get('source_page', '')}::{rel.get('relationship_id', '')}"


def effective_relationship(rel: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    updated = dict(rel)
    updates = state.get("relationship_updates", {})
    updated.update(updates.get(relationship_key(rel), {}))
    return updated


def would_create_cycle(parent_id: str, child_id: str, relationships: list[dict[str, Any]]) -> bool:
    """Return True when adding parent->child would close a cycle in confirmed edges."""
    adjacency: dict[str, list[str]] = {}
    for rel in relationships:
        if rel.get("review_status") != "confirmed":
            continue
        parent = rel.get("parent_candidate_id")
        child = rel.get("child_candidate_id")
        if parent and child:
            adjacency.setdefault(parent, []).append(child)
    stack = [child_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == parent_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency.get(current, []))
    return False


def write_exports(root: Path, people: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> None:
    (root / "reviewed_people.json").write_text(
        json.dumps(people, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "reviewed_relationships.json").write_text(
        json.dumps(relationships, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (root / "reviewed_people.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "person_uid", "person_id", "source_page", "name_hanja_candidate", "raw_name_ocr",
            "transcribed_name_hanja", "sex_marker", "gender", "review_status",
            "generation_number", "courtesy_name_hanja", "pen_name_hanja",
            "birth_text", "death_text", "birth_date", "death_date", "birth_solar", "death_solar",
            "office_title", "spouse_text", "spouses",
            "burial_text", "biography_text", "notes", "information_review_status",
            "source_record_ocr_text", "raw_data", "reviewed_data", "source_occurrences",
            "bbox", "image_file", "ocr_confidence",
        ], extrasaction="ignore")
        writer.writeheader()
        csv_people = []
        for person in people:
            row = dict(person)
            for nested_key in ("spouses", "birth_date", "death_date", "birth_solar", "death_solar",
                               "raw_data", "reviewed_data", "source_occurrences", "bbox"):
                if nested_key in row:
                    row[nested_key] = json.dumps(row[nested_key], ensure_ascii=False)
            csv_people.append(row)
        writer.writerows(csv_people)
    with (root / "reviewed_relationships.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "relationship_id", "source_page", "type", "parent_candidate_id",
            "parent_name_hanja_candidate", "parent_person_uid", "child_candidate_id",
            "child_name_hanja_candidate", "child_person_uid", "relationship_basis",
            "review_status", "warning",
        ], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(relationships)


def build_review_data(root: Path, base_people: list[dict[str, Any]],
                      base_relationships: list[dict[str, Any]], state: dict[str, Any],
                      page_results: list[dict[str, Any]] | None = None):
    from review_extensions import merge_review_sources, apply_continuations
    base_people, base_relationships, page_results = merge_review_sources(
        base_people, base_relationships, page_results or [], state
    )
    page_result_map = {
        str(item.get("source_page") or Path(item.get("source_image", "page")).name): item
        for item in page_results
    }
    edition = state.get("edition", {"edition_id": "jokbo-1987", "publication_year": 1987})
    page_metadata = state.get("page_metadata", {})
    people = []
    by_page_people: dict[str, list[dict[str, Any]]] = {}
    for raw in base_people:
        by_page_people.setdefault(str(raw.get("source_page", "")), []).append(raw)
    draft_cache: dict[str, dict[str, Any]] = {}
    for raw in base_people:
        person = dict(raw)
        local_key = person_local_key(person, edition.get("edition_id"))
        uid = state.get("person_uid_map", {}).get(local_key) or person.get("person_uid")
        if not uid:
            uid = ensure_person_uid(person, state)
        person["person_uid"] = str(uid)
        # Keep the unmodified OCR name permanently, while normalizing the candidate
        # name used in review and relationship labels.
        raw_name = str(person.get("raw_name_ocr") or person.get("name_hanja_candidate") or "")
        normalized_name, marker, gender = strip_name_marker(raw_name)
        person["raw_name_ocr"] = raw_name
        person["raw_name_marker"] = marker
        person["name_hanja_candidate"] = normalized_name
        if marker:
            person.setdefault("sex_marker", marker)
            person.setdefault("gender", gender)
        update = state.get("people_updates", {}).get(person.get("person_id"), {})
        person.update(update)
        if continuation_needs_review(continuation_field_parts(person, state), update):
            person["information_review_status"] = "needs_review"
        cleaned_review_name, update_marker, update_gender = strip_name_marker(
            person.get("transcribed_name_hanja") or person.get("name_hanja_candidate")
        )
        if person.get("transcribed_name_hanja"):
            person["transcribed_name_hanja"] = cleaned_review_name
        if update_marker and not person.get("sex_marker"):
            person["sex_marker"] = update_marker
            person["gender"] = update_gender

        source_page = str(person.get("source_page", ""))
        page_result = page_result_map.get(source_page)
        cache_key = f"{source_page}::{person.get('person_id')}"
        if cache_key not in draft_cache:
            if page_result:
                draft_cache[cache_key] = extract_person_info_draft(
                    raw, page_result, by_page_people.get(source_page, [])
                )
            else:
                draft_cache[cache_key] = {}
        # Always use the current extractor result for raw OCR evidence/bboxes.
        # A persisted draft from an older UI version may not contain field source
        # boxes, so it must not overwrite the freshly recomputed source geometry.
        draft = dict(draft_cache[cache_key] or {})
        occurrence = make_source_occurrence(
            raw, page_result, edition, page_metadata.get(source_page, {}),
            by_page_people.get(source_page, []),
        )
        person["source_occurrences"] = [occurrence]
        person["raw_data"] = build_raw_data(raw, page_result, draft, occurrence)
        apply_continuations(person, state)
        for event in ("birth", "death"):
            date_key = f"{event}_date"
            if date_key not in update and not person.get(date_key):
                source = person.get(f"{event}_text") or (draft.get("draft_values") or {}).get(f"{event}_text")
                parts = date_parts_with_solar(source, event, solar=person.get(f"{event}_solar"))
                if parts:
                    person[date_key] = parts
        person["source_record_ocr_text"] = (
            update.get("source_record_ocr_text")
            or draft.get("source_record_ocr_text")
            or raw.get("evidence_text")
        )
        person["reviewed_data"] = build_reviewed_data(person)
        people.append(person)

    rels = [effective_relationship(rel, state) for rel in base_relationships]
    for manual in state.get("manual_relationships", []):
        rels.append(effective_relationship(dict(manual), state))
    by_id = {p.get("person_id"): p for p in people}
    for rel in rels:
        parent = by_id.get(rel.get("parent_candidate_id"), {})
        child = by_id.get(rel.get("child_candidate_id"), {})
        if parent:
            rel["parent_name_hanja_candidate"] = effective_name(parent, state)
            rel["parent_person_uid"] = parent.get("person_uid")
        if child:
            rel["child_name_hanja_candidate"] = effective_name(child, state)
            rel["child_person_uid"] = child.get("person_uid")
    return people, rels


def get_page_image(page_result: dict[str, Any], page_dir: str) -> tuple[np.ndarray, tuple[int, int], str]:
    """Return image, coordinate offset (x,y), and source label.

    Person bboxes are always in original-page coordinates. If the original
    scan is unavailable, table_roi.jpg is used and the stored ROI offset is
    subtracted while drawing / added after clicks.
    """
    page_dir = Path(page_dir)
    source = Path(str(page_result.get("source_image", ""))).expanduser()
    if source.exists():
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is not None:
            return image, (0, 0), str(source)
    roi_image = cv2.imread(str(page_dir / "table_roi.jpg"), cv2.IMREAD_COLOR)
    if roi_image is not None:
        roi = page_result.get("table_roi") or {}
        return roi_image, (int(roi.get("x", 0)), int(roi.get("y", 0))), "저장된 table_roi.jpg"
    raise FileNotFoundError(
        f"원본 이미지와 {page_dir / 'table_roi.jpg'}를 모두 찾지 못했습니다."
    )


def parse_optional_generation(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("세대는 숫자로 입력하거나 비워 두세요.") from exc


def save_state(root: Path, state: dict[str, Any], base_people: list[dict[str, Any]],
               base_relationships: list[dict[str, Any]],
               page_results: list[dict[str, Any]] | None = None) -> None:
    state["updated_at"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
    (root / "review_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    people, rels = build_review_data(root, base_people, base_relationships, state, page_results)
    write_exports(root, people, rels)
