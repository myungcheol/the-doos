#!/usr/bin/env python3
"""Validate one parsed page JSON against the project rules.

This is intentionally dependency-free. `schema/page.schema.json` is the
machine-readable contract; this module implements the subset that matters for
review and gives readable Korean errors.

Usage:
    python3 scripts/validate_page.py data/parsed/genealogy/0025.json
    python3 scripts/validate_page.py f.json --section genealogy --page 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PAGE_TYPES = {
    "genealogy",
    "preface",
    "photo",
    "index",
    "generation_name_table",
    "property",
    "officers",
    "subscription",
    "colophon",
    "cover",
    "unknown",
}
RELATIONS = {
    "self",
    "son",
    "daughter",
    "brother",
    "sister",
    "sibling",
    "grandson",
    "granddaughter",
    "descendant",
    "spouse",
    "son_in_law",
    "daughter_in_law",
    "unknown",
}
CERTAINTY = {"exact", "probable", "uncertain", "unknown"}
DIRECTIONS = {"up", "down"}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_bbox(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(v, (int, float)) for v in value):
        errors.append(f"{where}: bbox는 숫자 4개 배열이어야 합니다.")
        return
    if any(v < 0 or v > 1000 for v in value):
        errors.append(f"{where}: bbox 값은 0~1000이어야 합니다.")


def _check_page_ref(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where}: page_ref는 객체 또는 null이어야 합니다.")
        return
    if not value.get("raw"):
        errors.append(f"{where}: page_ref.raw가 비었습니다.")
    if value.get("direction") not in DIRECTIONS:
        errors.append(f"{where}: page_ref.direction은 up/down이어야 합니다.")
    if value.get("target_section") not in {"frontmatter", "genealogy"}:
        errors.append(f"{where}: page_ref.target_section이 올바르지 않습니다.")
    if not _is_int(value.get("target_page_no")) or value.get("target_page_no", 0) < 1:
        errors.append(f"{where}: page_ref.target_page_no가 정수가 아닙니다.")
    _check_bbox(value.get("bbox"), f"{where}.page_ref", errors)


def _check_date(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where}: 날짜 블록은 객체여야 합니다.")
        return
    if "raw" not in value:
        errors.append(f"{where}: raw 필드가 없습니다.")
    if value.get("certainty") is not None and value.get("certainty") not in CERTAINTY:
        errors.append(f"{where}: certainty 값이 올바르지 않습니다.")


def _check_burial(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where}: burial은 객체여야 합니다.")
        return
    if "raw" not in value:
        errors.append(f"{where}: burial.raw가 없습니다.")
    if value.get("certainty") is not None and value.get("certainty") not in CERTAINTY:
        errors.append(f"{where}: burial.certainty 값이 올바르지 않습니다.")


def _check_person(person: Any, where: str, errors: list[str]) -> None:
    if not isinstance(person, dict):
        errors.append(f"{where}: person이 객체가 아닙니다.")
        return
    if not person.get("raw_name"):
        errors.append(f"{where}: person.raw_name이 비었습니다.")
    aliases = person.get("aliases")
    if aliases is not None:
        if not isinstance(aliases, list):
            errors.append(f"{where}: aliases는 배열이어야 합니다.")
        else:
            for index, alias in enumerate(aliases):
                if not isinstance(alias, dict) or not alias.get("value"):
                    errors.append(f"{where}.aliases[{index}]: type/value가 필요합니다.")
                elif alias.get("type") not in {"字", "號", "其他"}:
                    errors.append(f"{where}.aliases[{index}]: type은 字/號/其他이어야 합니다.")
    _check_date(person.get("birth"), f"{where}.birth", errors)
    _check_date(person.get("death"), f"{where}.death", errors)
    _check_burial(person.get("burial"), f"{where}.burial", errors)
    spouses = person.get("spouses")
    if spouses is not None:
        if not isinstance(spouses, list):
            errors.append(f"{where}: spouses는 배열이어야 합니다.")
        else:
            for index, spouse in enumerate(spouses):
                if not isinstance(spouse, dict) or not spouse.get("raw_name"):
                    errors.append(f"{where}.spouses[{index}]: raw_name이 필요합니다.")
                    continue
                _check_burial(spouse.get("burial"), f"{where}.spouses[{index}].burial", errors)
                if spouse.get("relation") not in {None, "wife", "husband", "son_in_law", "daughter_in_law", "unknown"}:
                    errors.append(f"{where}.spouses[{index}]: relation 값이 올바르지 않습니다.")
    children = person.get("children")
    if children is not None and not isinstance(children, list):
        errors.append(f"{where}: children은 배열이어야 합니다.")
    _check_page_ref(person.get("page_ref"), where, errors)
    _check_bbox(person.get("bbox"), where, errors)


def validate(
    data: Any,
    expected_section: str | None = None,
    expected_page: int | None = None,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ["최상위 값이 JSON 객체가 아닙니다."], warnings

    page = data.get("page")
    if not isinstance(page, dict):
        errors.append("page 객체가 없습니다.")
    else:
        if page.get("section") not in {"frontmatter", "genealogy"}:
            errors.append("page.section은 frontmatter/genealogy여야 합니다.")
        if not _is_int(page.get("printed_page_no")) or page.get("printed_page_no", 0) < 1:
            errors.append("page.printed_page_no가 양의 정수가 아닙니다.")
        if page.get("page_type") not in PAGE_TYPES:
            errors.append("page.page_type이 올바르지 않습니다.")
        if expected_section and page.get("section") != expected_section:
            errors.append(f"page.section이 기대값 {expected_section}과 다릅니다: {page.get('section')}")
        if expected_page is not None and page.get("printed_page_no") != expected_page:
            errors.append(f"page.printed_page_no가 기대값 {expected_page}과 다릅니다: {page.get('printed_page_no')}")

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("entries 배열이 없습니다.")
        entries = []

    seen: set[tuple[int, int]] = set()
    for index, entry in enumerate(entries):
        where = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: 객체가 아닙니다.")
            continue
        row, column = entry.get("row"), entry.get("column")
        if not _is_int(row) or row < 1:
            errors.append(f"{where}: row가 양의 정수가 아닙니다.")
        if not _is_int(column) or column < 1:
            errors.append(f"{where}: column이 양의 정수가 아닙니다.")
        if _is_int(row) and _is_int(column):
            key = (row, column)
            if key in seen:
                errors.append(f"{where}: (row={row}, column={column})가 중복됩니다.")
            seen.add(key)
        offset = entry.get("generation_offset")
        if offset is not None and (not _is_int(offset) or offset < 0):
            errors.append(f"{where}: generation_offset이 0 이상의 정수가 아닙니다.")
        if entry.get("relation_to_subject") not in RELATIONS:
            errors.append(f"{where}: relation_to_subject가 올바르지 않습니다.")
        _check_person(entry.get("person"), f"{where}.person", errors)
        _check_bbox(entry.get("bbox"), where, errors)

    subjects = data.get("subjects")
    if subjects is not None:
        if not isinstance(subjects, list):
            errors.append("subjects는 배열이어야 합니다.")
        else:
            for index, subject in enumerate(subjects):
                where = f"subjects[{index}]"
                if not isinstance(subject, dict):
                    errors.append(f"{where}: 객체가 아닙니다.")
                    continue
                _check_person(subject, where, errors)
                _check_page_ref(subject.get("page_ref"), where, errors)

    if page and page.get("page_type") != "genealogy" and entries:
        warnings.append("genealogy가 아닌 페이지에 entries가 있습니다. 보조 필드 사용을 검토하세요.")
    if page and page.get("page_type") == "genealogy" and not entries:
        warnings.append("genealogy 페이지인데 entries가 비었습니다. unreadable_regions를 확인하세요.")

    human_count = 0
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and (
            entry.get("needs_human") or (isinstance(entry.get("person"), dict) and entry["person"].get("needs_human"))
        ):
            human_count += 1
    if human_count:
        warnings.append(f"needs_human 항목 {human_count}개. 검수 화면에서 확인하세요.")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--section", choices=["frontmatter", "genealogy"])
    parser.add_argument("--page", type=int)
    args = parser.parse_args()

    failed = False
    for path in args.paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report parse errors to the user
            print(f"FAIL {path}: JSON parse error: {exc}")
            failed = True
            continue
        errors, warnings = validate(data, args.section, args.page)
        if errors:
            failed = True
            print(f"FAIL {path}: {len(errors)} error(s)")
            for message in errors:
                print(f"  - {message}")
        else:
            print(f"OK   {path}")
        for message in warnings:
            print(f"  ! {message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
