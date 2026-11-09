#!/usr/bin/env python3
"""Local Streamlit review UI for Jokbo OCR v6 outputs."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

from person_info_extractor import extract_person_info_draft
from review_helpers import (
    person_number_map, format_person_reference, filter_relationships_for_person,
    format_relationship_label,
)

st.set_page_config(page_title="Jokbo OCR 검수", page_icon="📜", layout="wide")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def find_output_root(raw_path: str) -> Path | None:
    path = Path(raw_path).expanduser().resolve()
    candidates = [path, path / "paddleocr", path / "tesseract"]
    for candidate in candidates:
        if (candidate / "ocr_results.json").exists():
            return candidate
    return None


def effective_name(person: dict[str, Any], state: dict[str, Any]) -> str:
    update = state.get("people_updates", {}).get(person.get("person_id"), {})
    return (update.get("transcribed_name_hanja")
            or person.get("transcribed_name_hanja")
            or person.get("name_hanja_candidate") or "(이름 미인식)")


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
            "person_id", "source_page", "name_hanja_candidate", "transcribed_name_hanja",
            "review_status", "generation_number", "courtesy_name_hanja", "pen_name_hanja",
            "birth_text", "death_text", "office_title", "spouse_text", "burial_text",
            "biography_text", "notes", "information_review_status", "source_record_ocr_text",
            "bbox", "image_file", "ocr_confidence",
        ], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(people)
    with (root / "reviewed_relationships.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "relationship_id", "source_page", "type", "parent_candidate_id",
            "parent_name_hanja_candidate", "child_candidate_id", "child_name_hanja_candidate",
            "relationship_basis", "review_status", "warning",
        ], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(relationships)


def build_review_data(root: Path, base_people: list[dict[str, Any]],
                      base_relationships: list[dict[str, Any]], state: dict[str, Any]):
    people = []
    for raw in base_people:
        person = dict(raw)
        update = state.get("people_updates", {}).get(person.get("person_id"), {})
        person.update(update)
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
        if child:
            rel["child_name_hanja_candidate"] = effective_name(child, state)
    return people, rels


def get_page_image(page_result: dict[str, Any], page_dir: Path) -> tuple[np.ndarray, tuple[int, int], str]:
    """Return image, coordinate offset (x,y), and source label.

    Person bboxes are always in original-page coordinates. If the original
    scan is unavailable, table_roi.jpg is used and the stored ROI offset is
    subtracted while drawing / added after clicks.
    """
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


def fit_display(image: np.ndarray, max_width: int = 950, max_height: int = 720) -> tuple[Image.Image, float]:
    """Fit the complete page into a bounded viewport while preserving coordinates."""
    h, w = image.shape[:2]
    scale = min(1.0, max_width / max(1, w), max_height / max(1, h))
    out_w, out_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(image, (out_w, out_h), interpolation=cv2.INTER_AREA) if scale < 1 else image.copy()
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb), scale


def draw_overlay(image: np.ndarray, offset: tuple[int, int], people: list[dict[str, Any]],
                 relationships: list[dict[str, Any]], state: dict[str, Any],
                 selected_id: str | None = None, pending_parent_id: str | None = None,
                 active_parent_id: str | None = None,
                 max_width: int = 950, max_height: int = 720) -> Image.Image:
    base, scale = fit_display(image, max_width, max_height)
    draw = ImageDraw.Draw(base, "RGBA")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 15)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    ox, oy = offset
    person_map = {p.get("person_id"): p for p in people}

    # Confirmed links are always visible. When a parent is active, also show
    # its unreviewed candidate links, using a different color to avoid implying
    # that those candidate relationships are already factual.
    for rel in relationships:
        status = rel.get("review_status")
        parent_id = rel.get("parent_candidate_id")
        if status == "rejected":
            continue
        active_parent_edge = bool(active_parent_id and parent_id == active_parent_id)
        if status != "confirmed" and not active_parent_edge:
            continue
        child_id = rel.get("child_candidate_id")
        parent = person_map.get(parent_id)
        child = person_map.get(child_id)
        if not parent or not child:
            continue
        pb, cb = parent.get("bbox") or {}, child.get("bbox") or {}
        pc = ((float(pb.get("x", 0)) + float(pb.get("width", 0)) / 2 - ox) * scale,
              (float(pb.get("y", 0)) + float(pb.get("height", 0)) / 2 - oy) * scale)
        cc = ((float(cb.get("x", 0)) + float(cb.get("width", 0)) / 2 - ox) * scale,
              (float(cb.get("y", 0)) + float(cb.get("height", 0)) / 2 - oy) * scale)
        active_edge = active_parent_edge and status == "confirmed"
        active_candidate = active_parent_edge and status != "confirmed"
        line_color = ((37, 99, 235, 245) if active_edge else
                      (217, 119, 6, 235) if active_candidate else (22, 163, 74, 190))
        line_width = 6 if active_edge else (3 if active_candidate else 3)
        draw.line([pc, cc], fill=line_color, width=line_width)
        if active_edge:
            dx, dy = cc[0] - pc[0], cc[1] - pc[1]
            length = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux
            base_x, base_y = cc[0] - ux * 13, cc[1] - uy * 13
            draw.polygon([cc, (base_x + px * 6, base_y + py * 6),
                          (base_x - px * 6, base_y - py * 6)],
                         fill=(37, 99, 235, 245))

    for index, person in enumerate(people, start=1):
        bbox = person.get("bbox") or {}
        x0 = (float(bbox.get("x", 0)) - ox) * scale
        y0 = (float(bbox.get("y", 0)) - oy) * scale
        x1 = (float(bbox.get("x", 0)) + float(bbox.get("width", 0)) - ox) * scale
        y1 = (float(bbox.get("y", 0)) + float(bbox.get("height", 0)) - oy) * scale
        pid = person.get("person_id")
        status = effective_person_status(person, state)
        color = (245, 158, 11, 230) if status != "confirmed" else (22, 163, 74, 230)
        width = 4 if pid == selected_id or pid == pending_parent_id else 2
        if pid == selected_id:
            color = (37, 99, 235, 240)
        elif pid == pending_parent_id:
            color = (147, 51, 234, 245)
        draw.rectangle((x0, y0, x1, y1), outline=color, width=width)
        label = f"{index}. {effective_name(person, state)}"
        label_top = max(0, y0 - 21)
        text_box = draw.textbbox((x0, label_top), label, font=small_font)
        draw.rectangle(text_box, fill=(15, 23, 42, 190))
        draw.text((x0, label_top), label, fill=(255, 255, 255, 255), font=small_font)

    return base


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
               base_relationships: list[dict[str, Any]]) -> None:
    state["updated_at"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
    (root / "review_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    people, rels = build_review_data(root, base_people, base_relationships, state)
    write_exports(root, people, rels)


def main() -> None:
    st.title("족보 OCR 검수 v6.4")
    st.caption("기존 부모·자녀 연결선을 확인하고, 부모 한 명에게 여러 자녀를 연결할 수 있습니다. 인물 정보는 저장된 OCR 텍스트에서 검수용 초안을 만들 수 있습니다.")

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
    people, relationships = build_review_data(root, all_people, all_relationships, state)

    page_names = [item.get("source_page", Path(item.get("source_image", "page")).name) for item in page_results]
    page_col, spacer_col = st.columns([1, 2])
    with page_col:
        selected_page_name = st.selectbox("검수할 페이지", page_names)
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
                save_state(root, state, all_people, all_relationships)
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
    # Bound both dimensions: a portrait scan is shown in full, instead of extending far below the fold.
    image_max_width = 1050
    # Keep the scan's height compatible with the right-hand fixed-height review pane.
    effective_image_height = min(max_height, max(320, int(detail_panel_height) - 110))
    display_image, display_scale = fit_display(image, image_max_width, effective_image_height)
    selected_id = st.session_state.get("selected_person_id")
    pending_parent_id = st.session_state.get("pending_parent_id")
    overlay = draw_overlay(
        image, offset, page_people, page_rels, state,
        selected_id=selected_id, pending_parent_id=pending_parent_id,
        active_parent_id=pending_parent_id if click_mode == "부모 → 자녀 연결" else None,
        max_width=image_max_width, max_height=effective_image_height,
    )

    image_col, detail_col = st.columns([1.8, 1], gap="large")
    with image_col:
        st.subheader(f"원본 페이지 · {selected_page_name}")
        st.caption(f"{image_label} · 페이지 전체 보기 · 인물 박스를 직접 클릭할 수 있습니다. (표시 높이 최대 {effective_image_height}px)")
        click_value = streamlit_image_coordinates(
            overlay, width=overlay.width,
            key=f"page_click_{selected_page_name}_{click_mode}", cursor="crosshair",
        )
        if click_value and isinstance(click_value, dict) and "x" in click_value and "y" in click_value:
            click_event = (click_value.get("timestamp"), click_value.get("x"), click_value.get("y"))
            event_key = f"last_click_{selected_page_name}_{click_mode}"
            if st.session_state.get(event_key) != click_event:
                st.session_state[event_key] = click_event
                # Coordinates returned by the component refer to the resized image.
                x_img = float(click_value["x"]) / max(display_scale, 1e-6)
                y_img = float(click_value["y"]) / max(display_scale, 1e-6)
                person = find_person_at_click(page_people, x_img, y_img, offset)
                if person is None:
                    st.session_state["last_click_message"] = "인물 박스 안쪽을 클릭해 주세요."
                    st.rerun()
                elif click_mode == "인물 선택 / 이름 검수":
                    st.session_state["selected_person_id"] = person["person_id"]
                    st.session_state[f"person_select_{selected_page_name}"] = person["person_id"]
                    st.session_state["last_click_message"] = f"선택됨: {effective_name(person, state)}"
                    st.rerun()
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
                    save_state(root, state, all_people, all_relationships)
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
            st.markdown("🟠 미검수 인물 · 🟢 확인된 인물 · 🔵 선택된 인물 · 🟣 연결할 부모 · 🟢 일반 확정 관계 · 🔵 선택 부모의 확정 관계 · 🟠 선택 부모의 검토 후보")

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

                    def person_value(field: str, fallback: Any = "") -> str:
                        value = update.get(field, selected_person.get(field, fallback))
                        return "" if value is None else str(value)

                    current_transcription = (
                        person_value("transcribed_name_hanja")
                        or person_value("name_hanja_candidate")
                    )
                    row_ocr_text = get_person_row_text(page_result, selected_person)
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

                    if st.button(
                        "OCR로 인물 정보 초안 채우기",
                        key=f"extract_person_info_{selected_person_id}",
                        use_container_width=True,
                        help="새 OCR 추론을 실행하지 않고 저장된 OCR 열과 좌표를 이용해 생몰·관직·배우자·묘소 정보를 추출합니다.",
                    ):
                        draft = extract_person_info_draft(selected_person, page_result, page_people)
                        current_update = dict(state["people_updates"].get(selected_person_id, {}))
                        populated_fields = []
                        for field, value in draft.get("draft_values", {}).items():
                            if value and not current_update.get(field) and not selected_person.get(field):
                                current_update[field] = value
                                populated_fields.append(field)
                        current_update["auto_extraction_draft"] = draft
                        current_update["information_review_status"] = "needs_review"
                        state["people_updates"][selected_person_id] = current_update
                        save_state(root, state, all_people, all_relationships)
                        if populated_fields:
                            st.session_state["last_click_message"] = (
                                "OCR 초안을 추가했습니다: " + ", ".join(populated_fields)
                                + ". 기존에 입력된 항목은 덮어쓰지 않았습니다."
                            )
                        else:
                            st.session_state["last_click_message"] = draft.get("message", "추출을 마쳤습니다.")
                        st.rerun()

                    update = state["people_updates"].get(selected_person_id, {})
                    auto_draft = update.get("auto_extraction_draft")
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
                        corrected_name = st.text_input("검수한 한자 이름", value=current_transcription)
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
                        spouse_text = st.text_input(
                            "배우자·배우자 본관", value=person_value("spouse_text")
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
                                updated_person.update({
                                    "transcribed_name_hanja": corrected_name.strip() or None,
                                    "generation_number": generation_number,
                                    "courtesy_name_hanja": courtesy_name.strip() or None,
                                    "pen_name_hanja": pen_name.strip() or None,
                                    "birth_text": birth_text.strip() or None,
                                    "death_text": death_text.strip() or None,
                                    "office_title": office_title.strip() or None,
                                    "spouse_text": spouse_text.strip() or None,
                                    "burial_text": burial_text.strip() or None,
                                    "biography_text": biography_text.strip() or None,
                                    "notes": notes.strip() or None,
                                    "information_review_status": "confirmed" if mark_information_reviewed else "needs_review",
                                    "source_record_ocr_text": (auto_draft or {}).get("source_record_ocr_text") or person_value("source_record_ocr_text") or None,
                                    "review_status": "confirmed" if mark_confirmed else "needs_review",
                                    "transcription_status": "manually_verified" if mark_confirmed else "pending_manual_verification",
                                })
                                state["people_updates"][selected_person_id] = updated_person
                                save_state(root, state, all_people, all_relationships)
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
                                    save_state(root, state, all_people, all_relationships)
                                    st.success("관계를 승인했습니다.")
                                    st.rerun()
                            if reject_rel:
                                state["relationship_updates"][selected_rel_key] = {"review_status": "rejected"}
                                save_state(root, state, all_people, all_relationships)
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
                        save_state(root, state, all_people, all_relationships)
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
    people_export, rel_export = build_review_data(root, all_people, all_relationships, state)
    write_exports(root, people_export, rel_export)
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

    st.caption(f"검수 상태는 `{root / 'review_state.json'}`에 자동 저장됩니다. 원본 OCR 후보 파일은 덮어쓰지 않습니다. 인물별 추가 정보와 OCR 자동 추출 근거, 정보 검수 상태도 함께 저장됩니다.")


if __name__ == "__main__":
    main()
