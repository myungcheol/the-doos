#!/usr/bin/env python3
"""Local Streamlit review UI for Jokbo OCR v6 outputs."""
from __future__ import annotations

import base64
import csv
import json
import hashlib
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from person_info_extractor import extract_person_info_draft, get_field_source_columns
from person_data_model import (
    build_person_registry, build_raw_data, build_reviewed_data, ensure_person_uid,
    make_source_occurrence, person_local_key, registry_options, strip_name_marker,
)
from review_helpers import (
    person_number_map, format_person_reference, filter_relationships_for_person,
    format_relationship_label, relationship_bbox_anchors, resolve_person_field_value,
)

st.set_page_config(page_title="Jokbo OCR 검수", page_icon="📜", layout="wide")

_IMAGE_VIEWER_DIR = Path(__file__).resolve().parent / "components" / "jokbo_image_viewer"
jokbo_image_viewer = components.declare_component(
    "jokbo_image_viewer", path=str(_IMAGE_VIEWER_DIR)
)

# Keep semantically different overlays far apart in hue and brightness.
# Two greens, two blues, and two oranges intentionally use clearly distinct shades.
REVIEW_COLORS = {
    "person_needs_review": (249, 115, 22, 240),   # bright orange
    "person_confirmed": (132, 204, 22, 240),      # lime green
    "person_selected": (37, 99, 235, 250),        # cobalt blue
    "parent_selected": (168, 85, 247, 250),       # violet
    "relation_confirmed": (22, 101, 52, 220),     # forest green
    "relation_active_confirmed": (8, 145, 178, 250),  # teal blue
    "relation_candidate": (154, 52, 18, 245),     # burnt orange
    "ocr_name": (219, 39, 119, 240),              # magenta
    "ocr_record": (14, 165, 233, 230),            # sky blue
    "ocr_token": (250, 204, 21, 230),             # yellow
}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


@st.cache_data(show_spinner=False)
def image_data_url_from_file(image_path: str, modified_ns: int, file_size: int) -> str:
    """Read and encode the source scan once; keep it stable across UI reruns."""
    path = Path(image_path)
    suffix = path.suffix.lower()
    if suffix in {".tif", ".tiff"}:
        source = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f"이미지를 읽지 못했습니다: {path}")
        ok, encoded_image = cv2.imencode(".png", source)
        if not ok:
            raise ValueError(f"브라우저용 이미지로 변환하지 못했습니다: {path}")
        raw = encoded_image.tobytes()
        mime = "image/png"
    else:
        raw = path.read_bytes()
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".bmp": "image/bmp",
        }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@st.cache_data(show_spinner=False)
def cached_extract_person_info_draft(
    person: dict[str, Any], page_result: dict[str, Any], page_people: list[dict[str, Any]]
) -> dict[str, Any]:
    """Cache deterministic OCR evidence extraction while keeping the UI responsive."""
    return extract_person_info_draft(person, page_result, page_people)


def find_output_root(raw_path: str) -> Path | None:
    path = Path(raw_path).expanduser().resolve()
    candidates = [path, path / "paddleocr", path / "tesseract"]
    for candidate in candidates:
        if (candidate / "ocr_results.json").exists():
            return candidate
    return None


def effective_name(person: dict[str, Any], state: dict[str, Any]) -> str:
    update = state.get("people_updates", {}).get(person.get("person_id"), {})
    candidate = (update.get("transcribed_name_hanja")
                 or person.get("transcribed_name_hanja")
                 or person.get("name_hanja_candidate") or "")
    normalized, _, _ = strip_name_marker(candidate)
    return normalized or "(이름 미인식)"


def effective_person_status(person: dict[str, Any], state: dict[str, Any]) -> str:
    update = state.get("people_updates", {}).get(person.get("person_id"), {})
    return update.get("review_status") or person.get("review_status", "needs_review")


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
            "birth_text", "death_text", "office_title", "spouse_text", "spouses",
            "burial_text", "biography_text", "notes", "information_review_status",
            "source_record_ocr_text", "raw_data", "reviewed_data", "source_occurrences",
            "bbox", "image_file", "ocr_confidence",
        ], extrasaction="ignore")
        writer.writeheader()
        csv_people = []
        for person in people:
            row = dict(person)
            for nested_key in ("spouses", "raw_data", "reviewed_data", "source_occurrences", "bbox"):
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
    page_results = page_results or []
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
                draft_cache[cache_key] = cached_extract_person_info_draft(
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


@st.cache_data(show_spinner=False)
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


def get_person_row_text(page_result: dict[str, Any], person: dict[str, Any]) -> str:
    """Return OCR text for the row containing a person, when available."""
    row_id = person.get("source_row_id")
    for row in page_result.get("rows", []) or []:
        if row.get("row_id") == row_id:
            return str(row.get("band_text") or row.get("text") or "")
    return str(person.get("evidence_text") or "")


def parse_optional_generation(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("세대는 숫자로 입력하거나 비워 두세요.") from exc


def _rgba_css(color: tuple[int, int, int, int]) -> tuple[str, float]:
    return "#%02X%02X%02X" % color[:3], color[3] / 255.0


def _source_bbox(bbox: dict[str, Any], offset: tuple[int, int]) -> dict[str, float]:
    ox, oy = offset
    return {
        "x": float(bbox.get("x", 0)) - ox,
        "y": float(bbox.get("y", 0)) - oy,
        "width": float(bbox.get("width", 0)),
        "height": float(bbox.get("height", 0)),
    }


def build_viewer_overlay_data(
    image_size: tuple[int, int], offset: tuple[int, int], people: list[dict[str, Any]],
    relationships: list[dict[str, Any]], state: dict[str, Any],
    selected_id: str | None = None, pending_parent_id: str | None = None,
    active_parent_id: str | None = None,
    ocr_boxes: list[dict[str, Any]] | None = None,
    ocr_focus: str = "all",
) -> dict[str, Any]:
    """Return vector overlay primitives in original image coordinates.

    The browser renders these over a stable source image. Changing zoom or
    selecting a person updates only SVG overlays; it never reloads the bitmap.
    """
    width, height = image_size
    person_map = {p.get("person_id"): p for p in people}
    relations: list[dict[str, Any]] = []
    for rel in relationships:
        status = rel.get("review_status")
        parent_id = rel.get("parent_candidate_id")
        if status == "rejected":
            continue
        active_parent_edge = bool(active_parent_id and parent_id == active_parent_id)
        if status != "confirmed" and not active_parent_edge:
            continue
        parent = person_map.get(parent_id)
        child = person_map.get(rel.get("child_candidate_id"))
        if not parent or not child:
            continue
        parent_anchor, child_anchor = relationship_bbox_anchors(
            parent.get("bbox") or {}, child.get("bbox") or {}
        )
        color_key = (
            "relation_active_confirmed" if active_parent_edge and status == "confirmed" else
            "relation_candidate" if active_parent_edge else "relation_confirmed"
        )
        color, opacity = _rgba_css(REVIEW_COLORS[color_key])
        relations.append({
            "x1": parent_anchor[0] - offset[0], "y1": parent_anchor[1] - offset[1],
            "x2": child_anchor[0] - offset[0], "y2": child_anchor[1] - offset[1],
            "color": color, "opacity": opacity,
            "width": 6 if color_key == "relation_active_confirmed" else 3,
            "arrow": color_key == "relation_active_confirmed",
        })

    person_boxes: list[dict[str, Any]] = []
    for index, person in enumerate(people, start=1):
        pid = person.get("person_id")
        status = effective_person_status(person, state)
        color_key = (
            "person_selected" if pid == selected_id else
            "parent_selected" if pid == pending_parent_id else
            "person_confirmed" if status == "confirmed" else "person_needs_review"
        )
        color, opacity = _rgba_css(REVIEW_COLORS[color_key])
        raw_data = person.get("raw_data") or {}
        raw_name = raw_data.get("name_ocr") or {}
        raw_record = raw_data.get("record_ocr") or {}
        raw_fields = raw_data.get("field_ocr") or {}

        def make_ocr_items(source_items: list[dict[str, Any]], color_key: str) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            item_color, item_opacity = _rgba_css(REVIEW_COLORS[color_key])
            for source_item in source_items or []:
                source_bbox = source_item.get("bbox") or {}
                if not source_bbox:
                    continue
                tokens = []
                for token in source_item.get("token_boxes") or []:
                    token_bbox = token.get("bbox") or {}
                    if token_bbox:
                        token_color, token_opacity = _rgba_css(REVIEW_COLORS["ocr_token"])
                        tokens.append({
                            "bbox": _source_bbox(token_bbox, offset),
                            "color": token_color, "opacity": token_opacity,
                        })
                result.append({
                    "bbox": _source_bbox(source_bbox, offset),
                    "label": str(source_item.get("text") or "OCR")[:48],
                    "color": item_color, "opacity": item_opacity, "tokens": tokens,
                })
            return result

        name_ocr = []
        name_bbox = raw_name.get("bbox") or person.get("bbox") or {}
        if name_bbox:
            name_color, name_opacity = _rgba_css(REVIEW_COLORS["ocr_name"])
            name_ocr.append({
                "bbox": _source_bbox(name_bbox, offset),
                "label": "이름 OCR: " + str(raw_name.get("raw_text") or person.get("raw_name_ocr") or ""),
                "color": name_color, "opacity": name_opacity, "tokens": [],
            })
        all_ocr = make_ocr_items(raw_record.get("columns") or [], "ocr_record")
        field_ocr = {
            field: make_ocr_items(source.get("columns") or [], "ocr_record")
            for field, source in raw_fields.items()
        }
        person_boxes.append({
            "bbox": _source_bbox(person.get("bbox") or {}, offset),
            "person_id": pid,
            "label": f"{index}. {effective_name(person, state)}",
            "color": color, "selected_color": _rgba_css(REVIEW_COLORS["person_selected"])[0],
            "parent_color": _rgba_css(REVIEW_COLORS["parent_selected"])[0],
            "opacity": opacity,
            "width": 4 if pid in {selected_id, pending_parent_id} else 2,
            "selected": pid == selected_id,
            # OCR bboxes are sent once with the page. The browser can switch a
            # person's highlighted OCR fields instantly on image selection,
            # without waiting for another Streamlit rerun.
            "ocr": {"name": name_ocr, "all": all_ocr, "fields": field_ocr},
        })

    ocr_overlays: list[dict[str, Any]] = []
    for item in (ocr_boxes or []):
        bbox = item.get("bbox") or {}
        if not bbox:
            continue
        color_key = "ocr_name" if item.get("kind") == "name" else "ocr_record"
        color, opacity = _rgba_css(REVIEW_COLORS[color_key])
        tokens = []
        for token in item.get("token_boxes") or []:
            token_bbox = token.get("bbox") or {}
            if token_bbox:
                token_color, token_opacity = _rgba_css(REVIEW_COLORS["ocr_token"])
                tokens.append({
                    "bbox": _source_bbox(token_bbox, offset),
                    "color": token_color, "opacity": token_opacity,
                })
        ocr_overlays.append({
            "bbox": _source_bbox(bbox, offset),
            "label": str(item.get("label") or item.get("text") or "OCR")[:48],
            "color": color, "opacity": opacity, "tokens": tokens,
        })

    return {
        "image_width": int(width), "image_height": int(height),
        "selected_id": selected_id, "ocr_focus": ocr_focus,
        "relationships": relations, "people": person_boxes, "ocr_boxes": ocr_overlays,
    }


def find_person_at_click(people: list[dict[str, Any]], x: float, y: float,
                         offset: tuple[int, int]) -> dict[str, Any] | None:
    ox, oy = offset
    candidates = []
    for person in people:
        bbox = person.get("bbox") or {}
        x0, y0 = float(bbox.get("x", 0)) - ox, float(bbox.get("y", 0)) - oy
        x1 = x0 + float(bbox.get("width", 0))
        y1 = y0 + float(bbox.get("height", 0))
        # A small hit area makes clicking narrow vertical name boxes easier.
        pad_x, pad_y = max(12.0, (x1 - x0) * 0.35), 8.0
        if x0 - pad_x <= x <= x1 + pad_x and y0 - pad_y <= y <= y1 + pad_y:
            center_distance = math.hypot((x0 + x1) / 2 - x, (y0 + y1) / 2 - y)
            candidates.append((center_distance, person))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def save_state(root: Path, state: dict[str, Any], base_people: list[dict[str, Any]],
               base_relationships: list[dict[str, Any]],
               page_results: list[dict[str, Any]] | None = None) -> None:
    state["updated_at"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
    (root / "review_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    people, rels = build_review_data(root, base_people, base_relationships, state, page_results)
    write_exports(root, people, rels)


def main() -> None:
    st.title("족보 OCR 검수 v6.7")
    st.caption("이미지를 확대해 OCR 글자 영역을 확인하고, 인물별 원본 OCR과 검수 데이터를 분리 저장합니다. 인물은 영구 UUID로 식별하며 부모·자녀 관계는 해당 ID를 참조합니다.")

    with st.sidebar:
        st.header("작업 폴더")
        raw_root = st.text_input(
            "OCR 결과 디렉터리", value="output",
            help="ocr_results.json이 있는 폴더. both 실행 결과라면 output/paddleocr를 지정해도 됩니다.",
        )
        max_height = st.slider("페이지 표시 높이", 400, 1000, 650, 25,
                               help="기본값은 페이지 전체를 볼 수 있도록 축소하는 높이입니다.")
        detail_panel_height = st.slider(
            "오른쪽 검수 패널 높이", 500, 1000, 780, 20,
            help="오른쪽 인물/관계 입력 영역만 내부 스크롤됩니다. 왼쪽 페이지 이미지는 그대로 보입니다.",
        )
        click_mode = st.radio("이미지 클릭 모드", ["부모 → 자녀 연결", "인물 선택 / 이름 검수"], index=0)

    root = find_output_root(raw_root)
    if root is None:
        st.info("먼저 OCR을 실행한 뒤 `ocr_results.json`이 생성된 결과 폴더를 지정하세요. 예: `output` 또는 `output/paddleocr`.")
        st.code("python jokbo_ocr.py ./scan/ --ocr-engine paddleocr --rows 6 --output output")
        return

    page_results = read_json(root / "ocr_results.json", [])
    if not page_results:
        st.error("ocr_results.json에 페이지 결과가 없습니다.")
        return
    all_people = read_json(root / "people_candidates.json", [])
    all_relationships = read_json(root / "relationship_candidates.json", [])
    state = read_json(root / "review_state.json", {
        "people_updates": {}, "relationship_updates": {}, "manual_relationships": []
    })
    state.setdefault("people_updates", {})
    state.setdefault("relationship_updates", {})
    state.setdefault("manual_relationships", [])
    state.setdefault("person_uid_map", {})
    state.setdefault("edition", {"edition_id": "jokbo-1987", "publication_year": 1987, "volume": None})
    state.setdefault("page_metadata", {})
    # Assign permanent IDs once and keep them in review_state.json. Location is
    # provenance, not identity, so a revised edition can reuse the same ID.
    uid_count_before = len(state["person_uid_map"])
    for base_person in all_people:
        ensure_person_uid(base_person, state)
    if len(state["person_uid_map"]) != uid_count_before:
        (root / "review_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    with st.sidebar:
        st.divider()
        st.subheader("판본 및 인물 ID")
        edition_id = st.text_input("판본 ID", value=str(state["edition"].get("edition_id") or "jokbo-1987"), key="edition_id_input")
        publication_year = st.number_input(
            "발행 연도", min_value=1000, max_value=None,
            value=int(state["edition"].get("publication_year") or 1987), step=1,
            key="publication_year_input",
        )
        volume = st.text_input("권/책", value=str(state["edition"].get("volume") or ""), key="edition_volume_input")
        registry_file = st.text_input(
            "공용 인물 레지스트리 파일", value="person_registry.json",
            help="다른 판본/연도 결과에서도 동일 파일을 지정하면 기존 인물 ID를 재사용할 수 있습니다.",
        )
    state["edition"] = {
        "edition_id": edition_id.strip() or f"jokbo-{int(publication_year)}",
        "publication_year": int(publication_year), "volume": volume.strip() or None,
    }
    registry_path = Path(registry_file or "person_registry.json").expanduser()
    if not registry_path.is_absolute():
        # Resolve relative to the project working directory, not the OCR output
        # folder, so multiple edition/output folders can share one registry.
        registry_path = (Path.cwd() / registry_path).resolve()
    registry_data = read_json(registry_path, {"schema_version": 1, "persons": {}})
    people, relationships = build_review_data(root, all_people, all_relationships, state, page_results)

    page_names = [item.get("source_page", Path(item.get("source_image", "page")).name) for item in page_results]
    page_col, spacer_col = st.columns([1, 2])
    with page_col:
        selected_page_name = st.selectbox("검수할 페이지", page_names)
    page_printed_key = f"printed_page_{selected_page_name}"
    page_metadata = state["page_metadata"].setdefault(selected_page_name, {})
    printed_page = st.text_input(
        "족보에 인쇄된 쪽수 (모르면 비움)",
        value=str(page_metadata.get("printed_page") or ""), key=page_printed_key,
    )
    state["page_metadata"][selected_page_name]["printed_page"] = printed_page.strip() or None
    previous_page = st.session_state.get("active_review_page")
    previous_mode = st.session_state.get("active_click_mode")
    if previous_page != selected_page_name or previous_mode != click_mode:
        st.session_state["pending_parent_id"] = None
        st.session_state["selected_person_id"] = None
        st.session_state["last_click_message"] = None
        st.session_state["active_review_page"] = selected_page_name
        st.session_state["active_click_mode"] = click_mode

    page_result = next(item for item in page_results if item.get("source_page", Path(item.get("source_image", "page")).name) == selected_page_name)
    page_dir_raw = page_result.get("page_output_dir")
    page_dir = Path(page_dir_raw) if page_dir_raw else root / Path(str(page_result.get("source_image", "page"))).stem
    if not page_dir.is_absolute():
        page_dir = (root / page_dir).resolve()
    if not page_dir.exists():
        page_dir = root / Path(str(page_result.get("source_image", selected_page_name))).stem
    page_dir.mkdir(parents=True, exist_ok=True)
    page_people = [p for p in people if p.get("source_page") == selected_page_name]
    page_rels = [r for r in relationships if r.get("source_page") == selected_page_name]
    page_person_lookup = {p.get("person_id"): p for p in page_people}
    page_person_numbers = person_number_map(page_people)
    page_name_getter = lambda person: effective_name(person, state)
    confirmed_people = sum(effective_person_status(p, state) == "confirmed" for p in page_people)
    confirmed_rels = sum(r.get("review_status") == "confirmed" for r in page_rels)

    # Persistent controls are placed above the image so they remain visible without scrolling.
    pending_parent = st.session_state.get("pending_parent_id")
    manual_on_page = [r for r in state["manual_relationships"] if r.get("source_page") == selected_page_name]
    tool1, tool2, tool3, tool4 = st.columns([1.2, 1.2, 2.2, 1.5])
    with tool1:
        if pending_parent:
            if st.button("부모 선택 취소", key="cancel_pending_top", use_container_width=True):
                st.session_state["pending_parent_id"] = None
                st.session_state["selected_person_id"] = None
                st.session_state["last_click_message"] = "부모 선택을 취소했습니다."
                st.rerun()
        else:
            st.button("부모 선택 취소", key="cancel_pending_top_disabled", disabled=True, use_container_width=True)
    with tool2:
        if manual_on_page:
            if st.button("마지막 연결 되돌리기", key="undo_manual_top", use_container_width=True):
                last_manual = manual_on_page[-1]
                state["manual_relationships"] = [
                    r for r in state["manual_relationships"]
                    if not (r.get("source_page") == selected_page_name and
                            r.get("relationship_id") == last_manual.get("relationship_id"))
                ]
                save_state(root, state, all_people, all_relationships, page_results)
                st.session_state["last_click_message"] = "마지막으로 추가한 수동 관계를 취소했습니다."
                st.rerun()
        else:
            st.button("마지막 연결 되돌리기", key="undo_manual_top_disabled", disabled=True, use_container_width=True)
    with tool3:
        if pending_parent:
            parent_label = format_person_reference(
                pending_parent, page_person_lookup, page_person_numbers, page_name_getter
            )
            parent_links = [
                r for r in page_rels
                if r.get("parent_candidate_id") == pending_parent
                and r.get("review_status") != "rejected"
            ]
            child_count = sum(r.get("review_status") == "confirmed" for r in parent_links)
            pending_child_count = sum(r.get("review_status") != "confirmed" for r in parent_links)
            st.warning(
                f"부모 선택 중: {parent_label} → 자녀를 계속 클릭하세요. "
                f"확정 관계 {child_count}명 · 검토 후보 {pending_child_count}명"
            )
            confirmed_names = [
                format_person_reference(r.get("child_candidate_id"), page_person_lookup, page_person_numbers, page_name_getter)
                for r in parent_links if r.get("review_status") == "confirmed"
            ]
            pending_names = [
                format_person_reference(r.get("child_candidate_id"), page_person_lookup, page_person_numbers, page_name_getter)
                for r in parent_links if r.get("review_status") != "confirmed"
            ]
            if confirmed_names:
                st.markdown("**확정된 자녀 (파란 선):** " + " · ".join(confirmed_names))
            if pending_names:
                st.markdown("**검토 중 후보 (주황 선):** " + " · ".join(pending_names))
        elif click_mode == "부모 → 자녀 연결":
            st.info("이미지에서 부모를 먼저 클릭하세요. 이후 자녀를 여러 명 차례로 클릭하면 모두 같은 부모에게 연결됩니다.")
        else:
            st.info("이미지에서 검수할 인물 박스를 클릭하세요.")
    with tool4:
        st.caption("부모를 선택한 상태에서는 자녀를 연속으로 선택할 수 있습니다. 다른 부모로 바꾸려면 ‘부모 선택 취소’를 누르세요.")

    # Feedback and validation messages stay above the scan so they are not hidden below it.
    message = st.session_state.get("last_click_message")
    if message:
        if any(word in message for word in ("이미 등록", "순환", "같은 인물", "클릭해 주세요")):
            st.warning(message)
        else:
            st.info(message)

    image, offset, image_label = get_page_image(page_result, page_dir)
    image_max_width = 1050
    effective_image_height = min(max_height, max(320, int(detail_panel_height) - 110))
    selected_id = (
        st.session_state.get(f"person_select_{selected_page_name}")
        or st.session_state.get("selected_person_id")
    )
    if selected_id not in page_person_lookup:
        selected_id = None
    selected_for_overlay = page_person_lookup.get(selected_id) if selected_id else None
    selected_draft = (
        cached_extract_person_info_draft(selected_for_overlay, page_result, page_people)
        if selected_for_overlay else {}
    )
    ocr_focus_options = {
        "전체 인물 기록 OCR": "all",
        "이름 OCR": "name",
        "출생 OCR": "birth_text",
        "사망 OCR": "death_text",
        "관직 OCR": "office_title",
        "배우자 OCR": "spouse_text",
        "묘소 OCR": "burial_text",
        "자(字) OCR": "courtesy_name_hanja",
        "호(號) OCR": "pen_name_hanja",
    }
    ocr_focus_key = f"ocr_focus_{selected_page_name}"
    if ocr_focus_key not in st.session_state:
        st.session_state[ocr_focus_key] = "전체 인물 기록 OCR"
    ocr_focus_label = st.session_state.get(ocr_focus_key, "전체 인물 기록 OCR")
    ocr_boxes: list[dict[str, Any]] = []
    if selected_for_overlay:
        focus = ocr_focus_options[ocr_focus_label]
        if focus == "name":
            ocr_boxes = [{
                "kind": "name", "label": "이름 OCR: " + str(selected_for_overlay.get("raw_name_ocr") or selected_for_overlay.get("name_hanja_candidate") or ""),
                "bbox": selected_for_overlay.get("bbox") or {},
            }]
        else:
            if focus == "all":
                columns = selected_draft.get("columns") or []
            else:
                # field_sources already contains the exact OCR column objects and
                # their original-page bbox. Use them directly instead of looking
                # them up by column_id (older OCR files may omit that identifier).
                columns = get_field_source_columns(selected_draft, focus)
                if not columns and (selected_draft.get("draft_values") or {}).get(focus):
                    # Legacy review drafts may contain text but not field_sources.
                    # In that case highlight the person's full record region rather
                    # than silently showing no bbox at all.
                    columns = selected_draft.get("columns") or []
            ocr_boxes = [{
                "kind": "record", "label": str(col.get("text") or "OCR"),
                "bbox": col.get("bbox") or {}, "token_boxes": col.get("token_boxes") or [],
            } for col in columns if col.get("bbox")]
    pending_parent_id = st.session_state.get("pending_parent_id")
    overlay_payload = build_viewer_overlay_data(
        (image.shape[1], image.shape[0]), offset, page_people, page_rels, state,
        selected_id=selected_id, pending_parent_id=pending_parent_id,
        active_parent_id=pending_parent_id if click_mode == "부모 → 자녀 연결" else None,
        ocr_boxes=ocr_boxes, ocr_focus=focus,
    )
    image_path = Path(image_label) if Path(image_label).is_file() else page_dir / "table_roi.jpg"
    image_stat = image_path.stat()
    base_image_url = image_data_url_from_file(
        str(image_path.resolve()), image_stat.st_mtime_ns, image_stat.st_size
    )
    fit_scale = min(
        1.0, image_max_width / max(1, image.shape[1]),
        effective_image_height / max(1, image.shape[0]),
    )
    base_width = max(1, int(round(image.shape[1] * fit_scale)))
    base_height = max(1, int(round(image.shape[0] * fit_scale)))

    image_col, detail_col = st.columns([1.8, 1], gap="large")
    with image_col:
        st.subheader(f"원본 페이지 · {selected_page_name}")
        st.caption(
            f"{image_label} · 이미지 위의 + / − 버튼 또는 Ctrl+마우스휠로 확대·축소 · "
            "드래그로 이동 · 짧게 클릭하면 인물을 선택합니다."
        )
        click_value = jokbo_image_viewer(
            image_data=base_image_url,
            overlay_data=json.dumps(overlay_payload, ensure_ascii=False, separators=(",", ":")),
            fit_width=base_width,
            fit_height=base_height,
            viewport_height=int(effective_image_height),
            page_id=selected_page_name,
            click_mode=click_mode,
            height=int(effective_image_height) + 46,
            key=f"page_image_{selected_page_name}",
            default=None,
        )
        if click_value and isinstance(click_value, dict) and "x" in click_value and "y" in click_value:
            click_event = (click_value.get("timestamp"), click_value.get("x"), click_value.get("y"))
            event_key = f"last_click_{selected_page_name}_{click_mode}"
            if st.session_state.get(event_key) != click_event:
                st.session_state[event_key] = click_event
                # The viewer returns coordinates in the natural source-image space.
                # No Python-side zoom scale conversion is needed.
                x_img = float(click_value["x"])
                y_img = float(click_value["y"])
                person = find_person_at_click(page_people, x_img, y_img, offset)
                if person is None:
                    st.session_state["last_click_message"] = "인물 박스 안쪽을 클릭해 주세요."
                    st.rerun()
                elif click_mode == "인물 선택 / 이름 검수":
                    st.session_state["selected_person_id"] = person["person_id"]
                    st.session_state[f"person_select_{selected_page_name}"] = person["person_id"]
                    st.session_state["last_click_message"] = f"선택됨: {effective_name(person, state)}"
                    # The custom component event already caused this Streamlit
                    # run. The browser highlights the clicked bbox immediately;
                    # avoid a second explicit rerun just to refresh the right pane.
                elif not st.session_state.get("pending_parent_id"):
                    st.session_state["pending_parent_id"] = person["person_id"]
                    st.session_state["selected_person_id"] = person["person_id"]
                    st.session_state[f"person_select_{selected_page_name}"] = person["person_id"]
                    st.session_state["last_click_message"] = f"부모 선택: {effective_name(person, state)} · 이제 자녀를 클릭하세요."
                    st.rerun()
                else:
                    parent_id = st.session_state["pending_parent_id"]
                    child_id = person["person_id"]
                    if parent_id == child_id:
                        st.session_state["last_click_message"] = "같은 인물을 선택했습니다. 다른 인물을 자녀로 선택하거나 선택을 취소하세요."
                        st.rerun()
                    duplicate = any(
                        r.get("parent_candidate_id") == parent_id and
                        r.get("child_candidate_id") == child_id and
                        r.get("review_status") != "rejected" for r in relationships
                    )
                    if duplicate:
                        st.session_state["last_click_message"] = (
                            "이미 등록된 부모–자녀 관계입니다. 기존 연결을 유지했습니다. "
                            "같은 부모의 다른 자녀를 계속 선택할 수 있습니다."
                        )
                        st.rerun()
                    if would_create_cycle(parent_id, child_id, relationships):
                        st.session_state["last_click_message"] = (
                            "이 연결은 확인된 관계에 순환을 만듭니다. 부모·자녀 방향을 확인하세요. "
                            "현재 부모 선택은 유지됩니다."
                        )
                        st.rerun()
                    parent = next(p for p in page_people if p["person_id"] == parent_id)
                    existing_manual_ids = {
                        str(item.get("relationship_id")) for item in state["manual_relationships"]
                    }
                    sequence = 1
                    while True:
                        manual_id = f"{Path(selected_page_name).stem}_MANUAL_{sequence:04d}"
                        if manual_id not in existing_manual_ids:
                            break
                        sequence += 1
                    manual = {
                        "relationship_id": manual_id, "source_page": selected_page_name,
                        "type": "parent_child", "parent_candidate_id": parent_id,
                        "parent_name_hanja_candidate": effective_name(parent, state),
                        "candidate_parent_ids": [], "child_candidate_id": child_id,
                        "child_name_hanja_candidate": effective_name(person, state),
                        "relationship_basis": "manual_visual_link", "placement_role": "manually_confirmed",
                        "source_row_ids": [parent.get("source_row_id"), person.get("source_row_id")],
                        "confidence": 1.0, "review_status": "confirmed", "warning": None,
                    }
                    state["manual_relationships"].append(manual)
                    save_state(root, state, all_people, all_relationships, page_results)
                    st.session_state["last_click_message"] = (
                        f"연결 저장: {effective_name(parent, state)} → {effective_name(person, state)}. "
                        f"부모 {effective_name(parent, state)} 선택을 유지합니다. "
                        "다른 자녀를 계속 클릭하거나 ‘부모 선택 취소’를 누르세요."
                    )
                    # Keep the same parent active so one-to-many links can be created in sequence.
                    st.session_state["pending_parent_id"] = parent_id
                    st.session_state["selected_person_id"] = child_id
                    st.session_state[f"person_select_{selected_page_name}"] = child_id
                    st.rerun()

        with st.expander("색상 안내", expanded=False):
            legend = [
                ("#F97316", "밝은 주황", "미검수 인물 테두리"),
                ("#84CC16", "라임 그린", "확인된 인물 테두리"),
                ("#2563EB", "코발트 블루", "현재 선택한 인물"),
                ("#A855F7", "보라", "부모 선택 대기"),
                ("#166534", "짙은 숲색", "일반 확정 관계선"),
                ("#0891B2", "청록 블루", "선택 부모의 확정 관계선"),
                ("#9A3412", "짙은 러스트", "선택 부모의 미검수 관계 후보"),
                ("#DB2777", "마젠타", "이름 OCR Bounding Box"),
                ("#0EA5E9", "하늘색", "인물 정보 OCR Bounding Box"),
                ("#FACC15", "노랑", "문자 단위 OCR Bounding Box"),
            ]
            for start_idx in range(0, len(legend), 2):
                cols = st.columns(2)
                for col, (hex_color, color_name, meaning) in zip(cols, legend[start_idx:start_idx + 2]):
                    col.markdown(
                        f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
                        f'<span style="display:inline-block;width:18px;height:18px;flex:0 0 18px;'
                        f'background:{hex_color};border:1px solid #64748b;border-radius:4px"></span>'
                        f'<span><b>{color_name}</b> <code>{hex_color}</code><br><small>{meaning}</small></span></div>',
                        unsafe_allow_html=True,
                    )

    with detail_col:
        # Native fixed-height scroll pane keeps the left scan in view while
        # the reviewer scrolls through long forms on the right.
        with st.container(height=int(detail_panel_height), border=True, key="review_detail_scroll"):
            person_tab, relation_tab = st.tabs(["인명 검수", "관계 검수"])
            with person_tab:
                st.subheader("인물 판독")
                person_options = {
                    p["person_id"]: f"{p['person_id']} · {effective_name(p, state)} · {effective_person_status(p, state)}"
                    for p in page_people
                }
                if not person_options:
                    st.warning("이 페이지에서 인물 후보를 찾지 못했습니다.")
                    selected_person = None
                else:
                    default_id = selected_id if selected_id in person_options else next(iter(person_options))
                    selected_person_id = st.selectbox(
                        "인물 선택", list(person_options), index=list(person_options).index(default_id),
                        format_func=lambda value: person_options[value], key=f"person_select_{selected_page_name}",
                    )
                    st.session_state["selected_person_id"] = selected_person_id
                    selected_person = next(p for p in page_people if p["person_id"] == selected_person_id)
                if selected_person:
                    focus_before = st.session_state.get(ocr_focus_key, "전체 인물 기록 OCR")
                    st.selectbox(
                        "왼쪽 이미지에서 확인할 OCR 항목",
                        list(ocr_focus_options),
                        key=ocr_focus_key,
                        help="항목을 선택하면 왼쪽 원본 이미지에서 해당 OCR 영역의 Bounding Box를 강조합니다.",
                    )
                    st.caption(f"왼쪽 이미지 강조 항목: {st.session_state.get(ocr_focus_key, focus_before)}")

                    crop_path = Path(str(selected_person.get("image_file", "")))
                    if not crop_path.exists():
                        crop_path = page_dir / "columns" / f"{selected_person.get('source_column_id', '')}.png"
                    if crop_path.exists():
                        st.image(str(crop_path), caption="인명 crop", width=190)
                    st.write(f"OCR 후보: **{selected_person.get('name_hanja_candidate') or '(없음)'}**")
                    st.write(f"Confidence: {selected_person.get('ocr_confidence')}")
                    hypotheses = selected_person.get("ranked_ocr_hypotheses") or []
                    if hypotheses:
                        st.caption("OCR 대안: " + " / ".join(
                            f"{h.get('text')} ({h.get('confidence')})" for h in hypotheses[:6]
                        ))
                    update = state["people_updates"].get(selected_person_id, {})
                    # Precompute field-level OCR values as soon as an individual is selected.
                    auto_draft = cached_extract_person_info_draft(
                        selected_person, page_result, page_people
                    )
                    draft_values = auto_draft.get("draft_values", {}) if isinstance(auto_draft, dict) else {}
                    current_uid = selected_person.get("person_uid") or state.get("person_uid_map", {}).get(
                        person_local_key(selected_person, state.get("edition", {}).get("edition_id")), ""
                    )
                    st.code(f"person_uid: {current_uid}", language="text")
                    reusable_ids = registry_options(registry_data, exclude_uid=current_uid)
                    if reusable_ids:
                        reuse_choice = st.selectbox(
                            "이 인물을 기존 등록 인물과 동일인으로 연결",
                            [""] + [uid for uid, _ in reusable_ids],
                            format_func=lambda uid: "새 인물 ID 유지" if not uid else next(
                                (label for option_uid, label in reusable_ids if option_uid == uid), uid
                            ),
                            key=f"reuse_person_uid_{selected_page_name}_{selected_person_id}",
                        )
                        if st.button(
                            "선택한 기존 인물 ID 사용", key=f"apply_reuse_uid_{selected_person_id}",
                            disabled=not bool(reuse_choice), use_container_width=True,
                        ):
                            state.setdefault("person_uid_map", {})[
                                person_local_key(selected_person, state.get("edition", {}).get("edition_id"))
                            ] = reuse_choice
                            save_state(root, state, all_people, all_relationships, page_results)
                            st.session_state["last_click_message"] = f"기존 인물 ID {reuse_choice}를 연결했습니다."
                            st.rerun()
                    else:
                        st.caption("다른 판본에서 등록한 인물이 있으면 공용 레지스트리 파일을 지정한 뒤 기존 ID를 재사용할 수 있습니다.")

                    def person_value(field: str, fallback: Any = "") -> Any:
                        return resolve_person_field_value(
                            field, update, selected_person, draft_values, fallback
                        )

                    current_transcription = (
                        person_value("transcribed_name_hanja")
                        or person_value("name_hanja_candidate")
                    )
                    raw_name_ocr = str(selected_person.get("raw_name_ocr") or selected_person.get("name_hanja_candidate") or "")
                    normalized_ocr_name, inferred_marker, inferred_gender = strip_name_marker(raw_name_ocr)
                    row_ocr_text = get_person_row_text(page_result, selected_person)
                    with st.expander("원본 OCR 데이터(raw_data)", expanded=True):
                        st.write(f"**이름 OCR 원문:** `{raw_name_ocr}`")
                        st.write(f"**이름 후보(子/女 제외):** `{normalized_ocr_name}`")
                        if inferred_marker:
                            st.caption(f"앞 글자 표식: {inferred_marker} ({'아들' if inferred_marker == '子' else '딸'}) · 이 표식은 이름에서 분리해 보관합니다.")
                        source_occurrence = (selected_person.get("source_occurrences") or [{}])[0]
                        st.caption(
                            f"출처: {source_occurrence.get('publication_year') or '?'}년 판본 "
                            f"{source_occurrence.get('edition_id') or '?'} · "
                            f"인쇄 쪽수 {source_occurrence.get('printed_page') or '(미입력)'} · "
                            f"스캔 {source_occurrence.get('scan_page') or '?'} · "
                            f"행 {source_occurrence.get('row_number') or '?'} · "
                            f"오른쪽부터 {source_occurrence.get('column_number_right_to_left') or '?'}번째 열 · "
                            f"열 내 {source_occurrence.get('position_in_column') or '?'}번째"
                        )
                        st.json({
                            "image": {
                                "source_image": page_result.get("source_image"),
                                "image_file": selected_person.get("image_file"),
                                "bbox": selected_person.get("bbox"),
                            },
                            "name_ocr": {
                                "raw_text": raw_name_ocr,
                                "confidence": selected_person.get("ocr_confidence"),
                                "evidence_text": selected_person.get("evidence_text"),
                                "hypotheses": selected_person.get("ranked_ocr_hypotheses") or [],
                            },
                            "record_ocr": selected_draft.get("source_record_ocr_text", ""),
                            "field_ocr": selected_draft.get("evidence", {}),
                        }, expanded=False)
                    with st.expander("해당 인물의 원문 OCR 참고", expanded=True):
                        st.caption(
                            f"출처 행: {selected_person.get('source_row_id') or '정보 없음'} · "
                            "아래 내용은 해당 행 전체 OCR이며, 이 인물의 정보만 분리된 결과는 아닙니다."
                        )
                        st.text_area(
                            "행 전체 OCR 텍스트", value=row_ocr_text,
                            height=180, disabled=True,
                            key=f"row_ocr_{selected_person_id}",
                        )

                    # Information OCR is prepared automatically for the selected person.
                    # Persisted/manual values always take precedence over these draft values.
                    populated_draft_fields = [
                        field for field, value in draft_values.items() if value
                    ]
                    if populated_draft_fields:
                        st.info(
                            "OCR 정보 초안을 자동으로 입력했습니다. 원본 이미지와 대조한 뒤 저장하세요. "
                            "아직 검수 전인 값입니다."
                        )
                    else:
                        st.caption("이 인물에서 자동 추출할 수 있는 정보가 없습니다. 원문 OCR 영역을 직접 확인해 주세요.")

                    if auto_draft:
                        with st.expander("OCR 자동 추출 근거 및 원문 영역", expanded=True):
                            st.caption(
                                "OCR 텍스트와 위치 규칙으로 만든 미검수 초안입니다. "
                                "날짜 변환이나 사실관계 판단은 하지 않으므로 원본 이미지와 대조해야 합니다."
                            )
                            if auto_draft.get("source_record_ocr_text"):
                                st.text_area(
                                    "이 인물에게 배정된 OCR 기록 영역",
                                    value=auto_draft.get("source_record_ocr_text", ""),
                                    height=180, disabled=True,
                                    key=f"person_section_ocr_{selected_person_id}",
                                )
                            evidence_map = auto_draft.get("evidence", {})
                            for field, snippets in evidence_map.items():
                                label = {
                                    "birth_text": "출생", "death_text": "사망",
                                    "office_title": "관직", "spouse_text": "배우자",
                                    "burial_text": "묘소", "courtesy_name_hanja": "자(字)",
                                    "pen_name_hanja": "호(號)", "biography_text": "기록 전체",
                                }.get(field, field)
                                st.caption(f"{label} 근거: " + " · ".join(snippets))
                            if auto_draft.get("message"):
                                st.caption(auto_draft["message"])

                    with st.form(f"person_form_{selected_person_id}"):
                        corrected_name = st.text_input("검수한 한자 이름 (子/女 제외)", value=current_transcription)
                        marker_options = {"표식 없음": None, "子 (아들)": "子", "女 (딸)": "女"}
                        current_marker = person_value("sex_marker") or inferred_marker
                        marker_reverse = {value: label for label, value in marker_options.items()}
                        marker_label = st.selectbox(
                            "자녀 표식 / 성별", list(marker_options),
                            index=list(marker_options).index(marker_reverse.get(current_marker, "표식 없음")),
                        )
                        st.markdown("**인물의 추가 정보**")
                        gen_col, courtesy_col, pen_col = st.columns(3)
                        generation_input = gen_col.text_input(
                            "세대", value=person_value("generation_number"), placeholder="예: 3"
                        )
                        courtesy_name = courtesy_col.text_input(
                            "자(字)", value=person_value("courtesy_name_hanja")
                        )
                        pen_name = pen_col.text_input(
                            "호(號)", value=person_value("pen_name_hanja")
                        )
                        birth_col, death_col = st.columns(2)
                        birth_text = birth_col.text_input(
                            "출생 정보", value=person_value("birth_text"),
                            placeholder="예: 壬子年三月生"
                        )
                        death_text = death_col.text_input(
                            "사망 정보", value=person_value("death_text"),
                            placeholder="예: 庚寅年卒"
                        )
                        office_title = st.text_input(
                            "관직·품계·봉호", value=person_value("office_title")
                        )
                        existing_spouses = person_value("spouses", None)
                        if not isinstance(existing_spouses, list):
                            existing_spouses = []
                        if not existing_spouses:
                            legacy_spouse = person_value("spouse_text")
                            # OCR alone cannot reliably distinguish wife from concubine;
                            # keep the extracted text unclassified until a reviewer decides.
                            existing_spouses = ([{"type": "other", "name_and_record": legacy_spouse,
                                                  "notes": "OCR 초안 - 부인/첩 구분 검수 필요"}]
                                                if legacy_spouse else [])
                        spouse_rows = []
                        for spouse in existing_spouses:
                            kind = spouse.get("type", "wife")
                            spouse_rows.append({
                                "구분": {"wife": "부인", "concubine": "첩", "other": "기타"}.get(kind, "부인"),
                                "이름·본관·원문": spouse.get("name_and_record", spouse.get("name_text", "")),
                                "비고": spouse.get("notes", ""),
                            })
                        spouse_df = pd.DataFrame(spouse_rows, columns=["구분", "이름·본관·원문", "비고"])
                        st.caption("부인과 첩을 여러 명 등록할 수 있습니다. 행을 추가해 각각 입력하세요.")
                        spouses_editor = st.data_editor(
                            spouse_df, key=f"spouses_editor_{selected_person_id}",
                            num_rows="dynamic", hide_index=True, use_container_width=True,
                            column_config={
                                "구분": st.column_config.SelectboxColumn(
                                    "구분", options=["부인", "첩", "기타"], required=True,
                                ),
                                "이름·본관·원문": st.column_config.TextColumn("이름·본관·원문"),
                                "비고": st.column_config.TextColumn("비고"),
                            },
                        )
                        burial_text = st.text_input(
                            "묘소·장지", value=person_value("burial_text")
                        )
                        biography_text = st.text_area(
                            "인물 기록 원문 / 추가 판독", value=person_value("biography_text"),
                            height=150,
                            placeholder="이 인물에 해당하는 관직, 생몰, 배우자, 행적 등의 원문을 옮겨 적으세요."
                        )
                        notes = st.text_area(
                            "기타 메모", value=person_value("notes"), height=80
                        )
                        mark_confirmed = st.checkbox(
                            "이 인명의 판독을 확인했습니다.",
                            value=effective_person_status(selected_person, state) == "confirmed",
                        )
                        mark_information_reviewed = st.checkbox(
                            "추가 인물 정보(OCR 초안 포함)를 원본과 대조했습니다.",
                            value=person_value("information_review_status") == "confirmed",
                        )
                        if st.form_submit_button("인명 및 인물 정보 저장", use_container_width=True):
                            try:
                                generation_number = parse_optional_generation(generation_input)
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                updated_person = dict(update)
                                cleaned_name, marker_from_name, inferred_from_name = strip_name_marker(corrected_name)
                                selected_marker = (
                                    marker_from_name if marker_label == "표식 없음" and marker_from_name
                                    else marker_options[marker_label]
                                )
                                spouse_type_map = {"부인": "wife", "첩": "concubine", "기타": "other"}
                                reviewed_spouses = []
                                for row in spouses_editor.to_dict(orient="records"):
                                    raw_text_value = row.get("이름·본관·원문")
                                    raw_notes_value = row.get("비고")
                                    text_value = "" if pd.isna(raw_text_value) else str(raw_text_value).strip()
                                    notes_value = "" if pd.isna(raw_notes_value) else str(raw_notes_value).strip()
                                    if not text_value and not notes_value:
                                        continue
                                    raw_type_value = row.get("구분")
                                    type_value = "부인" if pd.isna(raw_type_value) or not raw_type_value else str(raw_type_value)
                                    reviewed_spouses.append({
                                        "type": spouse_type_map.get(type_value, "wife"),
                                        "name_and_record": text_value,
                                        "notes": notes_value,
                                        "review_status": "needs_review" if not mark_information_reviewed else "confirmed",
                                    })
                                legacy_spouse_text = " / ".join(
                                    ("첩: " if item["type"] == "concubine" else "부인: " if item["type"] == "wife" else "기타: ") + item["name_and_record"]
                                    for item in reviewed_spouses if item.get("name_and_record")
                                ) or None
                                updated_person.update({
                                    "transcribed_name_hanja": cleaned_name or None,
                                    "sex_marker": selected_marker,
                                    "gender": {"子": "male", "女": "female"}.get(selected_marker),
                                    "generation_number": generation_number,
                                    "courtesy_name_hanja": courtesy_name.strip() or None,
                                    "pen_name_hanja": pen_name.strip() or None,
                                    "birth_text": birth_text.strip() or None,
                                    "death_text": death_text.strip() or None,
                                    "office_title": office_title.strip() or None,
                                    "spouses": reviewed_spouses,
                                    "spouse_text": legacy_spouse_text,
                                    "burial_text": burial_text.strip() or None,
                                    "biography_text": biography_text.strip() or None,
                                    "notes": notes.strip() or None,
                                    "information_review_status": "confirmed" if mark_information_reviewed else "needs_review",
                                    "source_record_ocr_text": (auto_draft or {}).get("source_record_ocr_text") or person_value("source_record_ocr_text") or None,
                                    "auto_extraction_draft": auto_draft,
                                    "review_status": "confirmed" if mark_confirmed else "needs_review",
                                    "transcription_status": "manually_verified" if mark_confirmed else "pending_manual_verification",
                                })
                                state["people_updates"][selected_person_id] = updated_person
                                save_state(root, state, all_people, all_relationships, page_results)
                                st.success("인명과 인물 정보를 저장했습니다.")
                                st.rerun()

            with relation_tab:
                st.subheader("선택 인물의 관계 및 관계 후보")
                st.caption("관계 목록의 1, 2, 3… 번호는 왼쪽 원본 이미지 위에 표시된 인물 번호와 같습니다.")
                # The currently selected person is shared with the person-review tab
                # and image click selection. Show all parent/child edges touching it.
                focus_person_id = st.session_state.get("selected_person_id")
                if focus_person_id not in page_person_lookup:
                    focus_person_id = None
                if focus_person_id:
                    focus_label = format_person_reference(
                        focus_person_id, page_person_lookup, page_person_numbers, page_name_getter
                    )
                    st.info(f"관계 검수 기준 인물: **{focus_label}** · 이 인물이 부모이거나 자녀인 관계를 표시합니다.")
                    focused_rels = filter_relationships_for_person(page_rels, focus_person_id)
                    # Show each direction explicitly to make both the person's parents
                    # and children visible before selecting a candidate to edit.
                    as_parent = [r for r in focused_rels if r.get("parent_candidate_id") == focus_person_id]
                    as_child = [r for r in focused_rels if r.get("child_candidate_id") == focus_person_id]
                    if as_parent:
                        st.markdown("**이 인물이 부모인 관계 (자녀)**")
                        for rel in as_parent:
                            child_label = format_person_reference(
                                rel.get("child_candidate_id"), page_person_lookup, page_person_numbers, page_name_getter
                            )
                            st.write(f"{rel.get('review_status', 'needs_review')} · {focus_label} → {child_label}")
                    if as_child:
                        st.markdown("**이 인물이 자녀인 관계 (부모)**")
                        for rel in as_child:
                            parent_label = format_person_reference(
                                rel.get("parent_candidate_id"), page_person_lookup, page_person_numbers, page_name_getter
                            )
                            st.write(f"{rel.get('review_status', 'needs_review')} · {parent_label} → {focus_label}")
                    if not focused_rels:
                        st.caption("선택한 인물과 연결된 관계 후보나 저장된 관계가 없습니다.")
                    scope_key = f"relationship_scope_{selected_page_name}"
                    focus_key = f"relationship_focus_{selected_page_name}"
                    if st.session_state.get(focus_key) != focus_person_id:
                        # Whenever the reviewer chooses another person, default back
                        # to that person's relationships rather than leaving the old
                        # page-wide or previous-person filter active.
                        st.session_state[scope_key] = "선택 인물 관련 관계"
                        st.session_state[focus_key] = focus_person_id
                    relationship_scope = st.radio(
                        "관계 목록 범위", ["선택 인물 관련 관계", "페이지 전체 관계"],
                        horizontal=True, index=0, key=scope_key,
                    )
                    visible_rels = focused_rels if relationship_scope == "선택 인물 관련 관계" else page_rels
                else:
                    st.caption("인명 검수 탭 또는 왼쪽 이미지에서 인물을 선택하면 해당 인물의 부모·자녀 관계만 모아 볼 수 있습니다.")
                    visible_rels = page_rels

                if not visible_rels:
                    st.caption("표시할 관계 후보가 없습니다.")
                else:
                    rel_labels = {
                        relationship_key(r): format_relationship_label(
                            r, page_person_lookup, page_person_numbers, page_name_getter
                        )
                        for r in visible_rels
                    }
                    rel_select_key = f"rel_select_{selected_page_name}"
                    if st.session_state.get(rel_select_key) not in rel_labels:
                        st.session_state[rel_select_key] = next(iter(rel_labels))
                    selected_rel_key = st.selectbox(
                        "검수할 관계", list(rel_labels), format_func=lambda value: rel_labels[value],
                        key=rel_select_key,
                    )
                    selected_rel = next(r for r in visible_rels if relationship_key(r) == selected_rel_key)
                    if page_person_lookup:
                        parent_default = selected_rel.get("parent_candidate_id") if selected_rel.get("parent_candidate_id") in page_person_lookup else None
                        child_default = selected_rel.get("child_candidate_id") if selected_rel.get("child_candidate_id") in page_person_lookup else None
                        person_ids = list(page_person_lookup)
                        with st.form(f"relation_form_{selected_rel_key}"):
                            parent_idx = person_ids.index(parent_default) if parent_default in person_ids else 0
                            child_idx = person_ids.index(child_default) if child_default in person_ids else 0
                            parent_choice = st.selectbox(
                                "부모 인물", person_ids, index=parent_idx,
                                format_func=lambda pid: format_person_reference(
                                    pid, page_person_lookup, page_person_numbers, page_name_getter
                                ),
                            )
                            child_choice = st.selectbox(
                                "자녀 인물", person_ids, index=child_idx,
                                format_func=lambda pid: format_person_reference(
                                    pid, page_person_lookup, page_person_numbers, page_name_getter
                                ),
                            )
                            approve_col, reject_col = st.columns(2)
                            approve_rel = approve_col.form_submit_button("승인 / 저장", use_container_width=True)
                            reject_rel = reject_col.form_submit_button("거절", use_container_width=True)
                            if approve_rel:
                                if parent_choice == child_choice:
                                    st.error("부모와 자녀가 같은 인물일 수 없습니다.")
                                elif would_create_cycle(parent_choice, child_choice, relationships):
                                    st.error("확인된 관계에 순환이 생깁니다. 부모·자녀 방향을 확인하세요.")
                                else:
                                    state["relationship_updates"][selected_rel_key] = {
                                        "parent_candidate_id": parent_choice,
                                        "parent_name_hanja_candidate": effective_name(page_person_lookup[parent_choice], state),
                                        "child_candidate_id": child_choice,
                                        "child_name_hanja_candidate": effective_name(page_person_lookup[child_choice], state),
                                        "review_status": "confirmed", "relationship_basis": "manually_reviewed_candidate",
                                        "warning": None,
                                    }
                                    save_state(root, state, all_people, all_relationships, page_results)
                                    st.success("관계를 승인했습니다.")
                                    st.rerun()
                            if reject_rel:
                                state["relationship_updates"][selected_rel_key] = {"review_status": "rejected"}
                                save_state(root, state, all_people, all_relationships, page_results)
                                st.success("관계 후보를 거절했습니다.")
                                st.rerun()

                confirmed_visible_rels = [r for r in visible_rels if r.get("review_status") == "confirmed"]
                if confirmed_visible_rels:
                    st.divider()
                    st.markdown("**표시 중인 인물의 저장된 관계 연결 취소**")
                    confirmed_options = {
                        relationship_key(r): format_relationship_label(
                            r, page_person_lookup, page_person_numbers, page_name_getter
                        )
                        for r in confirmed_visible_rels
                    }
                    cancel_select_key = f"cancel_rel_{selected_page_name}"
                    if st.session_state.get(cancel_select_key) not in confirmed_options:
                        st.session_state[cancel_select_key] = next(iter(confirmed_options))
                    cancel_rel_key = st.selectbox(
                        "취소할 연결", list(confirmed_options), format_func=lambda value: confirmed_options[value],
                        key=cancel_select_key,
                    )
                    if st.button("선택한 연결 취소", key=f"cancel_rel_button_{selected_page_name}", use_container_width=True):
                        rel_to_cancel = next(r for r in confirmed_visible_rels if relationship_key(r) == cancel_rel_key)
                        if rel_to_cancel.get("relationship_basis") == "manual_visual_link":
                            state["manual_relationships"] = [
                                r for r in state["manual_relationships"]
                                if relationship_key(r) != cancel_rel_key
                            ]
                        else:
                            state["relationship_updates"][cancel_rel_key] = {"review_status": "rejected"}
                        save_state(root, state, all_people, all_relationships, page_results)
                        st.session_state["last_click_message"] = "선택한 관계 연결을 취소했습니다."
                        st.rerun()

                pending_count = sum(r.get("review_status") == "needs_review" for r in visible_rels)
                st.caption(f"현재 표시된 관계 중 검토 대기: {pending_count}개")
    # Less-critical counts are kept below the review workspace.
    st.divider()
    st.subheader("페이지 검수 현황")
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    summary_col1.metric("인물 후보", len(page_people))
    summary_col2.metric("인명 확인 완료", f"{confirmed_people}/{len(page_people)}")
    summary_col3.metric("관계 후보", len(page_rels))
    summary_col4.metric("관계 확인 완료", confirmed_rels)

    st.divider()
    st.subheader("검수 결과 내보내기")
    export_signature_payload = {
        "state": state,
        "registry_path": str(registry_path),
        "registry": registry_data,
        "people_count": len(all_people),
        "relationship_count": len(all_relationships),
    }
    export_signature = hashlib.sha256(
        json.dumps(export_signature_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    exports_exist = (root / "reviewed_people.json").exists() and (root / "reviewed_relationships.json").exists()
    if (st.session_state.get("review_export_signature") != export_signature) or not exports_exist:
        people_export, rel_export = build_review_data(
            root, all_people, all_relationships, state, page_results
        )
        write_exports(root, people_export, rel_export)
        registry_data = build_person_registry(people_export, registry_data)
        try:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(json.dumps(registry_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            st.error(f"인물 레지스트리를 저장하지 못했습니다: {registry_path} · {exc}")
        # Persist edition/source-location metadata and permanent person UID mappings.
        (root / "review_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        st.session_state["review_export_signature"] = export_signature
    else:
        people_export = read_json(root / "reviewed_people.json", people)
        rel_export = read_json(root / "reviewed_relationships.json", relationships)
    export_col1, export_col2 = st.columns(2)
    with export_col1:
        st.download_button("검수 인물 JSON", json.dumps(people_export, ensure_ascii=False, indent=2),
                           file_name="reviewed_people.json", mime="application/json")
        st.download_button("검수 인물 CSV", (root / "reviewed_people.csv").read_bytes(),
                           file_name="reviewed_people.csv", mime="text/csv")
    with export_col2:
        st.download_button("검수 관계 JSON", json.dumps(rel_export, ensure_ascii=False, indent=2),
                           file_name="reviewed_relationships.json", mime="application/json")
        st.download_button("검수 관계 CSV", (root / "reviewed_relationships.csv").read_bytes(),
                           file_name="reviewed_relationships.csv", mime="text/csv")
    st.download_button(
        "인물 ID 레지스트리 JSON", json.dumps(registry_data, ensure_ascii=False, indent=2),
        file_name="person_registry.json", mime="application/json",
    )

    st.caption(f"검수 상태는 `{root / 'review_state.json'}`에 저장됩니다. 사람의 고유 ID는 위치와 무관한 UUID이며, 판본·쪽·열·이미지 좌표는 `source_occurrences`에 출처 정보로 기록됩니다. 공용 인물 레지스트리: `{registry_path}`")


if __name__ == "__main__":
    main()
