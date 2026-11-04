#!/usr/bin/env python3
"""Import approved page JSON into PostgreSQL.

The durable input is `data/exports/approved.jsonl` (one approved page per line).
This script turns it into a self-contained SQL file that can be applied with
`psql`, or applies it directly through `psql` when `--dsn` is given. No Python
database driver is required.

Usage:
    # 1) SQL 파일 생성 (기본: data/exports/import.sql)
    python3 scripts/import_db.py

    # 2) 스키마까지 함께 적용
    python3 scripts/import_db.py --include-schema --sql /tmp/doos.sql
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/doos.sql

    # 3) psql로 바로 적재 (psql이 PATH에 있어야 함)
    python3 scripts/import_db.py --dsn "$DATABASE_URL" --include-schema

    # 4) 적재 계획만 확인
    python3 scripts/import_db.py --dry-run

Rules:
    * `generation_no` is copied from the printed `世` value. It is never
      computed from the father chain.
    * `father_id` is resolved from `person.father` after all pages are loaded.
    * Re-running the import replaces the derived rows of every approved page.
    * Only the approved JSONL is imported. Raw `data/parsed/` stays local.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from common import ROOT, load_manifest
from validate_page import validate

DEFAULT_INPUT = ROOT / "data" / "exports" / "approved.jsonl"
DEFAULT_SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_SQL = ROOT / "data" / "exports" / "import.sql"

SECTION_ROWS = [
    ("frontmatter", "전편(서문·사진·부록)", 1, 93, "independent", None),
    ("genealogy", "본편(세보)", 1, 938, "independent", None),
    ("covers", "표지", None, None, "none", None),
]

ALIAS_KIND = {"字": "ja", "號": "ho", "其他": "other"}
POSITION = {"앞": "first", "가운데": "middle", "뒤": "last", None: None}
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
CHUNK = 300


# ---------------------------------------------------------------------------
# input
# ---------------------------------------------------------------------------


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise ValueError(
            f"{path}가 없습니다. 먼저 `python3 scripts/export_approved.py`로 승인분을 내보내세요."
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}가 비어 있습니다.")

    records: list[dict] = []
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None

    if isinstance(whole, dict):
        if isinstance(whole.get("parsed"), dict):
            records = [whole]
        elif isinstance(whole.get("page"), dict):
            page = whole["page"]
            records = [
                {
                    "section": page.get("section"),
                    "printed_page_no": page.get("printed_page_no"),
                    "review": {"status": "approved"},
                    "parsed": whole,
                }
            ]
        else:
            raise ValueError(f"{path}: 페이지 JSON도 approved 레코드도 아닙니다.")
    else:
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: JSON 오류: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_no}: 객체가 아닙니다.")
            records.append(item)

    normalized: list[dict] = []
    for record in records:
        parsed = record.get("parsed") if isinstance(record.get("parsed"), dict) else record
        page = _dict(parsed.get("page"))
        section = _text(record.get("section")) or _text(page.get("section"))
        page_no = _int(record.get("printed_page_no")) or _int(page.get("printed_page_no"))
        if not section or not page_no:
            raise ValueError("레코드에 section/printed_page_no가 없습니다.")
        normalized.append(
            {
                "section": section,
                "printed_page_no": page_no,
                "review": _dict(record.get("review")),
                "parsed": parsed,
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def _manifest_pages() -> dict[tuple[str, int], dict]:
    pages: dict[tuple[str, int], dict] = {}
    for row in load_manifest():
        pages[(row["section"], row["printed_page_no"])] = row
    return pages


def _quality_flags(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    for separator in (";", ","):
        value = value.replace(separator, " ")
    return [part for part in value.split() if part]


def _page_row(manifest: dict | None, record: dict | None) -> dict:
    if record is None:
        assert manifest is not None
        page_type = _text(manifest.get("page_type")) or "unknown"
        image_path = _text(manifest.get("normalized_path")) or _text(manifest.get("source_path"))
        return {
            "section": manifest["section"],
            "printed_page_no": manifest["printed_page_no"],
            "scan_seq": _int(manifest.get("scan_seq")),
            "page_type": page_type,
            "image_path": image_path,
            "image_sha256": _text(manifest.get("sha256")),
            "width": _int(manifest.get("width")),
            "height": _int(manifest.get("height")),
            "dpi": _int(manifest.get("dpi")),
            "quality_flags": _quality_flags(manifest.get("quality_flags")),
            "manifest_notes": _text(manifest.get("notes")),
            "review_status": "pending",
            "raw": None,
        }

    parsed = record["parsed"]
    page = _dict(parsed.get("page"))
    page_type = _text(page.get("page_type")) or "unknown"
    if page_type not in PAGE_TYPES:
        raise ValueError(
            f"{record['section']} {record['printed_page_no']}: page_type={page_type}이 올바르지 않습니다."
        )
    image_path = None
    image_sha256 = None
    scan_seq = width = height = dpi = None
    quality_flags: list[str] = []
    notes = None
    if manifest is not None:
        image_path = _text(manifest.get("normalized_path")) or _text(manifest.get("source_path"))
        image_sha256 = _text(manifest.get("sha256"))
        scan_seq = _int(manifest.get("scan_seq"))
        width = _int(manifest.get("width"))
        height = _int(manifest.get("height"))
        dpi = _int(manifest.get("dpi"))
        quality_flags = _quality_flags(manifest.get("quality_flags"))
        notes = _text(manifest.get("notes"))
    if page_type != "missing" and (not image_path or not image_sha256):
        raise ValueError(
            f"{record['section']} {record['printed_page_no']}: manifest에 이미지 경로/해시가 없습니다."
        )
    review_status = _text(record["review"].get("status")) or "approved"
    return {
        "section": record["section"],
        "printed_page_no": record["printed_page_no"],
        "scan_seq": scan_seq,
        "page_type": page_type,
        "image_path": image_path,
        "image_sha256": image_sha256,
        "width": width,
        "height": height,
        "dpi": dpi,
        "quality_flags": quality_flags,
        "manifest_notes": notes,
        "review_status": review_status,
        "raw": page,
    }


def _add_ref(plan: dict, ref: Any, row: int, column: int, note: str) -> None:
    if not isinstance(ref, dict):
        return
    raw = _text(ref.get("raw"))
    direction = _text(ref.get("direction"))
    target_section = _text(ref.get("target_section"))
    target_page_no = _int(ref.get("target_page_no"))
    if not raw or direction not in {"up", "down"} or not target_section or not target_page_no:
        return
    plan["page_refs"].append(
        {
            "row": row,
            "column": column,
            "raw_ref": raw,
            "direction": direction,
            "target_section": target_section,
            "target_page_no": target_page_no,
            "confidence": _number(ref.get("confidence")),
            "note": note,
            "bbox": ref.get("bbox"),
        }
    )


def _add_person(plan: dict, person: Any, placement: dict, is_subject: bool) -> None:
    if not isinstance(person, dict):
        return
    row = _int(placement.get("row"))
    column = _int(placement.get("column"))
    if row is None or column is None:
        return
    key = (row, column)
    if key in plan["positions"]:
        plan["warnings"].append(
            f"{plan['section']} {plan['printed_page_no']}: (row={row}, column={column}) 중복을 건너뜁니다."
        )
        return
    plan["positions"].add(key)

    father = person.get("father")
    father = father if isinstance(father, dict) else None
    declared_source = _text(father.get("source")) if father else None
    if declared_source in {"printed", "inferred", "reviewed", "unknown"}:
        father_source = declared_source
    elif father and isinstance(father.get("page_ref"), dict):
        father_source = "printed"
    elif father and father.get("row") is not None:
        father_source = "inferred"
    else:
        father_source = "unknown"
    relation = _text(placement.get("relation_to_subject")) or "unknown"
    needs_human = bool(placement.get("needs_human") or person.get("needs_human"))
    if father is None and relation in {"son", "daughter"}:
        needs_human = True
    plan["people"].append(
        {
            "row": row,
            "column": column,
            "is_subject": is_subject,
            "as_printed": _text(person.get("as_printed")) or "",
            "name_hanja": _text(person.get("name_hanja")),
            "name_hangul": _text(person.get("name_hangul")),
            "prefix": _text(person.get("prefix")),
            "generation_no": _int(person.get("generation_no")),
            "generation_char": _text(person.get("generation_char")),
            "generation_offset": _int(placement.get("generation_offset")),
            "page_relation": relation,
            "father_raw": father,
            "father_relation": (_text(father.get("relation")) if father else None)
            or ("father" if father else None),
            "father_source": father_source,
            "father_confidence": _number(father.get("confidence")) if father else None,
            "needs_human": needs_human,
            "confidence": _number(placement.get("confidence")) or _number(person.get("confidence")),
            "bbox": placement.get("bbox") or person.get("bbox"),
            "notes": [n for n in _list(person.get("notes")) if isinstance(n, str)],
            "offices": [o for o in _list(person.get("offices")) if isinstance(o, str)],
            "raw": person,
        }
    )

    # aliases and names
    name_hanja = _text(person.get("name_hanja"))
    name_hangul = _text(person.get("name_hangul"))
    if name_hanja:
        plan["names"].append({"row": row, "column": column, "kind": "hanja", "value": name_hanja, "ordinal": 0})
    if name_hangul:
        plan["names"].append({"row": row, "column": column, "kind": "hangul", "value": name_hangul, "ordinal": 0})
    for index, alias in enumerate(_list(person.get("aliases"))):
        if not isinstance(alias, dict):
            continue
        value = _text(alias.get("value"))
        kind = ALIAS_KIND.get(_text(alias.get("type")) or "")
        if value and kind:
            plan["names"].append(
                {"row": row, "column": column, "kind": kind, "value": value, "ordinal": index + 1}
            )

    # birth / death
    for event_type in ("birth", "death"):
        block = person.get(event_type)
        if not isinstance(block, dict):
            continue
        plan["events"].append(
            {
                "row": row,
                "column": column,
                "event_type": event_type,
                "date_raw": _text(block.get("raw")),
                "king_era": _text(block.get("king_era")),
                "ganji": _text(block.get("ganji")),
                "date_text": _text(block.get("date_text")),
                "certainty": _text(block.get("certainty")),
            }
        )

    # person burial
    burial = person.get("burial")
    if isinstance(burial, dict):
        plan["person_burials"].append(
            {
                "row": row,
                "column": column,
                "burial_raw": _text(burial.get("raw")),
                "location": _text(burial.get("location")),
                "orientation": _text(burial.get("orientation")),
                "note": _text(burial.get("note")),
                "certainty": _text(burial.get("certainty")),
                "raw": burial,
            }
        )

    # marriages
    for ordinal, spouse in enumerate(_list(person.get("spouses"))):
        if not isinstance(spouse, dict):
            continue
        plan["marriages"].append(
            {
                "row": row,
                "column": column,
                "ordinal": ordinal,
                "spouse_as_printed": _text(spouse.get("as_printed")) or "",
                "spouse_name_hanja": _text(spouse.get("name_hanja")),
                "spouse_bonkwan": _text(spouse.get("bonkwan")),
                "spouse_father": _text(spouse.get("father")),
                "relation": _text(spouse.get("relation")) or "unknown",
                "birth": spouse.get("birth") if isinstance(spouse.get("birth"), dict) else None,
                "death": spouse.get("death") if isinstance(spouse.get("death"), dict) else None,
                "certainty": _text(spouse.get("certainty")),
                "bbox": spouse.get("bbox"),
                "raw": spouse,
            }
        )
        spouse_burial = spouse.get("burial")
        if isinstance(spouse_burial, dict):
            plan["marriage_burials"].append(
                {
                    "row": row,
                    "column": column,
                    "ordinal": ordinal,
                    "burial_raw": _text(spouse_burial.get("raw")),
                    "location": _text(spouse_burial.get("location")),
                    "orientation": _text(spouse_burial.get("orientation")),
                    "note": _text(spouse_burial.get("note")),
                    "certainty": _text(spouse_burial.get("certainty")),
                    "raw": spouse_burial,
                }
            )

    # children printed inline
    for child in _list(person.get("children")):
        if not isinstance(child, dict):
            continue
        child_name = _text(child.get("as_printed")) or _text(child.get("name_hanja"))
        if not child_name:
            continue
        plan["relations"].append(
            {
                "row": row,
                "column": column,
                "to_as_printed": child_name,
                "relation_type": _text(child.get("relation")) or "unknown",
                "raw": child,
            }
        )
        if isinstance(child.get("page_ref"), dict):
            _add_ref(plan, child["page_ref"], row, column, f"child:{child_name}")

    # page references attached to this person
    if isinstance(person.get("page_ref"), dict):
        _add_ref(plan, person["page_ref"], row, column, "person")
    if isinstance(father, dict) and isinstance(father.get("page_ref"), dict):
        _add_ref(plan, father["page_ref"], row, column, "father")


def build_page_plan(record: dict, manifest: dict | None) -> dict:
    parsed = record["parsed"]
    errors, warnings = validate(parsed, record["section"], record["printed_page_no"])
    if errors:
        joined = "\n  - ".join(errors)
        raise ValueError(f"{record['section']} {record['printed_page_no']}: 검증 오류\n  - {joined}")

    plan: dict = {
        "section": record["section"],
        "printed_page_no": record["printed_page_no"],
        "page": _page_row(manifest, record),
        "people": [],
        "positions": set(),
        "names": [],
        "events": [],
        "marriages": [],
        "person_burials": [],
        "marriage_burials": [],
        "relations": [],
        "page_refs": [],
        "texts": [],
        "tables": [],
        "unreadable": [],
        "index_entries": [],
        "toc_entries": [],
        "generation_chars": [],
        "warnings": [f"{record['section']} {record['printed_page_no']}: {w}" for w in warnings],
    }

    for subject in _list(parsed.get("subjects")):
        if isinstance(subject, dict):
            _add_person(plan, subject, subject, True)
    for entry in _list(parsed.get("entries")):
        if isinstance(entry, dict):
            _add_person(plan, entry.get("person"), entry, False)

    # auxiliary page content
    for item in _list(parsed.get("page_texts")):
        if isinstance(item, dict) and _text(item.get("raw")):
            plan["texts"].append(
                {
                    "kind": _text(item.get("kind")) or "body",
                    "subkind": None,
                    "raw_text": _text(item.get("raw")),
                    "bbox": item.get("bbox"),
                }
            )
    for item in _list(parsed.get("captions")):
        if isinstance(item, dict) and _text(item.get("raw")):
            plan["texts"].append(
                {
                    "kind": "caption",
                    "subkind": None,
                    "raw_text": _text(item.get("raw")),
                    "bbox": item.get("bbox"),
                }
            )
    for item in _list(parsed.get("annotations")):
        if isinstance(item, dict) and _text(item.get("raw")):
            plan["texts"].append(
                {
                    "kind": "annotation",
                    "subkind": _text(item.get("kind")),
                    "raw_text": _text(item.get("raw")),
                    "bbox": item.get("bbox"),
                }
            )

    for item in _list(parsed.get("tables")):
        if isinstance(item, dict):
            plan["tables"].append(
                {
                    "title": _text(item.get("title")),
                    "headers": _list(item.get("headers")),
                    "rows": _list(item.get("rows")),
                    "bbox": item.get("bbox"),
                }
            )

    for item in _list(parsed.get("unreadable_regions")):
        if isinstance(item, dict):
            plan["unreadable"].append({"bbox": item.get("bbox"), "reason": _text(item.get("reason"))})

    for item in _list(parsed.get("index_entries")):
        if not isinstance(item, dict):
            continue
        ref = _dict(item.get("page_ref"))
        plan["index_entries"].append(
            {
                "name_hanja": _text(item.get("name_hanja")) or "",
                "name_hangul": _text(item.get("name_hangul")),
                "target_section": _text(ref.get("target_section")),
                "target_page_no": _int(ref.get("target_page_no")),
                "raw_ref": _text(ref.get("raw")),
                "bbox": item.get("bbox"),
            }
        )

    for item in _list(parsed.get("toc_entries")):
        if not isinstance(item, dict) or not _text(item.get("title")):
            continue
        ref = _dict(item.get("page_ref"))
        plan["toc_entries"].append(
            {
                "item_no": _int(item.get("item_no")),
                "title": _text(item.get("title")),
                "target_section": _text(item.get("target_section")) or _text(ref.get("target_section")),
                "target_page_no": _int(item.get("target_page_no")) or _int(ref.get("target_page_no")),
                "note": _text(item.get("note")),
            }
        )

    for item in _list(parsed.get("generation_chars")):
        if not isinstance(item, dict):
            continue
        generation_no = _int(item.get("generation_no"))
        if generation_no is None:
            plan["warnings"].append(
                f"{record['section']} {record['printed_page_no']}: generation_chars에 generation_no가 없어 건너뜁니다."
            )
            continue
        position = POSITION.get(item.get("position"), None)
        for char in _list(item.get("chars")):
            if isinstance(char, str) and char:
                plan["generation_chars"].append(
                    {
                        "generation_no": generation_no,
                        "char_hanja": char,
                        "position": position,
                    }
                )
    return plan


def build_plan(records: list[dict]) -> dict:
    manifest = _manifest_pages()
    approved_keys = {(r["section"], r["printed_page_no"]) for r in records}
    raw_keys = [(r["section"], r["printed_page_no"]) for r in records]
    duplicates = [key for key, count in Counter(raw_keys).items() if count > 1]
    if duplicates:
        joined = ", ".join(f"{section} {page}" for section, page in duplicates)
        raise ValueError(f"같은 페이지가 여러 번 들어 있습니다: {joined}")

    pages: list[dict] = []
    for key in sorted(manifest, key=lambda k: (0 if k[0] == "frontmatter" else 1, k[1])):
        row = manifest[key]
        pages.append(_page_row(row, None))
    for record in records:
        key = (record["section"], record["printed_page_no"])
        if key not in manifest:
            raise ValueError(
                f"{record['section']} {record['printed_page_no']}: pages.csv에 없는 페이지입니다."
            )
    page_by_key = {(p["section"], p["printed_page_no"]): p for p in pages}
    for record in records:
        key = (record["section"], record["printed_page_no"])
        page_by_key[key] = _page_row(manifest[key], record)

    plans = [build_page_plan(record, manifest.get((record["section"], record["printed_page_no"]))) for record in records]
    warnings: list[str] = []
    for plan in plans:
        warnings.extend(plan["warnings"])

    counts = Counter()
    for plan in plans:
        counts["people"] += len(plan["people"])
        counts["marriages"] += len(plan["marriages"])
        counts["page_refs"] += len(plan["page_refs"])
        counts["relations"] += len(plan["relations"])
        counts["names"] += len(plan["names"])
        counts["events"] += len(plan["events"])
        counts["burials"] += len(plan["person_burials"]) + len(plan["marriage_burials"])
        counts["texts"] += len(plan["texts"])
        counts["index_entries"] += len(plan["index_entries"])
        counts["generation_chars"] += len(plan["generation_chars"])

    return {
        "pages": list(page_by_key.values()),
        "plans": plans,
        "approved": approved_keys,
        "warnings": warnings,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# SQL rendering
# ---------------------------------------------------------------------------


def q(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL 문자는 PostgreSQL text에 넣을 수 없습니다.")
    return "'" + value.replace("'", "''") + "'"


def v_text(value: Any) -> str:
    if not isinstance(value, str):
        return "NULL::text"
    return f"{q(value)}::text"


def v_int(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "NULL::integer"
    return f"{value}::integer"


def v_bool(value: Any) -> str:
    if value is None:
        return "NULL::boolean"
    return "TRUE" if value else "FALSE"


def v_num(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "NULL::numeric"
    return f"{number:.3f}::numeric"


def v_json(value: Any) -> str:
    if value is None:
        return "NULL::jsonb"
    return q(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) + "::jsonb"


def v_text_array(values: Any) -> str:
    items = [item for item in _list(values) if isinstance(item, str)]
    if not items:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(q(item) for item in items) + "]::text[]"


def chunks(items: list, size: int = CHUNK) -> Iterable[list]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def emit_sections() -> str:
    values = []
    for code, title, start, end, numbering, note in SECTION_ROWS:
        values.append(
            f"({q(code)}, {q(title)}, {v_int(start)}, {v_int(end)}, {q(numbering)}, {v_text(note)})"
        )
    return (
        "INSERT INTO sections (code, title, page_start, page_end, numbering, note)\n"
        "VALUES\n  " + ",\n  ".join(values) + "\n"
        "ON CONFLICT (code) DO UPDATE SET\n"
        "  title = EXCLUDED.title,\n"
        "  page_start = EXCLUDED.page_start,\n"
        "  page_end = EXCLUDED.page_end,\n"
        "  numbering = EXCLUDED.numbering,\n"
        "  note = EXCLUDED.note;"
    )


def emit_pages(pages: list[dict]) -> list[str]:
    statements: list[str] = []
    for batch in chunks(pages):
        values = []
        for page in batch:
            values.append(
                "("
                + ", ".join(
                    [
                        q(page["section"]),
                        v_int(page["printed_page_no"]),
                        v_int(page["scan_seq"]),
                        q(page["page_type"]),
                        v_text(page["image_path"]),
                        v_text(page["image_sha256"]),
                        v_int(page["width"]),
                        v_int(page["height"]),
                        v_int(page["dpi"]),
                        v_text_array(page["quality_flags"]),
                        v_text(page["manifest_notes"]),
                        q(page["review_status"]),
                        v_json(page["raw"]),
                    ]
                )
                + ")"
            )
        statements.append(
            "INSERT INTO pages (section_id, printed_page_no, scan_seq, page_type, image_path,\n"
            "  image_sha256, width, height, dpi, quality_flags, manifest_notes, review_status, raw)\n"
            "SELECT s.id, v.printed_page_no, v.scan_seq, v.page_type, v.image_path,\n"
            "  v.image_sha256, v.width, v.height, v.dpi, v.quality_flags, v.manifest_notes,\n"
            "  v.review_status, v.raw\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(section_code, printed_page_no, scan_seq, page_type, image_path,\n"
            "  image_sha256, width, height, dpi, quality_flags, manifest_notes, review_status, raw)\n"
            "JOIN sections s ON s.code = v.section_code\n"
            "ON CONFLICT (section_id, printed_page_no) DO UPDATE SET\n"
            "  scan_seq = EXCLUDED.scan_seq,\n"
            "  page_type = EXCLUDED.page_type,\n"
            "  image_path = EXCLUDED.image_path,\n"
            "  image_sha256 = EXCLUDED.image_sha256,\n"
            "  width = EXCLUDED.width,\n"
            "  height = EXCLUDED.height,\n"
            "  dpi = EXCLUDED.dpi,\n"
            "  quality_flags = EXCLUDED.quality_flags,\n"
            "  manifest_notes = EXCLUDED.manifest_notes,\n"
            "  review_status = EXCLUDED.review_status,\n"
            "  raw = EXCLUDED.raw,\n"
            "  updated_at = now();"
        )
    return statements


def _page_cte(section: str, page_no: int) -> str:
    return (
        "WITH pg AS (\n"
        "  SELECT p.id FROM pages p JOIN sections s ON s.id = p.section_id\n"
        f"  WHERE s.code = {q(section)} AND p.printed_page_no = {page_no}\n"
        ")"
    )


def emit_page_deletes(plan: dict) -> list[str]:
    cte = _page_cte(plan["section"], plan["printed_page_no"])
    return [
        f"{cte}\nDELETE FROM relations WHERE source_page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM page_refs WHERE source_page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM index_entries WHERE page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM page_texts WHERE page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM page_tables WHERE page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM unreadable_regions WHERE page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM generation_chars WHERE source_page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM toc_entries WHERE source_page_id IN (SELECT id FROM pg);",
        f"{cte}\nDELETE FROM people WHERE source_page_id IN (SELECT id FROM pg);",
    ]


def emit_unapproved_cleanup() -> list[str]:
    """DB를 approved.jsonl의 스냅샷으로 만든다.

    승인 목록에서 빠진 페이지의 인물·관계·참조 행을 지운다. 페이지 행 자체는
    `pending`으로 남겨 인벤토리와 미수록 면을 유지한다.
    """
    stale = (
        "WITH stale AS (\n"
        "  SELECT id FROM pages WHERE review_status NOT IN ('approved', 'published')\n"
        ")"
    )
    return [
        f"{stale}\nDELETE FROM relations WHERE source_page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM page_refs WHERE source_page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM index_entries WHERE page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM page_texts WHERE page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM page_tables WHERE page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM unreadable_regions WHERE page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM generation_chars WHERE source_page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM toc_entries WHERE source_page_id IN (SELECT id FROM stale);",
        f"{stale}\nDELETE FROM people WHERE source_page_id IN (SELECT id FROM stale);",
    ]


def emit_people(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["people"]):
        values = []
        for person in batch:
            values.append(
                "("
                + ", ".join(
                    [
                        v_int(person["row"]),
                        v_int(person["column"]),
                        v_bool(person["is_subject"]),
                        v_text(person["as_printed"]),
                        v_text(person["name_hanja"]),
                        v_text(person["name_hangul"]),
                        v_text(person["prefix"]),
                        v_int(person["generation_no"]),
                        v_text(person["generation_char"]),
                        v_int(person["generation_offset"]),
                        q(person["page_relation"]),
                        v_json(person["father_raw"]),
                        v_text(person["father_relation"]),
                        q(person["father_source"]),
                        v_num(person["father_confidence"]),
                        v_bool(person["needs_human"]),
                        v_num(person["confidence"]),
                        v_json(person["bbox"]),
                        v_text_array(person["notes"]),
                        v_text_array(person["offices"]),
                        v_json(person["raw"]),
                    ]
                )
                + ")"
            )
        statements.append(
            "INSERT INTO people (source_page_id, row_no, column_no, is_subject, as_printed,\n"
            "  name_hanja, name_hangul, prefix, generation_no, generation_char, generation_offset,\n"
            "  page_relation, father_raw, father_relation, father_source, father_confidence,\n"
            "  needs_human, confidence, bbox, notes, offices, raw)\n"
            "SELECT pg.id, v.row_no, v.column_no, v.is_subject, v.as_printed,\n"
            "  v.name_hanja, v.name_hangul, v.prefix, v.generation_no, v.generation_char,\n"
            "  v.generation_offset, v.page_relation, v.father_raw, v.father_relation,\n"
            "  v.father_source, v.father_confidence, v.needs_human, v.confidence, v.bbox,\n"
            "  v.notes, v.offices, v.raw\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, is_subject, as_printed, name_hanja, name_hangul, prefix,\n"
            "  generation_no, generation_char, generation_offset, page_relation, father_raw,\n"
            "  father_relation, father_source, father_confidence, needs_human, confidence,\n"
            "  bbox, notes, offices, raw)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nON CONFLICT (source_page_id, row_no, column_no) DO UPDATE SET\n"
            "  is_subject = EXCLUDED.is_subject,\n"
            "  as_printed = EXCLUDED.as_printed,\n"
            "  name_hanja = EXCLUDED.name_hanja,\n"
            "  name_hangul = EXCLUDED.name_hangul,\n"
            "  prefix = EXCLUDED.prefix,\n"
            "  generation_no = EXCLUDED.generation_no,\n"
            "  generation_char = EXCLUDED.generation_char,\n"
            "  generation_offset = EXCLUDED.generation_offset,\n"
            "  page_relation = EXCLUDED.page_relation,\n"
            "  father_raw = EXCLUDED.father_raw,\n"
            "  father_relation = EXCLUDED.father_relation,\n"
            "  father_source = EXCLUDED.father_source,\n"
            "  father_confidence = EXCLUDED.father_confidence,\n"
            "  needs_human = EXCLUDED.needs_human,\n"
            "  confidence = EXCLUDED.confidence,\n"
            "  bbox = EXCLUDED.bbox,\n"
            "  notes = EXCLUDED.notes,\n"
            "  offices = EXCLUDED.offices,\n"
            "  raw = EXCLUDED.raw,\n"
            "  updated_at = now();"
        )
    return statements


def _page_join() -> str:
    return "JOIN sections s ON s.code = {section}\nJOIN pages pg ON pg.section_id = s.id AND pg.printed_page_no = {page_no}"


def emit_names(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["names"]):
        values = [
            "("
            + ", ".join(
                [v_int(r["row"]), v_int(r["column"]), q(r["kind"]), q(r["value"]), v_int(r["ordinal"])]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO person_names (person_id, kind, value, ordinal)\n"
            "SELECT p.id, v.kind, v.value, v.ordinal\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, kind, value, ordinal)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "ON CONFLICT (person_id, kind, value) DO NOTHING;"
        )
    return statements


def emit_events(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["events"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["row"]),
                    v_int(r["column"]),
                    q(r["event_type"]),
                    v_text(r["date_raw"]),
                    v_text(r["king_era"]),
                    v_text(r["ganji"]),
                    v_text(r["date_text"]),
                    v_text(r["certainty"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO person_events (person_id, event_type, date_raw, king_era, ganji, date_text, certainty)\n"
            "SELECT p.id, v.event_type, v.date_raw, v.king_era, v.ganji, v.date_text, v.certainty\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, event_type, date_raw, king_era, ganji, date_text, certainty)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "ON CONFLICT (person_id, event_type) DO UPDATE SET\n"
            "  date_raw = EXCLUDED.date_raw,\n"
            "  king_era = EXCLUDED.king_era,\n"
            "  ganji = EXCLUDED.ganji,\n"
            "  date_text = EXCLUDED.date_text,\n"
            "  certainty = EXCLUDED.certainty;"
        )
    return statements


def emit_marriages(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["marriages"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["row"]),
                    v_int(r["column"]),
                    v_int(r["ordinal"]),
                    v_text(r["spouse_as_printed"]),
                    v_text(r["spouse_name_hanja"]),
                    v_text(r["spouse_bonkwan"]),
                    v_text(r["spouse_father"]),
                    q(r["relation"]),
                    v_json(r["birth"]),
                    v_json(r["death"]),
                    v_text(r["certainty"]),
                    v_json(r["bbox"]),
                    v_json(r["raw"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO marriages (person_id, ordinal, spouse_as_printed, spouse_name_hanja,\n"
            "  spouse_bonkwan, spouse_father, relation, birth, death, certainty, source_page_id, bbox, raw)\n"
            "SELECT p.id, v.ordinal, v.spouse_as_printed, v.spouse_name_hanja, v.spouse_bonkwan,\n"
            "  v.spouse_father, v.relation, v.birth, v.death, v.certainty, pg.id, v.bbox, v.raw\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, ordinal, spouse_as_printed, spouse_name_hanja, spouse_bonkwan,\n"
            "  spouse_father, relation, birth, death, certainty, bbox, raw)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "ON CONFLICT (person_id, ordinal) DO UPDATE SET\n"
            "  spouse_as_printed = EXCLUDED.spouse_as_printed,\n"
            "  spouse_name_hanja = EXCLUDED.spouse_name_hanja,\n"
            "  spouse_bonkwan = EXCLUDED.spouse_bonkwan,\n"
            "  spouse_father = EXCLUDED.spouse_father,\n"
            "  relation = EXCLUDED.relation,\n"
            "  birth = EXCLUDED.birth,\n"
            "  death = EXCLUDED.death,\n"
            "  certainty = EXCLUDED.certainty,\n"
            "  bbox = EXCLUDED.bbox,\n"
            "  raw = EXCLUDED.raw;"
        )
    return statements


def _emit_burial_values(batch: list[dict], *, marriage: bool) -> str:
    values = []
    for r in batch:
        parts = [v_int(r["row"]), v_int(r["column"])]
        if marriage:
            parts.append(v_int(r["ordinal"]))
        parts.extend(
            [
                v_text(r["burial_raw"]),
                v_text(r["location"]),
                v_text(r["orientation"]),
                v_text(r["note"]),
                v_text(r["certainty"]),
                v_json(r["raw"]),
            ]
        )
        values.append("(" + ", ".join(parts) + ")")
    return ",\n  ".join(values)


def emit_burials(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["person_burials"]):
        statements.append(
            "INSERT INTO burials (person_id, burial_raw, location, orientation, note, certainty, raw)\n"
            "SELECT p.id, v.burial_raw, v.location, v.orientation, v.note, v.certainty, v.raw\n"
            "FROM (VALUES\n  " + _emit_burial_values(batch, marriage=False) + "\n"
            ") AS v(row_no, column_no, burial_raw, location, orientation, note, certainty, raw)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no;"
        )
    for batch in chunks(plan["marriage_burials"]):
        statements.append(
            "INSERT INTO burials (marriage_id, burial_raw, location, orientation, note, certainty, raw)\n"
            "SELECT m.id, v.burial_raw, v.location, v.orientation, v.note, v.certainty, v.raw\n"
            "FROM (VALUES\n  " + _emit_burial_values(batch, marriage=True) + "\n"
            ") AS v(row_no, column_no, ordinal, burial_raw, location, orientation, note, certainty, raw)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "JOIN marriages m ON m.person_id = p.id AND m.ordinal = v.ordinal;"
        )
    return statements


def emit_relations(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["relations"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["row"]),
                    v_int(r["column"]),
                    v_text(r["to_as_printed"]),
                    q(r["relation_type"]),
                    v_json(r["raw"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO relations (source_page_id, from_person_id, to_person_id, to_as_printed, relation_type, raw)\n"
            "SELECT pg.id, p.id, NULL, v.to_as_printed, v.relation_type, v.raw\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, to_as_printed, relation_type, raw)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "ON CONFLICT (from_person_id, relation_type, to_as_printed) DO UPDATE SET raw = EXCLUDED.raw;"
        )
    return statements


def emit_page_refs(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["page_refs"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["row"]),
                    v_int(r["column"]),
                    q(r["raw_ref"]),
                    q(r["direction"]),
                    q(r["target_section"]),
                    v_int(r["target_page_no"]),
                    v_num(r["confidence"]),
                    v_text(r["note"]),
                    v_json(r["bbox"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO page_refs (source_page_id, source_person_id, raw_ref, direction,\n"
            "  target_section_id, target_page_no, confidence, note, bbox)\n"
            "SELECT pg.id, p.id, v.raw_ref, v.direction, ts.id, v.target_page_no, v.confidence, v.note, v.bbox\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(row_no, column_no, raw_ref, direction, target_section, target_page_no, confidence, note, bbox)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN people p ON p.source_page_id = pg.id AND p.row_no = v.row_no AND p.column_no = v.column_no\n"
            "JOIN sections ts ON ts.code = v.target_section;"
        )
    return statements


def emit_texts(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["texts"]):
        values = [
            "("
            + ", ".join(
                [
                    q(r["kind"]),
                    v_text(r["subkind"]),
                    v_text(r["raw_text"]),
                    v_json(r["bbox"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO page_texts (page_id, kind, subkind, raw_text, bbox)\n"
            "SELECT pg.id, v.kind, v.subkind, v.raw_text, v.bbox\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(kind, subkind, raw_text, bbox)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"]) + ";"
        )
    return statements


def emit_tables(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["tables"]):
        values = [
            "("
            + ", ".join(
                [v_text(r["title"]), v_json(r["headers"]), v_json(r["rows"]), v_json(r["bbox"])]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO page_tables (page_id, title, headers, rows, bbox)\n"
            "SELECT pg.id, v.title, v.headers, v.rows, v.bbox\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(title, headers, rows, bbox)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"]) + ";"
        )
    return statements


def emit_unreadable(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["unreadable"]):
        values = [
            "(" + ", ".join([v_json(r["bbox"]), q(r["reason"])]) + ")"
            for r in batch
            if r["reason"]
        ]
        if not values:
            continue
        statements.append(
            "INSERT INTO unreadable_regions (page_id, bbox, reason)\n"
            "SELECT pg.id, v.bbox, v.reason\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(bbox, reason)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"]) + ";"
        )
    return statements


def emit_index_entries(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["index_entries"]):
        values = [
            "("
            + ", ".join(
                [
                    q(r["name_hanja"]),
                    v_text(r["name_hangul"]),
                    v_text(r["target_section"]),
                    v_int(r["target_page_no"]),
                    v_text(r["raw_ref"]),
                    v_json(r["bbox"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO index_entries (page_id, name_hanja, name_hangul, target_section_id,\n"
            "  target_page_no, raw_ref, bbox)\n"
            "SELECT pg.id, v.name_hanja, v.name_hangul, ts.id, v.target_page_no, v.raw_ref, v.bbox\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(name_hanja, name_hangul, target_section, target_page_no, raw_ref, bbox)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nLEFT JOIN sections ts ON ts.code = v.target_section;"
        )
    return statements


def emit_toc(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["toc_entries"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["item_no"]),
                    q(r["title"]),
                    q(r["target_section"]),
                    v_int(r["target_page_no"]),
                    v_text(r["note"]),
                ]
            )
            + ")"
            for r in batch
            if r["target_section"]
        ]
        if not values:
            continue
        statements.append(
            "INSERT INTO toc_entries (source_page_id, section_id, item_no, title,\n"
            "  target_section_id, target_page_no, note)\n"
            "SELECT pg.id, s.id, v.item_no, v.title, ts.id, v.target_page_no, v.note\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(item_no, title, target_section, target_page_no, note)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nJOIN sections ts ON ts.code = v.target_section;"
        )
    return statements


def emit_generation_chars(plan: dict) -> list[str]:
    statements: list[str] = []
    for batch in chunks(plan["generation_chars"]):
        values = [
            "("
            + ", ".join(
                [
                    v_int(r["generation_no"]),
                    q(r["char_hanja"]),
                    v_text(r["position"]),
                ]
            )
            + ")"
            for r in batch
        ]
        statements.append(
            "INSERT INTO generation_chars (generation_no, char_hanja, position, source_page_id)\n"
            "SELECT v.generation_no, v.char_hanja, v.position, pg.id\n"
            "FROM (VALUES\n  " + ",\n  ".join(values) + "\n"
            ") AS v(generation_no, char_hanja, position)\n"
            + _page_join().format(section=q(plan["section"]), page_no=plan["printed_page_no"])
            + "\nON CONFLICT (generation_no, char_hanja, source_page_id) DO NOTHING;"
        )
    return statements


FINAL_SQL = """
-- 아버지 연결: 같은 페이지 (row/column)
UPDATE people c
SET father_id = f.id,
    father_source = CASE
      WHEN c.father_raw->>'source' IN ('printed', 'inferred', 'reviewed', 'unknown')
      THEN c.father_raw->>'source'
      ELSE 'inferred'
    END,
    updated_at = now()
FROM people f
WHERE c.father_raw IS NOT NULL
  AND c.father_raw ? 'row'
  AND c.father_raw ? 'column'
  AND f.source_page_id = c.source_page_id
  AND f.row_no = (c.father_raw->>'row')::integer
  AND f.column_no = (c.father_raw->>'column')::integer
  AND f.id <> c.id;

-- 아버지 연결: 다른 페이지 (page_ref의 상대 면 + as_printed/name_hanja)
WITH candidates AS (
  SELECT c.id AS child_id, min(f.id) AS father_id, count(*) AS matches
  FROM people c
  JOIN pages tp
    ON tp.printed_page_no = (c.father_raw->'page_ref'->>'target_page_no')::integer
  JOIN sections ts
    ON ts.id = tp.section_id
   AND ts.code = c.father_raw->'page_ref'->>'target_section'
  JOIN people f
    ON f.source_page_id = tp.id
   AND (
        f.as_printed = c.father_raw->>'as_printed'
        OR (c.father_raw->>'name_hanja' IS NOT NULL AND f.name_hanja = c.father_raw->>'name_hanja')
   )
  WHERE c.father_raw ? 'page_ref'
    AND c.father_id IS NULL
  GROUP BY c.id
)
UPDATE people c
SET father_id = candidates.father_id,
    father_source = CASE
      WHEN c.father_raw->>'source' IN ('printed', 'inferred', 'reviewed', 'unknown')
      THEN c.father_raw->>'source'
      ELSE 'printed'
    END,
    updated_at = now()
FROM candidates
WHERE c.id = candidates.child_id
  AND candidates.matches = 1;

-- 끝까지 연결하지 못한 아버지는 사람이 봐야 한다.
UPDATE people
SET father_source = 'unknown',
    needs_human = true,
    updated_at = now()
WHERE father_raw IS NOT NULL
  AND father_id IS NULL;

-- 페이지 참조의 대상 페이지 채우기
UPDATE page_refs r
SET target_page_id = p.id
FROM pages p
WHERE r.target_page_id IS NULL
  AND p.section_id = r.target_section_id
  AND p.printed_page_no = r.target_page_no;

UPDATE index_entries i
SET target_page_id = p.id
FROM pages p
WHERE i.target_page_id IS NULL
  AND i.target_section_id IS NOT NULL
  AND p.section_id = i.target_section_id
  AND p.printed_page_no = i.target_page_no;

UPDATE toc_entries t
SET target_page_id = p.id
FROM pages p
WHERE t.target_page_id IS NULL
  AND p.section_id = t.target_section_id
  AND p.printed_page_no = t.target_page_no;

-- children[] 중 같은 페이지에 실제 인물이 있으면 연결
WITH matches AS (
  SELECT r.id, min(p.id) AS person_id, count(*) AS matches
  FROM relations r
  JOIN people p
    ON p.source_page_id = r.source_page_id
   AND p.as_printed = r.to_as_printed
  WHERE r.to_person_id IS NULL
    AND r.to_as_printed IS NOT NULL
    AND p.id <> r.from_person_id
  GROUP BY r.id
)
UPDATE relations r
SET to_person_id = matches.person_id
FROM matches
WHERE r.id = matches.id
  AND matches.matches = 1;

-- father_id 순환 검사
DO $do$
DECLARE
  bad integer;
BEGIN
  WITH RECURSIVE walk AS (
    SELECT id, father_id, ARRAY[id] AS path, false AS cycle
    FROM people
    WHERE father_id IS NOT NULL
    UNION ALL
    SELECT w.id, p.father_id, w.path || p.id, p.id = ANY(w.path)
    FROM walk w
    JOIN people p ON p.id = w.father_id
    WHERE NOT w.cycle
  )
  SELECT count(*) INTO bad FROM walk WHERE cycle;
  IF bad > 0 THEN
    RAISE EXCEPTION 'father cycle detected in % row(s)', bad;
  END IF;
END
$do$;
"""


def render_sql(plan: dict, include_schema: bool, schema_path: Path, source_file: str) -> str:
    parts: list[str] = []
    if include_schema:
        parts.append(schema_path.read_text(encoding="utf-8").rstrip())
        parts.append("")
    parts.append("BEGIN;")
    parts.append(emit_sections())
    parts.extend(emit_pages(plan["pages"]))
    parts.extend(emit_unapproved_cleanup())

    for page_plan in plan["plans"]:
        parts.extend(emit_page_deletes(page_plan))
        parts.extend(emit_people(page_plan))
        parts.extend(emit_names(page_plan))
        parts.extend(emit_events(page_plan))
        parts.extend(emit_marriages(page_plan))
        parts.extend(emit_burials(page_plan))
        parts.extend(emit_relations(page_plan))
        parts.extend(emit_page_refs(page_plan))
        parts.extend(emit_texts(page_plan))
        parts.extend(emit_tables(page_plan))
        parts.extend(emit_unreadable(page_plan))
        parts.extend(emit_index_entries(page_plan))
        parts.extend(emit_toc(page_plan))
        parts.extend(emit_generation_chars(page_plan))

    parts.append(FINAL_SQL.strip())
    warnings_json = json.dumps(plan["warnings"], ensure_ascii=False, separators=(",", ":"))
    parts.append(
        "INSERT INTO import_runs (finished_at, source_file, pages, people, warnings)\n"
        f"VALUES (now(), {q(source_file)}, {len(plan['pages'])}, {plan['counts']['people']}, "
        f"{q(warnings_json)}::jsonb);"
    )
    parts.append("COMMIT;")
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def apply_with_psql(dsn: str, sql: str) -> None:
    psql = shutil.which("psql")
    if not psql:
        raise ValueError(
            "psql을 찾을 수 없습니다. `--sql`로 파일을 만든 뒤 PostgreSQL 클라이언트로 실행하세요."
        )
    completed = subprocess.run(
        [psql, dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
        input=sql,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError(f"psql 실행이 실패했습니다 (exit {completed.returncode}).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="approved.jsonl 또는 페이지 JSON")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="DDL 파일")
    parser.add_argument("--sql", type=Path, help="생성할 SQL 파일 (기본 data/exports/import.sql)")
    parser.add_argument("--stdout", action="store_true", help="SQL을 표준출력으로 보낸다")
    parser.add_argument("--dsn", help="PostgreSQL 연결 문자열. psql로 바로 적용한다")
    parser.add_argument("--include-schema", action="store_true", help="SQL 앞에 db/schema.sql을 붙인다")
    parser.add_argument("--dry-run", action="store_true", help="적재 계획만 확인하고 SQL을 쓰지 않는다")
    args = parser.parse_args()

    try:
        records = load_records(args.input)
        plan = build_plan(records)
    except ValueError as exc:
        print(f"중단: {exc}", file=sys.stderr)
        return 1

    def log(message: str = "") -> None:
        print(message, file=sys.stderr if args.stdout else sys.stdout)

    log(f"input: {args.input}")
    log(f"approved pages: {len(records)} / manifest pages: {len(plan['pages'])}")
    for key in (
        "people",
        "marriages",
        "page_refs",
        "relations",
        "names",
        "events",
        "burials",
        "texts",
        "index_entries",
        "generation_chars",
    ):
        log(f"  {key}: {plan['counts'][key]}")
    if plan["warnings"]:
        log(f"warnings: {len(plan['warnings'])}")
        for message in plan["warnings"][:20]:
            log(f"  ! {message}")
        if len(plan["warnings"]) > 20:
            log(f"  ... 외 {len(plan['warnings']) - 20}건")

    if args.dry_run:
        return 0

    if args.include_schema and not args.schema.exists():
        print(f"중단: 스키마 파일이 없습니다: {args.schema}", file=sys.stderr)
        return 1

    source_file = str(args.input.relative_to(ROOT)) if args.input.is_relative_to(ROOT) else str(args.input)
    sql = render_sql(plan, args.include_schema, args.schema, source_file)

    if args.dsn:
        try:
            apply_with_psql(args.dsn, sql)
        except ValueError as exc:
            print(f"중단: {exc}", file=sys.stderr)
            return 1
        print("적재 완료")
        return 0

    if args.stdout:
        sys.stdout.write(sql)
        return 0

    out = args.sql or DEFAULT_SQL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sql, encoding="utf-8")
    print(f"wrote {out}")
    print(f"apply: psql \"$DATABASE_URL\" -v ON_ERROR_STOP=1 -f {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
