"""Stable person identity, source provenance, and raw/reviewed data helpers.

Person IDs are opaque UUID-based keys. Edition/page/column coordinates are stored
as source occurrences, never used as a person's permanent identity.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any


PERSON_FIELDS = (
    "transcribed_name_hanja", "sex_marker", "gender", "generation_number",
    "courtesy_name_hanja", "pen_name_hanja", "birth_text", "death_text",
    "birth_date", "death_date", "birth_solar", "death_solar",
    "office_title", "spouses", "spouse_text", "burial_text", "biography_text",
    "notes", "review_status", "information_review_status",
)

MARKER_MAP = {"子": "male", "女": "female"}


def strip_name_marker(value: Any) -> tuple[str, str | None, str | None]:
    """Remove a leading genealogy marker (子/女) from the name only."""
    text = "" if value is None else str(value).strip()
    if text and text[0] in MARKER_MAP:
        marker = text[0]
        return text[1:].strip(), marker, MARKER_MAP[marker]
    return text, None, None


def person_local_key(person: dict[str, Any], edition_id: str | None = None) -> str:
    """Stable key for the same OCR occurrence, not a cross-edition person ID."""
    bbox = person.get("bbox") or {}
    edition = edition_id or person.get("edition_id") or "default-edition"
    source_page = person.get("source_page", "")
    row_id = person.get("source_row_id", "")
    column_id = person.get("source_column_id", "")
    if source_page and row_id and column_id and bbox:
        locator = ":".join(str(bbox.get(k, "")) for k in ("x", "y", "width", "height"))
        return f"occ::{edition}::{source_page}::{row_id}::{column_id}::{locator}"
    return f"candidate::{edition}::{source_page}::{person.get('person_id', '')}"


def ensure_person_uid(person: dict[str, Any], state: dict[str, Any]) -> str:
    """Return an ID that persists in review_state.json for this OCR occurrence."""
    mapping = state.setdefault("person_uid_map", {})
    edition_id = (state.get("edition") or {}).get("edition_id")
    key = person_local_key(person, edition_id)
    if mapping.get(key):
        return str(mapping[key])
    existing = person.get("person_uid")
    value = str(existing) if existing else f"PER_{uuid.uuid4().hex.upper()}"
    mapping[key] = value
    return value


def make_source_occurrence(
    person: dict[str, Any], page_result: dict[str, Any] | None,
    edition: dict[str, Any] | None, page_metadata: dict[str, Any] | None = None,
    page_people: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    edition = edition or {}
    page_metadata = page_metadata or {}
    source_page = str(person.get("source_page") or (page_result or {}).get("source_page") or "")
    row_id = person.get("source_row_id")
    column_id = person.get("source_column_id")
    column_order = None
    row_number = None
    if page_result:
        for row in page_result.get("rows", []) or []:
            if row.get("row_id") == row_id:
                row_number = row.get("row_number")
                for col in row.get("columns", []) or []:
                    if col.get("column_id") == column_id:
                        column_order = col.get("order_right_to_left")
                        break
                break
    bbox = dict(person.get("bbox") or {})
    # Position is the vertical order if multiple candidate records share a column.
    position_in_column = None
    if column_id:
        same_column = [p for p in (page_people or [])
                       if p.get("source_column_id") == column_id and p.get("source_page") == source_page]
        same_column.sort(key=lambda p: float((p.get("bbox") or {}).get("y", 0)))
        for idx, candidate in enumerate(same_column, start=1):
            if candidate.get("person_id") == person.get("person_id"):
                position_in_column = idx
                break
        if position_in_column is None:
            position_in_column = 1
    edition_id = str(edition.get("edition_id") or "jokbo-1987")
    identity_source = "|".join([
        edition_id, source_page, str(row_id or ""), str(column_id or ""),
        str(bbox.get("x", "")), str(bbox.get("y", "")),
    ])
    occurrence_id = "OCC_" + uuid.uuid5(uuid.NAMESPACE_URL, identity_source).hex.upper()
    return {
        "source_occurrence_id": occurrence_id,
        "edition_id": edition_id,
        "publication_year": edition.get("publication_year", 1987),
        "volume": edition.get("volume") or None,
        "printed_page": page_metadata.get("printed_page") or None,
        "scan_page": source_page,
        "source_image": (page_result or {}).get("source_image"),
        "source_row_id": row_id,
        "row_number": row_number,
        "source_column_id": column_id,
        "column_number_right_to_left": column_order,
        "position_in_column": position_in_column,
        "bbox": bbox,
    }


def build_raw_data(
    person: dict[str, Any], page_result: dict[str, Any] | None,
    draft: dict[str, Any] | None, occurrence: dict[str, Any],
) -> dict[str, Any]:
    raw_name = str(person.get("raw_name_ocr") or person.get("name_hanja_candidate") or "")
    normalized, marker, gender = strip_name_marker(raw_name)
    draft = draft or {}
    evidence = draft.get("evidence") or {}
    field_sources = draft.get("field_sources") or {}
    raw_fields: dict[str, Any] = {}
    for field in ("birth_text", "death_text", "office_title", "spouse_text",
                  "burial_text", "courtesy_name_hanja", "pen_name_hanja"):
        raw_fields[field] = {
            "text": evidence.get(field, []),
            "columns": field_sources.get(field, []),
        }
    return {
        "image": {
            "source_image": (page_result or {}).get("source_image"),
            "image_file": person.get("image_file"),
            "bbox": dict(person.get("bbox") or {}),
        },
        "name_ocr": {
            "raw_text": raw_name,
            "normalized_name_candidate": normalized,
            "leading_marker": marker,
            "inferred_gender": gender,
            "confidence": person.get("ocr_confidence"),
            "bbox": dict(person.get("bbox") or {}),
            "evidence_text": person.get("evidence_text"),
            "hypotheses": person.get("ranked_ocr_hypotheses") or [],
        },
        "record_ocr": {
            "text": draft.get("source_record_ocr_text") or person.get("evidence_text") or "",
            "source_row_id": person.get("source_row_id"),
            "source_column_ids": draft.get("source_column_ids") or [],
            # Retain every column bbox so the browser viewer can reveal OCR
            # evidence immediately when an image click selects a person.
            "columns": draft.get("columns") or [],
            "method": draft.get("method"),
        },
        "field_ocr": raw_fields,
        "source_occurrence": occurrence,
    }


def build_reviewed_data(person: dict[str, Any]) -> dict[str, Any]:
    raw_name = str(person.get("raw_name_ocr") or person.get("name_hanja_candidate") or "")
    candidate_name, candidate_marker, candidate_gender = strip_name_marker(raw_name)
    reviewed_name, reviewed_marker, reviewed_gender = strip_name_marker(
        person.get("transcribed_name_hanja") or candidate_name
    )
    marker = person.get("sex_marker") or reviewed_marker or candidate_marker
    gender = person.get("gender") or (MARKER_MAP.get(marker) if marker else None) or reviewed_gender or candidate_gender
    spouses = person.get("spouses")
    if not isinstance(spouses, list):
        spouses = []
        legacy = person.get("spouse_text")
        if legacy:
            spouses = [{
                "type": "wife", "name_and_record": str(legacy), "notes": "",
                "review_status": "needs_review",
            }]
    return {
        "name_hanja": reviewed_name or None,
        "sex_marker": marker,
        "gender": gender,
        "generation_number": person.get("generation_number"),
        "courtesy_name_hanja": person.get("courtesy_name_hanja"),
        "pen_name_hanja": person.get("pen_name_hanja"),
        "birth_text": person.get("birth_text"),
        "death_text": person.get("death_text"),
        "birth_date": person.get("birth_date"),
        "death_date": person.get("death_date"),
        "birth_solar": person.get("birth_solar"),
        "death_solar": person.get("death_solar"),
        "office_title": person.get("office_title"),
        "spouses": spouses,
        "burial_text": person.get("burial_text"),
        "biography_text": person.get("biography_text"),
        "notes": person.get("notes"),
        "review_status": person.get("review_status", "needs_review"),
        "information_review_status": person.get("information_review_status", "needs_review"),
    }


def build_person_registry(people: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge this export's source occurrences into a reusable identity registry."""
    existing = existing or {}
    registry = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "persons": dict(existing.get("persons") or {}),
    }
    for person in people:
        uid = person.get("person_uid")
        if not uid:
            continue
        reviewed = person.get("reviewed_data") or build_reviewed_data(person)
        name = reviewed.get("name_hanja") or person.get("name_hanja_candidate") or ""
        entry = registry["persons"].setdefault(uid, {
            "person_uid": uid, "canonical_name_hanja": name,
            "aliases": [], "source_occurrences": [],
        })
        if name:
            aliases = set(entry.get("aliases") or [])
            old_canonical = entry.get("canonical_name_hanja")
            if old_canonical and old_canonical != name:
                aliases.add(old_canonical)
            if name != old_canonical:
                aliases.add(name)
            entry["aliases"] = sorted(aliases)
            if reviewed.get("review_status") == "confirmed" or not old_canonical:
                entry["canonical_name_hanja"] = name
        previous_reviewed = dict(entry.get("reviewed_data") or {})
        previous_occurrence = (entry.get("raw_data_latest") or {}).get("source_occurrence") or {}
        current_occurrence = (person.get("raw_data") or {}).get("source_occurrence") or {}
        same_occurrence = (previous_occurrence.get("source_occurrence_id")
                           and previous_occurrence.get("source_occurrence_id") == current_occurrence.get("source_occurrence_id"))
        merged_reviewed = dict(previous_reviewed)
        for field, value in reviewed.items():
            if value not in (None, "", [], {}):
                merged_reviewed[field] = value
            elif field not in merged_reviewed:
                merged_reviewed[field] = value
        # A corrected date on the same OCR occurrence invalidates its old
        # conversion. Keep an older edition's reviewed date when a different
        # occurrence has no usable date of its own.
        if same_occurrence:
            for event in ("birth", "death"):
                for suffix in ("date", "solar"):
                    field = f"{event}_{suffix}"
                    old_value = previous_reviewed.get(field)
                    if (isinstance(old_value, dict) and reviewed.get(field) is None
                            and old_value.get("source_text") != reviewed.get(f"{event}_text")):
                        merged_reviewed[field] = None
        # Do not downgrade an already confirmed identity record just because a
        # new edition occurrence has not yet been reviewed.
        if previous_reviewed.get("review_status") == "confirmed" and reviewed.get("review_status") != "confirmed":
            merged_reviewed["review_status"] = "confirmed"
        if previous_reviewed.get("information_review_status") == "confirmed" and reviewed.get("information_review_status") != "confirmed":
            merged_reviewed["information_review_status"] = "confirmed"
        entry["reviewed_data"] = merged_reviewed
        entry["raw_data_latest"] = person.get("raw_data") or {}
        occurrence = (person.get("raw_data") or {}).get("source_occurrence")
        if occurrence:
            current = entry.setdefault("source_occurrences", [])
            oid = occurrence.get("source_occurrence_id")
            if not any(x.get("source_occurrence_id") == oid for x in current):
                current.append(occurrence)
    return registry


def registry_options(registry: dict[str, Any], exclude_uid: str | None = None) -> list[tuple[str, str]]:
    options = []
    for uid, entry in (registry.get("persons") or {}).items():
        if uid == exclude_uid:
            continue
        name = entry.get("canonical_name_hanja") or "(이름 미확인)"
        year_pages = []
        for occurrence in entry.get("source_occurrences", []):
            year_pages.append(f"{occurrence.get('publication_year') or '?'}년 {occurrence.get('scan_page') or '?'}")
        suffix = f" · {', '.join(year_pages[:2])}" if year_pages else ""
        options.append((uid, f"{name} · {uid}{suffix}"))
    return sorted(options, key=lambda x: x[1])
