"""Rebuild one saved page's relationship drafts without running OCR.

Usage: python -m ocr.refresh_relationships output/003/page.json [--apply]
The default previews changes. Applying backs up the original page first.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from .jokbo_ocr import parse_relationships
from .storage import page_name, save_page_result, validate_page_result
from .page_geometry import layout_evidence, map_evidence


def refreshed_relationships(page: dict, state: dict) -> list[dict]:
    """Keep reviewed edges and their IDs; replace only unedited OCR drafts."""
    name = page_name(page)
    old = page.get("relationship_candidates", [])
    updates = state.get("relationship_updates", {})
    protected = [r for r in old if r.get("review_status", "needs_review") != "needs_review"
                 or f"{name}::{r.get('relationship_id', '')}" in updates]
    protected_children = {r.get("child_candidate_id") for r in protected}
    geometry = page.get("page_geometry") or {}
    roi = geometry.get("ocr_table_roi") or page.get("table_roi") or {}
    width = roi.get("width") or page.get("image_size", {}).get("width")
    if not width:
        raise ValueError("페이지 폭/ROI가 없어 관계를 다시 계산할 수 없습니다.")
    proposed = parse_relationships(layout_evidence(page["rows"]), width, table_x=roi.get("x", 0))
    if geometry.get("applied"):
        size = page["image_size"]
        proposed = map_evidence(proposed, geometry["ocr_to_source"], (size["width"], size["height"]))
    used_ids = {r.get("relationship_id") for r in old}
    pending_by_child = {}
    for relation in old:
        if relation not in protected:
            pending_by_child.setdefault(relation.get("child_candidate_id"), relation)
    result = deepcopy(protected)
    serial = 1
    for relation in proposed:
        child = relation.get("child_candidate_id")
        if child in protected_children:
            continue
        previous = pending_by_child.get(child, {})
        identifier = previous.get("relationship_id")
        if not identifier:
            while f"R{serial:04d}" in used_ids:
                serial += 1
            identifier = f"R{serial:04d}"
            used_ids.add(identifier)
        result.append({**relation, "relationship_id": identifier, "source_page": name})
    return result


def refresh_page(path: Path, apply: bool = False) -> dict:
    """Preview or atomically save drafts, leaving all non-relationship data intact."""
    if path.name != "page.json":
        raise ValueError("페이지별 page.json 경로를 지정하세요. 구형 OCR 파일은 변경하지 않습니다.")
    original = path.read_bytes()
    page = json.loads(original)
    validate_page_result(deepcopy(page), path)
    root = path.parent.parent
    state_path = root / "review_state.json"
    state_bytes = state_path.read_bytes() if state_path.exists() else None
    state = json.loads(state_bytes) if state_bytes is not None else {}
    old = page["relationship_candidates"]
    new = refreshed_relationships(page, state)
    old_by_child = {r.get("child_candidate_id"): r for r in old}
    new_by_child = {r.get("child_candidate_id"): r for r in new}
    summary = {"before": len(old), "after": len(new),
               "reparented": sum(old_by_child[c].get("parent_candidate_id") != r.get("parent_candidate_id")
                                 for c, r in new_by_child.items() if c in old_by_child),
               "removed": len(old_by_child.keys() - new_by_child.keys()), "applied": False}
    if apply and new != old:
        if path.read_bytes() != original or (state_path.read_bytes() if state_path.exists() else None) != state_bytes:
            raise ValueError("페이지 또는 검수 상태가 변경되었습니다. 다시 실행하세요.")
        descriptor, backup = tempfile.mkstemp(prefix="page.relationships-", suffix=".json.bak", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(original)
        page["relationship_candidates"] = new
        save_page_result(root, page)
        summary.update(applied=True, backup=backup)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="기존 OCR을 유지하고 한 페이지의 미검수 관계 후보만 다시 계산합니다.")
    parser.add_argument("page", type=Path, help="예: output/003/page.json")
    parser.add_argument("--apply", action="store_true", help="기존 페이지 백업 후 관계 후보 저장 (생략 시 미리보기)")
    args = parser.parse_args()
    try:
        print(json.dumps(refresh_page(args.page, args.apply), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"관계 재계산 실패: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
