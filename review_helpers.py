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
