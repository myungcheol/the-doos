"""Small pure helpers for review UI labels and relationship filtering."""
from __future__ import annotations

from typing import Any, Callable


def person_number_map(people: list[dict[str, Any]]) -> dict[str, int]:
    """Return the 1-based order used by the numbered boxes on the page image."""
    return {
        str(person.get("person_id")): index
        for index, person in enumerate(people, start=1)
        if person.get("person_id") is not None
    }


def format_person_reference(
    person_id: str | None,
    person_lookup: dict[str, dict[str, Any]],
    number_map: dict[str, int],
    name_getter: Callable[[dict[str, Any]], str],
) -> str:
    """Format a person exactly like the number shown beside their scan bbox."""
    if not person_id:
        return "인물 미정"
    person = person_lookup.get(person_id)
    if person is None:
        return str(person_id)
    number = number_map.get(person_id)
    name = name_getter(person) or "(이름 미인식)"
    return f"{number}. {name}" if number is not None else name


def filter_relationships_for_person(
    relationships: list[dict[str, Any]], person_id: str | None
) -> list[dict[str, Any]]:
    """Return relationships where the selected person is parent or child."""
    if not person_id:
        return list(relationships)
    return [
        rel for rel in relationships
        if rel.get("parent_candidate_id") == person_id
        or rel.get("child_candidate_id") == person_id
    ]


def format_relationship_label(
    relationship: dict[str, Any],
    person_lookup: dict[str, dict[str, Any]],
    number_map: dict[str, int],
    name_getter: Callable[[dict[str, Any]], str],
) -> str:
    """Format relationship with the same 1-based person numbers as the scan overlay."""
    status = relationship.get("review_status", "needs_review")
    parent = format_person_reference(
        relationship.get("parent_candidate_id"), person_lookup, number_map, name_getter
    )
    child = format_person_reference(
        relationship.get("child_candidate_id"), person_lookup, number_map, name_getter
    )
    return f"{status} · {parent} → {child}"


def relationship_bbox_anchors(
    parent_bbox: dict[str, Any], child_bbox: dict[str, Any]
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (parent bottom-center, child top-center) in source-image coordinates."""
    parent_x = float(parent_bbox.get("x", 0))
    parent_y = float(parent_bbox.get("y", 0))
    parent_width = float(parent_bbox.get("width", 0))
    parent_height = float(parent_bbox.get("height", 0))
    child_x = float(child_bbox.get("x", 0))
    child_y = float(child_bbox.get("y", 0))
    child_width = float(child_bbox.get("width", 0))
    return (
        (parent_x + parent_width / 2.0, parent_y + parent_height),
        (child_x + child_width / 2.0, child_y),
    )


def resolve_person_field_value(
    field: str,
    updates: dict[str, Any],
    person: dict[str, Any],
    draft_values: dict[str, Any],
    fallback: Any = "",
) -> Any:
    """Prioritize reviewer edits, then source values, then automatic OCR drafts."""
    if field in updates:
        value = updates[field]
    elif person.get(field) not in (None, ""):
        value = person[field]
    else:
        value = draft_values.get(field, fallback)
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return value
    return str(value)
