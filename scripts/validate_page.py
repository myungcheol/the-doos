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
# The subject lives in `subjects[]`, so an entry must never be the subject.
ENTRY_RELATIONS = RELATIONS - {"self"}
SPOUSE_RELATIONS = {"wife", "husband", "concubine", "unknown"}
CHILD_RELATIONS = {"son", "daughter", "adopted_son", "unknown"}
CERTAINTY = {"exact", "probable", "uncertain", "unknown"}
DIRECTIONS = {"up", "down"}
MAX_PAGE = {"frontmatter": 93, "genealogy": 938}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_string(value: Any, where: str, errors: list[str], *, nullable: bool = True) -> None:
    if value is None:
        if not nullable:
            errors.append(f"{where}: 값이 비었습니다.")
        return
    if not isinstance(value, str):
        errors.append(f"{where}: 문자열이어야 합니다.")


def _check_string_list(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{where}: 배열이어야 합니다.")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{where}[{index}]: 문자열이어야 합니다.")


def _check_bbox(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(v, (int, float)) for v in value):
        errors.append(f"{where}: bbox는 숫자 4개 배열이어야 합니다.")
        return
    if any(v < 0 or v > 1000 for v in value):
        errors.append(f"{where}: bbox 값은 0~1000이어야 합니다.")


def _check_confidence(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        errors.append(f"{where}: confidence는 0~1 숫자여야 합니다.")


def _check_page_ref(
    value: Any,
    where: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where}: page_ref는 객체 또는 null이어야 합니다.")
        return
    raw = value.get("raw")
    if not raw:
        errors.append(f"{where}: page_ref.raw가 비었습니다.")
    elif isinstance(raw, str) and raw[:1] in {"T", "F"}:
        warnings.append(f"{where}: page_ref.raw가 {raw[0]}로 시작합니다. 下로 정규화하세요: {raw}")
    if value.get("direction") not in DIRECTIONS:
        errors.append(f"{where}: page_ref.direction은 up/down이어야 합니다.")
    target_section = value.get("target_section")
    if target_section not in {"frontmatter", "genealogy"}:
        errors.append(f"{where}: page_ref.target_section이 올바르지 않습니다.")
    target_page_no = value.get("target_page_no")
    if not _is_int(target_page_no) or target_page_no < 1:
        errors.append(f"{where}: page_ref.target_page_no가 정수가 아닙니다.")
    elif target_section in MAX_PAGE and target_page_no > MAX_PAGE[target_section]:
        errors.append(
            f"{where}: page_ref.target_page_no={target_page_no}가 {target_section} 범위(1~{MAX_PAGE[target_section]})를 벗어납니다."
        )
    _check_bbox(value.get("bbox"), f"{where}.page_ref", errors)
    _check_confidence(value.get("confidence"), f"{where}.page_ref", errors)


def _check_date(value: Any, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where}: 날짜 블록은 객체여야 합니다.")
        return
    if "raw" not in value:
        errors.append(f"{where}: raw 필드가 없습니다.")
    else:
        _check_string(value.get("raw"), f"{where}.raw", errors)
    for field in ("king_era", "ganji", "date_text"):
        _check_string(value.get(field), f"{where}.{field}", errors)
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
    else:
        _check_string(value.get("raw"), f"{where}.raw", errors)
    for field in ("location", "orientation", "note"):
        _check_string(value.get(field), f"{where}.{field}", errors)
    if value.get("certainty") is not None and value.get("certainty") not in CERTAINTY:
        errors.append(f"{where}: burial.certainty 값이 올바르지 않습니다.")


def _check_spouse(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: 배우자는 객체여야 합니다.")
        return
    printed = value.get("as_printed") or value.get("raw_name")
    if not printed:
        errors.append(f"{where}: as_printed이 필요합니다.")
    else:
        _check_string(printed, f"{where}.as_printed", errors, nullable=False)
    for field in ("name_hanja", "bonkwan", "father"):
        _check_string(value.get(field), f"{where}.{field}", errors)
    if "relation" in value and value.get("relation") not in SPOUSE_RELATIONS:
        errors.append(f"{where}: relation은 wife/husband/concubine/unknown 중 하나여야 합니다.")
    _check_date(value.get("birth"), f"{where}.birth", errors)
    _check_date(value.get("death"), f"{where}.death", errors)
    _check_burial(value.get("burial"), f"{where}.burial", errors)
    if value.get("certainty") is not None and value.get("certainty") not in CERTAINTY:
        errors.append(f"{where}: certainty 값이 올바르지 않습니다.")


def _check_child(value: Any, where: str, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: 자녀는 객체여야 합니다.")
        return
    printed = value.get("as_printed") or value.get("raw_name")
    if not printed:
        errors.append(f"{where}: as_printed이 필요합니다.")
    else:
        _check_string(printed, f"{where}.as_printed", errors, nullable=False)
    for field in ("name_hanja", "prefix"):
        _check_string(value.get(field), f"{where}.{field}", errors)
    if "relation" in value and value.get("relation") not in CHILD_RELATIONS:
        errors.append(f"{where}: relation은 son/daughter/adopted_son/unknown 중 하나여야 합니다.")
    _check_page_ref(value.get("page_ref"), where, errors, warnings)


def _check_person(
    person: Any,
    where: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(person, dict):
        errors.append(f"{where}: person이 객체가 아닙니다.")
        return
    printed_name = person.get("as_printed") or person.get("raw_name")
    if not printed_name:
        errors.append(f"{where}: person.as_printed이 비었습니다.")
    else:
        _check_string(printed_name, f"{where}.as_printed", errors, nullable=False)
    for field in ("name_hanja", "name_hangul", "prefix", "generation_char"):
        _check_string(person.get(field), f"{where}.{field}", errors)

    generation_no = person.get("generation_no")
    if generation_no is not None and (not _is_int(generation_no) or generation_no < 1):
        errors.append(f"{where}.generation_no: 1 이상의 정수 또는 null이어야 합니다.")

    hint = person.get("generation_hint")
    if hint is not None:
        if not isinstance(hint, dict):
            errors.append(f"{where}.generation_hint: 객체 또는 null이어야 합니다.")
        else:
            if not _is_int(hint.get("value")):
                errors.append(f"{where}.generation_hint.value: 정수여야 합니다.")
            _check_string(hint.get("basis"), f"{where}.generation_hint.basis", errors)
            if hint.get("certainty") not in {"probable", "uncertain"}:
                errors.append(f"{where}.generation_hint.certainty: probable/uncertain이어야 합니다.")

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
    if "offices" in person:
        _check_string_list(person.get("offices"), f"{where}.offices", errors)
    if "notes" in person:
        _check_string_list(person.get("notes"), f"{where}.notes", errors)

    spouses = person.get("spouses")
    if spouses is not None:
        if not isinstance(spouses, list):
            errors.append(f"{where}: spouses는 배열이어야 합니다.")
        else:
            for index, spouse in enumerate(spouses):
                _check_spouse(spouse, f"{where}.spouses[{index}]", errors)

    children = person.get("children")
    if children is not None:
        if not isinstance(children, list):
            errors.append(f"{where}: children은 배열이어야 합니다.")
        else:
            for index, child in enumerate(children):
                _check_child(child, f"{where}.children[{index}]", errors, warnings)

    _check_page_ref(person.get("page_ref"), where, errors, warnings)
    _check_bbox(person.get("bbox"), where, errors)
    _check_confidence(person.get("confidence"), where, errors)
    if "needs_human" in person and not isinstance(person.get("needs_human"), bool):
        errors.append(f"{where}.needs_human: true/false여야 합니다.")


def _check_page(page: Any, errors: list[str]) -> None:
    if not isinstance(page, dict):
        errors.append("page 객체가 없습니다.")
        return
    if page.get("section") not in {"frontmatter", "genealogy"}:
        errors.append("page.section은 frontmatter/genealogy여야 합니다.")
    if not _is_int(page.get("printed_page_no")) or page.get("printed_page_no", 0) < 1:
        errors.append("page.printed_page_no가 양의 정수가 아닙니다.")
    if page.get("page_type") not in PAGE_TYPES:
        errors.append("page.page_type이 올바르지 않습니다.")

    quality = page.get("quality")
    if quality is not None:
        if not isinstance(quality, dict):
            errors.append("page.quality는 객체여야 합니다.")
        else:
            rotation = quality.get("rotation_degrees")
            if rotation is not None and (
                not isinstance(rotation, (int, float)) or isinstance(rotation, bool)
            ):
                errors.append("page.quality.rotation_degrees는 숫자 또는 null이어야 합니다.")
            for field in ("blur", "bleed_through"):
                if quality.get(field) not in {None, "low", "medium", "high"}:
                    errors.append(f"page.quality.{field}은 low/medium/high 또는 null이어야 합니다.")
            if "needs_human" in quality and not isinstance(quality.get("needs_human"), bool):
                errors.append("page.quality.needs_human은 true/false여야 합니다.")

    header = page.get("header")
    if header is not None:
        if not isinstance(header, dict):
            errors.append("page.header는 객체여야 합니다.")
        else:
            _check_string(header.get("running_head"), "page.header.running_head", errors)
            _check_string(header.get("father_name"), "page.header.father_name", errors)
            if "notes" in header:
                _check_string_list(header.get("notes"), "page.header.notes", errors)


def _check_auxiliary(data: dict, errors: list[str], warnings: list[str]) -> None:
    array_fields = (
        "captions",
        "index_entries",
        "annotations",
        "page_texts",
        "generation_chars",
        "tables",
        "unreadable_regions",
    )
    for field in array_fields:
        if field not in data:
            continue
        value = data.get(field)
        if not isinstance(value, list):
            errors.append(f"{field}: 배열이어야 합니다.")
            continue
        for index, item in enumerate(value):
            where = f"{field}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where}: 객체가 아닙니다.")
                continue
            if field in {"captions", "annotations", "page_texts"} and not item.get("raw"):
                errors.append(f"{where}: raw가 필요합니다.")
            elif field == "index_entries":
                if not item.get("name_hanja"):
                    errors.append(f"{where}: name_hanja가 필요합니다.")
                _check_page_ref(item.get("page_ref"), where, errors, warnings)
            elif field == "generation_chars":
                if not isinstance(item.get("chars"), list):
                    errors.append(f"{where}: chars 배열이 필요합니다.")
                if item.get("position") not in {None, "앞", "가운데", "뒤"}:
                    errors.append(f"{where}: position은 앞/가운데/뒤 또는 null이어야 합니다.")
            elif field == "tables" and not isinstance(item.get("rows"), list):
                errors.append(f"{where}: rows 배열이 필요합니다.")
            elif field == "unreadable_regions":
                if item.get("reason") not in {
                    "blur",
                    "bleed_through",
                    "cut_off",
                    "unknown_char",
                    "other",
                }:
                    errors.append(f"{where}: reason이 올바르지 않습니다.")
            if field == "annotations" and item.get("kind") not in {
                None,
                "note",
                "address",
                "burial",
                "other",
            }:
                errors.append(f"{where}: kind가 올바르지 않습니다.")
            if field == "page_texts" and item.get("kind") not in {
                None,
                "body",
                "heading",
                "colophon",
                "other",
            }:
                errors.append(f"{where}: kind가 올바르지 않습니다.")
            _check_bbox(item.get("bbox"), where, errors)


def _check_subject(
    subject: Any,
    where: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(subject, dict):
        errors.append(f"{where}: 객체가 아닙니다.")
        return
    row, column = subject.get("row"), subject.get("column")
    if not _is_int(row) or row < 1:
        errors.append(f"{where}: row가 양의 정수가 아닙니다.")
    if not _is_int(column) or column < 1:
        errors.append(f"{where}: column이 양의 정수가 아닙니다.")
    if subject.get("relation_to_subject") not in RELATIONS:
        errors.append(f"{where}: relation_to_subject가 올바르지 않습니다.")
    elif subject.get("relation_to_subject") != "self":
        warnings.append(f"{where}: 기준 인물의 relation_to_subject는 self여야 합니다: {subject.get('relation_to_subject')}")
    offset = subject.get("generation_offset")
    if offset is not None and (not _is_int(offset) or offset < 0):
        errors.append(f"{where}: generation_offset이 0 이상의 정수가 아닙니다.")
    elif offset not in (None, 0):
        warnings.append(f"{where}: 기준 인물의 generation_offset은 0이어야 합니다: {offset}")
    _check_person(subject, where, errors, warnings)


def _check_entry(
    entry: Any,
    where: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(entry, dict):
        errors.append(f"{where}: 객체가 아닙니다.")
        return
    row, column = entry.get("row"), entry.get("column")
    if not _is_int(row) or row < 1:
        errors.append(f"{where}: row가 양의 정수가 아닙니다.")
    if not _is_int(column) or column < 1:
        errors.append(f"{where}: column이 양의 정수가 아닙니다.")
    offset = entry.get("generation_offset")
    if offset is not None and (not _is_int(offset) or offset < 0):
        errors.append(f"{where}: generation_offset이 0 이상의 정수가 아닙니다.")
    if entry.get("relation_to_subject") not in ENTRY_RELATIONS:
        errors.append(
            f"{where}: relation_to_subject가 올바르지 않습니다. 기준 인물은 subjects[]에만 넣으세요."
        )
    _check_person(entry.get("person"), f"{where}.person", errors, warnings)
    _check_bbox(entry.get("bbox"), where, errors)
    _check_confidence(entry.get("confidence"), where, errors)
    if "needs_human" in entry and not isinstance(entry.get("needs_human"), bool):
        errors.append(f"{where}.needs_human: true/false여야 합니다.")


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
    _check_page(page, errors)
    if isinstance(page, dict):
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
        _check_entry(entry, where, errors, warnings)
        if isinstance(entry, dict):
            row, column = entry.get("row"), entry.get("column")
            if _is_int(row) and _is_int(column):
                key = (row, column)
                if key in seen:
                    errors.append(f"{where}: (row={row}, column={column})가 중복됩니다.")
                seen.add(key)

    subjects = data.get("subjects")
    if subjects is not None and not isinstance(subjects, list):
        errors.append("subjects는 배열이어야 합니다.")
        subjects = []
    subjects = subjects or []
    for index, subject in enumerate(subjects):
        where = f"subjects[{index}]"
        _check_subject(subject, where, errors, warnings)
        if isinstance(subject, dict):
            row, column = subject.get("row"), subject.get("column")
            if _is_int(row) and _is_int(column):
                key = (row, column)
                if key in seen:
                    errors.append(f"{where}: entries와 (row={row}, column={column})가 중복됩니다.")
                seen.add(key)

    subject_names = {
        (subject.get("as_printed") or subject.get("raw_name"))
        for subject in subjects
        if isinstance(subject, dict)
    }
    subject_names.discard(None)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("person"), dict):
            continue
        person_name = entry["person"].get("as_printed") or entry["person"].get("raw_name")
        if person_name and person_name in subject_names:
            warnings.append(f"entries[{index}]: 기준 인물이 entries에 중복되었습니다: {person_name}")

    _check_auxiliary(data, errors, warnings)

    if page and isinstance(page, dict):
        if page.get("page_type") != "genealogy" and entries:
            warnings.append("genealogy가 아닌 페이지에 entries가 있습니다. 보조 필드 사용을 검토하세요.")
        if page.get("page_type") == "genealogy":
            if not subjects:
                warnings.append("genealogy 페이지인데 subjects가 비었습니다. 기준 인물을 subjects[]에 넣으세요.")
            if not entries:
                warnings.append("genealogy 페이지인데 entries가 비었습니다. unreadable_regions를 확인하세요.")

    human_count = 0
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and (
            entry.get("needs_human") or (isinstance(entry.get("person"), dict) and entry["person"].get("needs_human"))
        ):
            human_count += 1
    for subject in subjects:
        if isinstance(subject, dict) and subject.get("needs_human"):
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
