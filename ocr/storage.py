"""Page-based OCR persistence with read-only support for older output layouts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def page_name(page):
    return str(page.get("source_page") or Path(page["source_image"]).name)


def read_records(path, default=None):
    if not path.exists():
        return list(default or [])
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError(f"JSON 객체 배열이 필요합니다: {path}")
    return records


def has_ocr_output(root):
    return root.is_dir() and ((root / "ocr_results.json").is_file()
                              or any(root.glob("*/page.json")))


def read_page_result(path):
    page = json.loads(path.read_text(encoding="utf-8"))
    return validate_page_result(page, path)


def validate_page_result(page, path):
    if not isinstance(page, dict) or not isinstance(page.get("source_image"), str) or not page["source_image"]:
        raise ValueError(f"페이지 원본 경로가 없습니다: {path}")
    if page.get("schema_version") != 1:
        raise ValueError(f"지원하지 않는 페이지 형식입니다: {path}")
    for key in ("rows", "people_candidates", "relationship_candidates"):
        records = page.get(key)
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise ValueError(f"페이지 {key} 배열이 올바르지 않습니다: {path}")
    name = page_name(page)
    if any(person.get("source_page") != name for person in page["people_candidates"]):
        raise ValueError(f"인물 후보의 원본 페이지가 다릅니다: {path}")
    page["relationship_candidates"] = [{**rel, "source_page": rel.get("source_page") or name}
                                       for rel in page["relationship_candidates"]]
    if any(rel["source_page"] != name for rel in page["relationship_candidates"]):
        raise ValueError(f"관계 후보의 원본 페이지가 다릅니다: {path}")
    page["page_output_dir"] = str(path.parent)
    return page


def check_page_target(root, source):
    """Reject a different scan sharing the same output folder stem."""
    target = root / source.stem / "page.json"
    if target.exists() and page_name(read_page_result(target)) != source.name:
        raise ValueError(f"다른 원본 페이지가 이미 저장되어 있습니다: {target}")


def save_page_result(root, page):
    """Publish a complete page atomically; earlier page JSON survives failed writes."""
    source = Path(page["source_image"])
    check_page_target(root, source)
    folder = root / source.stem
    folder.mkdir(parents=True, exist_ok=True)
    stored = {**page, "schema_version": 1, "page_output_dir": str(folder)}
    stored = validate_page_result(stored, folder / "page.json")
    # Serialize before opening a temporary file so invalid values cannot replace evidence.
    payload = json.dumps(stored, ensure_ascii=False, indent=2)
    descriptor, temporary = tempfile.mkstemp(prefix=".page-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary, folder / "page.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def discover_legacy_pages(root, pages, people):
    """Recover legacy page folders omitted from the old aggregate, without writes."""
    known_pages = {page_name(page) for page in pages}
    known_ids = {person.get("person_id") for person in people}
    templates = [Path(page["source_image"]) for page in pages if page.get("source_image")]
    suffixes = list(dict.fromkeys(template.suffix for template in templates if template.suffix))
    entries, warnings = [], []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder / "rows.json").is_file():
            continue
        try:
            # A new page.json supersedes every old copy of that page.
            if (folder / "page.json").exists():
                continue
            rows = read_records(folder / "rows.json")
            candidates = read_records(folder / "people_candidates.json")
            relations = read_records(folder / "relationship_candidates.json")
            if not rows:
                raise ValueError("OCR 행이 없습니다")
            names = {person.get("source_page") for person in candidates}
            if len(names) > 1:
                raise ValueError("한 폴더에 여러 원본 페이지가 섞여 있습니다")
            name = next(iter(names), None) or next((folder.name + suffix for suffix in suffixes), None)
            if not name:
                raise ValueError("원본 스캔의 파일 형식을 확인할 수 없습니다")
            if name in known_pages:
                continue
            if any(person.get("person_id") in known_ids for person in candidates):
                raise ValueError("기존 인물 ID와 충돌합니다")
            source = next((candidate for template in templates
                           for candidate in (template.parent / name, root.parent / template.parent / name, root / name)
                           if candidate.is_file()), None)
            if source is None:
                raise ValueError(f"원본 스캔 {name}을 찾을 수 없습니다")
            relations = [{**rel, "source_page": rel.get("source_page") or name} for rel in relations]
            if any(rel["source_page"] != name for rel in relations):
                raise ValueError("관계 후보의 원본 페이지가 다릅니다")
            page = {"source_page": name, "source_image": str(source.resolve()),
                    "page_output_dir": str(folder), "rows": rows,
                    "people_candidates": candidates, "relationship_candidates": relations}
            entries.append({"page_result": page, "people": candidates, "relationships": relations})
            known_pages.add(name)
            known_ids.update(person.get("person_id") for person in candidates)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{folder.name}: {exc}")
    return entries, warnings


def load_ocr_output(root):
    """Read canonical pages first, filling only other pages from legacy files."""
    canonical = [read_page_result(path) for path in sorted(root.glob("*/page.json"))]
    pages_by_name = {page_name(page): page for page in canonical}
    old_pages = read_records(root / "ocr_results.json")
    for page in old_pages:
        if not isinstance(page.get("source_image"), str) or not page["source_image"]:
            raise ValueError("기존 ocr_results.json에 페이지 원본 경로가 없습니다")
        for key in ("rows", "people_candidates", "relationship_candidates"):
            records = page.get(key, [])
            if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
                raise ValueError(f"기존 ocr_results.json의 {key} 배열이 올바르지 않습니다")
    old_people = read_records(root / "people_candidates.json",
                              [p for page in old_pages for p in page.get("people_candidates", [])])
    old_rels = read_records(root / "relationship_candidates.json",
                            [{**rel, "source_page": page_name(page)} for page in old_pages
                             for rel in page.get("relationship_candidates", [])])
    if any(not item.get("source_page") for item in old_people + old_rels):
        raise ValueError("기존 루트 후보 JSON에 source_page가 없습니다")
    for page in old_pages:
        name = page_name(page)
        if name in pages_by_name:
            continue
        pages_by_name[name] = {**page,
                              "people_candidates": [p for p in old_people if p.get("source_page") == name],
                              "relationship_candidates": [r for r in old_rels if r.get("source_page") == name]}
    pages = list(pages_by_name.values())
    people = [p for page in pages for p in page["people_candidates"]]
    extras, warnings = discover_legacy_pages(root, pages, people)
    pages.extend(entry["page_result"] for entry in extras)
    pages.sort(key=lambda page: page_name(page).lower())
    people = [p for page in pages for p in page["people_candidates"]]
    relationships = [{**rel, "source_page": page_name(page)} for page in pages
                     for rel in page["relationship_candidates"]]
    return pages, people, relationships, warnings
