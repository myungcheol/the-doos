#!/usr/bin/env python3
"""Qt desktop review interface for existing Jokbo OCR output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPen, QPixmap, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGraphicsScene,
    QGridLayout,
    QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from person_data_model import ensure_person_uid, strip_name_marker
from person_info_extractor import extract_person_info_draft, get_field_source_columns
from review_extensions import (merge_review_sources, page_name, page_sort_key, orphan_regions,
                               previous_row_people, make_continuation, recover_name_candidates)

# OpenCV's Linux wheel may replace these variables during import, directing Qt
# at cv2's plugin directory instead of PySide6's input-method plugins.
_qt_environment = {key: os.environ.get(key) for key in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR")}
from review_app import (effective_name, effective_relationship,
                        find_output_root, get_page_image, parse_optional_generation,
                        relationship_key, save_state, would_create_cycle)
import cv2


def restore_qt_environment(previous, environment, cv2_dir):
    """Undo only OpenCV's Qt overrides, preserving explicit user settings."""
    qt_dir = Path(cv2_dir) / "qt"
    for key, overridden in (("QT_QPA_PLATFORM_PLUGIN_PATH", qt_dir / "plugins"),
                            ("QT_QPA_FONTDIR", qt_dir / "fonts")):
        if environment.get(key) != str(overridden):
            continue
        if previous.get(key) is None:
            environment.pop(key, None)
        else:
            environment[key] = previous[key]


restore_qt_environment(_qt_environment, os.environ, Path(cv2.__file__).resolve().parent)


STYLE = """
QWidget { background: #182230; color: #e5edf7; font-size: 13px; }
QLabel { background: transparent; }
QWidget#header { background: #202e40; border-radius: 8px; }
QWidget#panel { background: #202d3c; border: 1px solid #33465b; border-radius: 8px; }
QLabel#title { font-size: 21px; font-weight: bold; color: #f5f8fc; }
QLabel#subtitle, QLabel#muted { color: #acbdd0; }
QLabel#section { font-size: 15px; font-weight: bold; color: #f4f7fb; }
QLabel#evidence { background: #26384a; border: 1px solid #3a5168; border-radius: 6px; padding: 8px; color: #e5edf7; }
QPushButton { background: #30465e; border: 1px solid #49647f; border-radius: 5px; padding: 7px 11px; }
QPushButton:hover { background: #405d7a; }
QPushButton:pressed { background: #243a51; }
QPushButton#primary { background: #2166a6; border-color: #408ccc; font-weight: bold; }
QPushButton#primary:hover { background: #2c7bbd; }
QPushButton:checked { background: #2166a6; border-color: #82b7e3; color: white; }
QLineEdit, QTextEdit, QComboBox, QListWidget { background: #101a27; color: #eef4fb; border: 1px solid #3b526a; border-radius: 5px; padding: 6px; selection-background-color: #315f87; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QListWidget:focus { border: 1px solid #66a9dc; }
QListWidget::item { padding: 7px; border-bottom: 1px solid #273a4d; }
QListWidget::item:selected { background: #315f87; color: white; }
QComboBox QAbstractItemView { background: #172638; color: #eef4fb; selection-background-color: #315f87; }
QTabWidget::pane { border: 1px solid #3b526a; border-radius: 5px; }
QTabBar::tab { background: #24374a; color: #b7c8da; padding: 8px 18px; margin-right: 3px; border-radius: 4px; }
QTabBar::tab:selected { background: #34536e; color: white; }
QScrollArea { border: 0; }
QGraphicsView { background: #101722; border: 1px solid #3b526a; border-radius: 5px; }
QToolTip { background: #f4f7fc; color: #142234; border: 1px solid #8999aa; padding: 5px; }
QStatusBar { color: #b9c9d9; }
"""


def configure_application(app):
    """Use the bundled OFL font so Korean and Hanja do not depend on host fonts."""
    app.setStyle("Fusion")
    font_path = Path(__file__).resolve().parent / "assets/fonts/NotoSansCJKkr-Regular.otf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if families:
        app.setFont(QFont(families[0], 10))
    app.setStyleSheet(STYLE)
    return bool(families)


def file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def discover_page_outputs(root, pages, people):
    """Find sibling per-page OCR results and their scans without changing review state."""
    known_pages = {page_name(page) for page in pages}
    known_ids = {person.get("person_id") for person in people}
    templates = [Path(page["source_image"]) for page in pages if page.get("source_image")]
    suffixes = list(dict.fromkeys(template.suffix for template in templates if template.suffix))
    entries, warnings = [], []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder / "rows.json").is_file():
            continue
        try:
            rows = read_json(folder / "rows.json", None)
            candidates = read_json(folder / "people_candidates.json", [])
            relations = read_json(folder / "relationship_candidates.json", [])
            if not isinstance(rows, list) or not rows or not isinstance(candidates, list) or not isinstance(relations, list):
                raise ValueError("OCR JSON 배열 형식 오류")
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
            if any(rel.get("source_page") != name for rel in relations):
                raise ValueError("관계 후보의 원본 페이지가 다릅니다")
            page = {"source_page": name, "source_image": str(source.resolve()),
                    "page_output_dir": str(folder.resolve()), "rows": rows}
            entries.append({"page_result": page, "people": candidates, "relationships": relations})
            known_pages.add(name)
            known_ids.update(person.get("person_id") for person in candidates)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{folder.name}: {exc}")
    return entries, warnings


class OcrFocusSelector(QWidget):
    """Always-visible choices: avoids platform-dependent popup behavior."""
    currentIndexChanged = Signal(int)
    choices = [("전체 기록", "all"), ("이름", "name"), ("출생", "birth_text"),
               ("사망", "death_text"), ("관직", "office_title"), ("배우자", "spouse_text"),
               ("묘소", "burial_text"), ("자", "courtesy_name_hanja"), ("호", "pen_name_hanja")]

    def __init__(self):
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.group = QButtonGroup(self)
        for index, (title, _) in enumerate(self.choices):
            button = QPushButton(title)
            button.setCheckable(True)
            self.group.addButton(button, index)
            layout.addWidget(button, index // 3, index % 3)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.currentIndexChanged.emit)

    def currentData(self):
        return self.choices[self.group.checkedId()][1]

    def setCurrentIndex(self, index):
        self.group.button(index).setChecked(True)
        self.currentIndexChanged.emit(index)


class ScanView(QGraphicsView):
    selected = Signal(str)
    hovered = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.people = []
        self.sources = []
        self.offset = (0, 0)
        self.down = None

    def show_page(self, pixmap, offset, people, selected, sources, relationships):
        self.people, self.sources, self.offset = people, sources, offset
        scene = self.scene()
        scene.clear()
        scene.addPixmap(pixmap)
        scene.setSceneRect(QRectF(pixmap.rect()))
        boxes = {p.get("person_id"): p.get("bbox") or {} for p in people}
        for rel in relationships:
            if rel.get("review_status") == "rejected":
                continue
            a, b = boxes.get(rel.get("parent_candidate_id")), boxes.get(rel.get("child_candidate_id"))
            if not a or not b:
                continue
            color = "#d946ef" if rel.get("review_status") == "confirmed" else "#ffb000"
            pen = QPen(QColor(color), 3)
            pen.setCosmetic(True)
            scene.addLine(a["x"] + a["width"] / 2 - offset[0], a["y"] + a["height"] - offset[1],
                          b["x"] + b["width"] / 2 - offset[0], b["y"] - offset[1], pen)
        for index, person in enumerate(people, 1):
            b = person.get("bbox") or {}
            if not b.get("width") or not b.get("height"):
                continue
            pen = QPen(QColor("#ef4444" if person.get("person_id") == selected else "#10b981"), 3)
            pen.setCosmetic(True)
            scene.addRect(b["x"] - offset[0], b["y"] - offset[1], b["width"], b["height"], pen)
            label = scene.addSimpleText(str(index))
            label.setBrush(QColor("#ff00ff"))
            label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations)
            label.setPos(b["x"] - offset[0], b["y"] - offset[1])
        for source in sources:
            b = source.get("bbox") or {}
            if not b.get("width") or not b.get("height"):
                continue
            pen = QPen(QColor("#00aaff"), 3)
            pen.setCosmetic(True)
            scene.addRect(b["x"] - offset[0], b["y"] - offset[1], b["width"], b["height"], pen)
            for token in source.get("token_boxes") or []:
                tb = token.get("bbox") or {}
                if tb.get("width") and tb.get("height"):
                    token_pen = QPen(QColor("#facc15"), 2)
                    token_pen.setCosmetic(True)
                    scene.addRect(tb["x"] - offset[0], tb["y"] - offset[1], tb["width"], tb["height"], token_pen)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        self.down = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.down is not None and (event.position() - self.down).manhattanLength() < 5:
            point = self.mapToScene(event.position().toPoint())
            x, y = point.x() + self.offset[0], point.y() + self.offset[1]
            for person in self.people:
                b = person.get("bbox") or {}
                if b and b.get("x", 0) <= x <= b.get("x", 0) + b.get("width", 0) and b.get("y", 0) <= y <= b.get("y", 0) + b.get("height", 0):
                    self.selected.emit(str(person["person_id"]))
                    break
        self.down = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self.down is None:
            point = self.mapToScene(event.position().toPoint())
            x, y = point.x() + self.offset[0], point.y() + self.offset[1]
            hits = [s for s in self.sources if (b := s.get("bbox") or {}) and b.get("x", 0) <= x <= b.get("x", 0) + b.get("width", 0) and b.get("y", 0) <= y <= b.get("y", 0) + b.get("height", 0)]
            if hits:
                hit = min(hits, key=lambda s: s["bbox"].get("width", 0) * s["bbox"].get("height", 0))
                self.hovered.emit(str(hit.get("text") or "OCR 텍스트 없음"))
        super().mouseMoveEvent(event)


class ReviewWindow(QMainWindow):
    fields = {"transcribed_name_hanja": "검수한 이름", "generation_number": "세대",
              "courtesy_name_hanja": "자(字)", "pen_name_hanja": "호(號)",
              "birth_text": "출생", "death_text": "사망", "office_title": "관직",
              "burial_text": "묘소", "biography_text": "인물 기록", "notes": "메모"}

    def __init__(self, root=None):
        super().__init__()
        self.setWindowTitle("족보 OCR 데스크톱 검수")
        self.resize(1500, 900)
        self.root = None
        self.selected_id = None
        self.page_people = []
        self.draft = {}
        self.loading = False
        self.dirty = False
        self.preview_link_sources = None
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        header = QWidget()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        title = QLabel("족보 OCR 검수")
        title.setObjectName("title")
        header_layout.addWidget(title)
        subtitle = QLabel("원본을 확인하고 인물과 관계를 검수합니다")
        subtitle.setObjectName("subtitle")
        header_layout.addWidget(subtitle)
        layout.addWidget(header)
        top = QHBoxLayout()
        layout.addLayout(top)
        open_button = QPushButton("OCR 결과 폴더 열기")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self.choose_folder)
        top.addWidget(open_button)
        self.folder_label = QLabel("폴더를 선택하세요")
        self.folder_label.setObjectName("muted")
        top.addWidget(self.folder_label, 1)
        self.pages = QComboBox()
        self.pages.currentIndexChanged.connect(self.change_page)
        top.addWidget(self.pages)
        import_button = QPushButton("페이지 다시 검색")
        import_button.clicked.connect(self.import_previous_page)
        top.addWidget(import_button)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        scan_title = QLabel("원본 스캔")
        scan_title.setObjectName("section")
        left_layout.addWidget(scan_title)
        self.scan_tools = QWidget(left)
        scan_tools_layout = QHBoxLayout(self.scan_tools)
        scan_tools_layout.setContentsMargins(0, 0, 0, 0)
        for text, factor in [("− 축소", 1 / 1.25), ("+ 확대", 1.25)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, scale=factor: self.scale_scans(scale))
            scan_tools_layout.addWidget(button)
        fit = QPushButton("화면 맞춤")
        fit.clicked.connect(self.fit_scans)
        scan_tools_layout.addWidget(fit)
        recover = QPushButton("누락 인명 후보 찾기")
        recover.clicked.connect(self.recover_people)
        scan_tools_layout.addWidget(recover)
        scan_tools_layout.addStretch(1)
        left_layout.addWidget(self.scan_tools)
        self.evidence = QLabel("OCR 박스에 마우스를 올려 원문을 확인하세요.")
        self.evidence.setObjectName("evidence")
        self.evidence.setWordWrap(True)
        self.evidence.setMinimumHeight(48)
        self.evidence.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.evidence)
        image_titles = QHBoxLayout()
        self.previous_scan_title = QLabel("이전 페이지 없음")
        self.previous_scan_title.setObjectName("muted")
        image_titles.addWidget(self.previous_scan_title, 1)
        self.current_scan_title = QLabel("현재 검수 페이지")
        self.current_scan_title.setObjectName("muted")
        image_titles.addWidget(self.current_scan_title, 1)
        left_layout.addLayout(image_titles)
        views = QHBoxLayout()
        views.setSpacing(8)
        self.previous_view = ScanView()
        self.previous_view.selected.connect(self.select_continuation_target)
        self.previous_view.hovered.connect(self.evidence.setText)
        views.addWidget(self.previous_view, 1)
        self.view = ScanView()
        self.view.selected.connect(self.select_person_id)
        self.view.hovered.connect(self.evidence.setText)
        views.addWidget(self.view, 1)
        left_layout.addLayout(views, 1)
        hint = QLabel("왼쪽: 직전 페이지 · 오른쪽: 현재 검수 페이지 · 드래그: 이동 · Ctrl + 휠: 확대/축소")
        hint.setObjectName("muted")
        left_layout.addWidget(hint)
        splitter.addWidget(left)
        right = QWidget()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("검수 작업")
        heading.setObjectName("section")
        right_layout.addWidget(heading)
        self.progress_label = QLabel("페이지를 열어 주세요")
        self.progress_label.setObjectName("muted")
        right_layout.addWidget(self.progress_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("인물 이름 또는 ID 검색")
        self.search.textChanged.connect(self.filter_people)
        right_layout.addWidget(self.search)
        self.person_results = QListWidget()
        self.person_results.setMinimumHeight(110)
        self.person_results.setMaximumHeight(170)
        self.person_results.currentItemChanged.connect(self.result_selected)
        right_layout.addWidget(self.person_results)
        tabs = self.tabs = QTabWidget()
        right_layout.addWidget(tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([950, 500])
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(10)
        self.people_list = QComboBox()
        self.people_list.currentIndexChanged.connect(self.person_changed)
        form.addRow("인물", self.people_list)
        self.raw_name = QLabel()
        self.raw_name.setWordWrap(True)
        form.addRow("이름 OCR 원문", self.raw_name)
        self.focus = OcrFocusSelector()
        self.focus.currentIndexChanged.connect(self.render_scan)
        form.addRow("OCR 강조", self.focus)
        self.inputs = {}
        for key, title in self.fields.items():
            widget = QTextEdit() if key in ("biography_text", "notes") else QLineEdit()
            if isinstance(widget, QTextEdit):
                widget.setFixedHeight(80)
                widget.textChanged.connect(self.mark_dirty)
            else:
                widget.textEdited.connect(self.mark_dirty)
            self.inputs[key] = widget
            form.addRow(title, widget)
        self.marker = QComboBox()
        for title, marker in [("없음", None), ("子 (아들)", "子"), ("女 (딸)", "女")]:
            self.marker.addItem(title, marker)
        self.marker.currentIndexChanged.connect(self.mark_dirty)
        form.addRow("원문 자녀 표식", self.marker)
        self.gender = QComboBox()
        for title, value in [("미상", "unknown"), ("남성", "male"), ("여성", "female")]:
            self.gender.addItem(title, value)
        self.gender.currentIndexChanged.connect(self.mark_dirty)
        self.gender.setToolTip("성별은 별도로 검수합니다. 子/女는 원문에 기록된 자녀 표식입니다.")
        form.addRow("성별", self.gender)
        self.name_status = QComboBox()
        for title, status in [("검토 대기", "needs_review"), ("확인", "confirmed"), ("거절", "rejected")]:
            self.name_status.addItem(title, status)
        self.info_confirmed = QCheckBox("추가 정보 확인")
        self.name_status.currentIndexChanged.connect(self.mark_dirty)
        self.info_confirmed.toggled.connect(self.mark_dirty)
        form.addRow("인명 검수 상태", self.name_status)
        form.addRow(self.info_confirmed)
        self.partners = QTextEdit()
        self.partners.setFixedHeight(110)
        self.partners.textChanged.connect(self.mark_dirty)
        form.addRow("배우자 배열 (JSON)", self.partners)
        self.attached_records = QTextEdit()
        self.attached_records.setReadOnly(True)
        self.attached_records.setFixedHeight(130)
        form.addRow("다른 페이지에서 연결한 원문", self.attached_records)
        save = QPushButton("인물 저장")
        save.setObjectName("primary")
        save.clicked.connect(self.save_person)
        scroll.setWidget(panel)
        tabs.addTab(scroll, "인물 검수")
        relations = QWidget()
        rel_layout = QVBoxLayout(relations)
        self.rel_list = QListWidget()
        rel_layout.addWidget(self.rel_list)
        for text, callback in [("선택 관계 승인", lambda: self.review_relation("confirmed")), ("선택 관계 거절", lambda: self.review_relation("rejected")), ("선택 인물을 부모로 지정", self.set_parent), ("선택 인물을 자녀로 연결", self.add_child), ("부모 선택 취소", self.cancel_parent)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            rel_layout.addWidget(button)
        self.parent_label = QLabel("선택된 부모 없음")
        rel_layout.addWidget(self.parent_label)
        self.pending_parent = None
        tabs.addTab(relations, "관계 검수")
        continuation_panel = QWidget()
        continuation_layout = QVBoxLayout(continuation_panel)
        instructions = QLabel("같은 행의 이전 페이지 마지막 인물을 제안합니다. 이름 누락 여부와 원본을 확인한 뒤 이어진 OCR 영역을 선택해 연결하세요.")
        instructions.setWordWrap(True)
        continuation_layout.addWidget(instructions)
        self.orphan_row = QComboBox()
        self.orphan_row.currentIndexChanged.connect(self.refresh_orphan_columns)
        continuation_layout.addWidget(self.orphan_row)
        self.orphan_list = QListWidget()
        self.orphan_list.setMinimumHeight(150)
        self.orphan_list.itemChanged.connect(self.orphan_selection_changed)
        self.orphan_list.currentItemChanged.connect(self.preview_orphan)
        continuation_layout.addWidget(self.orphan_list, 1)
        continuation_layout.addWidget(QLabel("선택한 영역의 OCR 원문 · 오른쪽에서 왼쪽 순서"))
        self.orphan_preview = QTextEdit()
        self.orphan_preview.setReadOnly(True)
        self.orphan_preview.setMinimumHeight(110)
        continuation_layout.addWidget(self.orphan_preview)
        self.continuation_target = QComboBox()
        self.continuation_target.currentIndexChanged.connect(self.render_scan)
        continuation_layout.addWidget(QLabel("연결할 이전 페이지 인물"))
        continuation_layout.addWidget(self.continuation_target)
        attach = QPushButton("선택한 OCR 영역을 인물에 연결")
        attach.clicked.connect(self.attach_continuation)
        continuation_layout.addWidget(attach)
        self.continuation_list = QListWidget()
        self.continuation_list.setMaximumHeight(70)
        self.continuation_list.currentItemChanged.connect(self.preview_continuation)
        continuation_layout.addWidget(self.continuation_list)
        detach = QPushButton("선택한 기록 연결 해제")
        detach.clicked.connect(self.detach_continuation)
        continuation_layout.addWidget(detach)
        continuation_scroll = QScrollArea()
        continuation_scroll.setWidgetResizable(True)
        continuation_scroll.setWidget(continuation_panel)
        tabs.addTab(continuation_scroll, "이어진 기록")
        tabs.currentChanged.connect(self.render_scan)
        tabs.currentChanged.connect(lambda index: save.setVisible(index == 0))
        right_layout.addWidget(save)
        if root:
            self.open_folder(Path(root))

    def import_previous_page(self):
        if not self.root:
            QMessageBox.information(self, "작업 폴더", "먼저 검수할 OCR 결과 폴더를 여세요.")
            return
        if not self.can_discard():
            return
        current = self.page_name
        self.open_folder(self.root, current)

    def import_page_data(self, rows_file, image_file):
        rows = read_json(rows_file, None)
        people = read_json(rows_file.parent / "people_candidates.json", [])
        rels = read_json(rows_file.parent / "relationship_candidates.json", [])
        if not isinstance(rows, list) or not rows or not isinstance(people, list) or not isinstance(rels, list):
            raise ValueError("rows.json과 인물/관계 후보 배열 형식을 확인하세요.")
        name = image_file.name
        # Per-page relationship files predate the aggregate source_page field.
        # Their page is supplied by the explicitly selected scan and page folder.
        rels = [{**rel, "source_page": rel.get("source_page") or name} for rel in rels]
        if any(page_name(p) == name for p in self.page_results):
            raise ValueError("이미 불러온 페이지입니다.")
        if any(p.get("source_page") != name for p in people) or any(r.get("source_page") != name for r in rels):
            raise ValueError("원본 스캔 이름과 OCR 후보의 페이지 이름이 다릅니다.")
        if {p.get("person_id") for p in people} & {p.get("person_id") for p in self.base_people}:
            raise ValueError("기존 인물 ID와 충돌합니다. 같은 판본의 서로 다른 페이지인지 확인하세요.")
        if cv2.imread(str(image_file)) is None:
            raise ValueError("원본 스캔 이미지를 읽을 수 없습니다.")
        entry = {"page_result": {"source_page": name, "source_image": str(image_file.resolve()),
                                "page_output_dir": str(rows_file.parent.resolve()), "rows": rows},
                 "people": people, "relationships": rels}
        self.state.setdefault("supplemental_pages", []).append(entry)
        if not self.persist():
            self.state["supplemental_pages"].pop()
            return False
        self.base_people, self.base_rels, self.page_results = merge_review_sources(self.base_people, self.base_rels, self.page_results, self.state)
        self.pages.blockSignals(True)
        self.pages.addItem(name)
        self.pages.blockSignals(False)
        self.refresh_orphan_rows()
        self.statusBar().showMessage("이전 페이지를 불러왔습니다. 이어진 기록 탭에서 연결하세요.", 6000)
        return True

    def recover_people(self):
        if not self.root or getattr(self, "source_image", None) is None:
            return
        if self.dirty:
            QMessageBox.information(self, "인물 저장", "인물 변경을 먼저 저장하세요.")
            return
        additions = recover_name_candidates(self.source_image, self.page, self.page_people, self.offset)
        if not additions:
            QMessageBox.information(self, "인명 후보", "추가로 검출된 큰 글자 인명 후보가 없습니다.")
            return
        if QMessageBox.question(self, "미검수 인명 후보", f"기존 OCR 결과와 이미지 기하에서 {len(additions)}개 후보를 찾았습니다. 검토 대기로 추가하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        self.state.setdefault("additional_people", []).extend(additions)
        if not self.persist():
            del self.state["additional_people"][-len(additions):]
            return
        self.base_people, self.base_rels, self.page_results = merge_review_sources(self.base_people, self.base_rels, self.page_results, self.state)
        self.change_page()
        self.select_person_id(additions[0]["person_id"])
        self.statusBar().showMessage("추가 후보의 이름과 영역을 원본에서 확인하세요.", 6000)

    def refresh_orphan_rows(self):
        self.preview_link_sources = None
        self.orphan_row.blockSignals(True)
        self.orphan_row.clear()
        for index, row in enumerate(self.page.get("rows", [])):
            regions = orphan_regions(row, self.page_people, self.state)
            preview = " ".join(regions[0]["text"].split())[:22] if regions else ""
            self.orphan_row.addItem(f"행 {row.get('row_number', index + 1)} · OCR 영역 {len(regions)}개 · {preview}", index)
        self.orphan_row.blockSignals(False)
        self.refresh_orphan_columns()

    def refresh_orphan_columns(self, *_):
        if not self.root or not hasattr(self, "page"):
            return
        self.preview_link_sources = None
        self.orphan_list.blockSignals(True)
        self.orphan_list.clear()
        self.orphan_preview.clear()
        self.continuation_target.clear()
        index = self.orphan_row.currentData()
        if index is not None:
            row = self.page["rows"][index]
            for number, region in enumerate(orphan_regions(row, self.page_people, self.state), 1):
                box = region["bbox"]
                snippet = " ".join(region["text"].split())
                label = (f"영역 {number} · x {box['x']}–{box['x'] + box['width']}, "
                         f"y {box['y']}–{box['y'] + box['height']} · {len(region['columns'])}열\n"
                         f"{snippet[:78]}{'…' if len(snippet) > 78 else ''}")
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, region)
                item.setToolTip(region["text"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.orphan_list.addItem(item)
            targets = previous_row_people(self.page, row, self.page_results, self.base_people, self.state)
            for person in targets:
                self.continuation_target.addItem(f"{person.get('source_page')} · {effective_name(person, self.state)}", person["person_id"])
        self.orphan_list.blockSignals(False)
        self.refresh_continuation_list()
        self.render_scan()

    def checked_orphan_columns(self):
        return [column for i in range(self.orphan_list.count())
                if self.orphan_list.item(i).checkState() == Qt.CheckState.Checked
                for column in self.orphan_list.item(i).data(Qt.ItemDataRole.UserRole)["columns"]]

    def checked_orphan_regions(self):
        return [self.orphan_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.orphan_list.count())
                if self.orphan_list.item(i).checkState() == Qt.CheckState.Checked]

    def preview_orphan(self, current, _previous):
        self.preview_link_sources = None
        if current:
            region = current.data(Qt.ItemDataRole.UserRole)
            self.orphan_preview.setPlainText(region["text"])
            self.preview_link_sources = [{"bbox": region["bbox"], "text": region["text"]}]
            self.render_scan()

    def orphan_selection_changed(self, *_):
        self.preview_link_sources = None
        self.render_scan()

    def attach_continuation(self):
        target_id = self.continuation_target.currentData()
        row_index = self.orphan_row.currentData()
        if not target_id or row_index is None:
            QMessageBox.information(self, "기록 연결", "같은 행의 이전 페이지 인물이 필요합니다. 페이지 목록과 이전 페이지 OCR 결과를 확인하세요.")
            return
        if self.dirty:
            QMessageBox.information(self, "인물 저장", "인물 변경을 먼저 저장하세요.")
            return
        target = next(p for p in self.base_people if p.get("person_id") == target_id)
        try:
            link = make_continuation(self.page, self.page["rows"][row_index], self.checked_orphan_columns(), target, self.state)
        except ValueError as exc:
            QMessageBox.warning(self, "기록 연결", str(exc))
            return
        self.state.setdefault("continuation_links", []).append(link)
        if not self.persist():
            self.state["continuation_links"].pop()
            return
        self.refresh_orphan_columns()
        self.statusBar().showMessage("이전 인물에 원문 기록을 연결했습니다. 검수한 인물 기록은 그대로 유지됩니다.", 6000)

    def refresh_continuation_list(self):
        self.continuation_list.clear()
        people = {p.get("person_id"): p for p in self.base_people}
        for link in self.state.get("continuation_links", []):
            if link.get("source_page") != self.page_name or link.get("review_status") != "confirmed":
                continue
            target = people.get(link.get("target_person_id"), {})
            item = QListWidgetItem(f"{link.get('source_row_id')} → {effective_name(target, self.state)} · {len(link.get('columns', []))}열")
            item.setData(Qt.ItemDataRole.UserRole, link["continuation_id"])
            self.continuation_list.addItem(item)

    def preview_continuation(self, current, _previous):
        if current:
            link = next(link for link in self.state.get("continuation_links", []) if link["continuation_id"] == current.data(Qt.ItemDataRole.UserRole))
            self.preview_link_sources = link.get("columns", [])
            self.render_scan()
            self.evidence.setText(link.get("text") or "")

    def detach_continuation(self):
        item = self.continuation_list.currentItem()
        if not item or self.dirty:
            return
        link = next(link for link in self.state.get("continuation_links", []) if link["continuation_id"] == item.data(Qt.ItemDataRole.UserRole))
        link["review_status"] = "rejected"
        if not self.persist():
            link["review_status"] = "confirmed"
            return
        self.preview_link_sources = None
        self.refresh_orphan_columns()
        self.render_scan()

    def mark_dirty(self, *_):
        if not self.loading and self.selected_id:
            self.dirty = True

    def can_discard(self):
        return not self.dirty or QMessageBox.question(self, "저장하지 않은 변경", "저장하지 않은 인물 변경을 버리시겠습니까?") == QMessageBox.StandardButton.Yes

    def choose_folder(self):
        if not self.can_discard():
            return
        folder = QFileDialog.getExistingDirectory(self, "OCR 결과 폴더")
        if folder:
            self.open_folder(Path(folder))

    def open_folder(self, path, selected_page=None):
        root = find_output_root(str(path))
        if root is None:
            QMessageBox.warning(self, "폴더 오류", "ocr_results.json을 찾을 수 없습니다.")
            return
        try:
            pages = read_json(root / "ocr_results.json", [])
            people = read_json(root / "people_candidates.json", [])
            rels = read_json(root / "relationship_candidates.json", [])
            state = read_json(root / "review_state.json", {})
            if not isinstance(pages, list) or not pages or not isinstance(state, dict) or not isinstance(people, list) or not isinstance(rels, list):
                raise ValueError("OCR 결과 또는 검수 상태 형식이 올바르지 않습니다.")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "읽기 오류", str(exc))
            return
        self.root, self.page_results, self.base_people, self.base_rels, self.state = root, pages, people, rels, state
        for key, default in [("people_updates", {}), ("relationship_updates", {}), ("manual_relationships", []), ("person_uid_map", {}), ("edition", {"edition_id": "jokbo-1987", "publication_year": 1987, "volume": None}), ("page_metadata", {})]:
            self.state.setdefault(key, default)
        self.base_people, self.base_rels, self.page_results = merge_review_sources(
            self.base_people, self.base_rels, self.page_results, self.state
        )
        discovered, warnings = discover_page_outputs(root, self.page_results, self.base_people)
        self.base_people, self.base_rels, self.page_results = merge_review_sources(
            self.base_people, self.base_rels, self.page_results, {"supplemental_pages": discovered}
        )
        self.page_results.sort(key=page_sort_key)
        self.state_digest = file_digest(root / "review_state.json")
        self.dirty = False
        self.selected_id = None
        self.folder_label.setText(str(root))
        self.pages.blockSignals(True)
        self.pages.clear()
        for page in self.page_results:
            self.pages.addItem(page_name(page))
        if selected_page and self.pages.findText(selected_page) >= 0:
            self.pages.setCurrentIndex(self.pages.findText(selected_page))
        elif self.pages.count() > 1:
            self.pages.setCurrentIndex(1)
        self.pages.blockSignals(False)
        self.search.clear()
        self.change_page()
        if warnings:
            self.statusBar().showMessage("일부 페이지를 읽지 못했습니다: " + "; ".join(warnings), 12000)

    def relationships(self):
        return [effective_relationship(r, self.state) for r in self.base_rels + self.state["manual_relationships"]]

    def scale_scans(self, factor):
        for view in (self.previous_view, self.view):
            view.scale(factor, factor)

    def fit_scans(self):
        for view in (self.previous_view, self.view):
            if not view.sceneRect().isEmpty():
                view.fitInView(view.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def page_directory(self, page):
        page_dir = Path(page.get("page_output_dir") or self.root / Path(str(page.get("source_image", page_name(page)))).stem)
        if not page_dir.is_absolute():
            page_dir = self.root / page_dir
        if not page_dir.exists():
            page_dir = self.root / Path(str(page.get("source_image", page_name(page)))).stem
        return page_dir

    def load_page_visual(self, page):
        image, offset, _ = get_page_image(page, str(self.page_directory(page)))
        from PySide6.QtGui import QImage
        rgb = image[:, :, ::-1].copy()
        qimage = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimage), offset, image

    def load_previous_page(self):
        self.previous_page = self.page_results[self.page_index - 1] if self.page_index > 0 else None
        self.previous_people = []
        self.previous_pixmap, self.previous_offset = QPixmap(), (0, 0)
        if not self.previous_page:
            self.previous_scan_title.setText("이전 페이지 없음")
            return
        previous_name = page_name(self.previous_page)
        self.previous_scan_title.setText(f"이전 페이지 · {previous_name}")
        self.previous_people = [person for person in self.base_people if person.get("source_page") == previous_name]
        try:
            self.previous_pixmap, self.previous_offset, _ = self.load_page_visual(self.previous_page)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"이전 페이지 이미지를 읽지 못했습니다: {exc}", 8000)

    def select_continuation_target(self, person_id):
        index = self.continuation_target.findData(person_id)
        if index < 0:
            self.statusBar().showMessage("같은 행의 이전 페이지 인물만 연결 대상으로 선택할 수 있습니다.", 5000)
            return
        self.continuation_target.setCurrentIndex(index)
        self.statusBar().showMessage("왼쪽 인물을 이어진 기록의 연결 대상으로 선택했습니다.", 4000)

    def change_page(self, *_):
        if not self.root:
            return
        if self.dirty and not self.can_discard():
            self.pages.blockSignals(True)
            self.pages.setCurrentIndex(self.page_index)
            self.pages.blockSignals(False)
            return
        self.dirty = False
        self.page_index = self.pages.currentIndex()
        if self.page_index < 0:
            return
        self.page = self.page_results[self.page_index]
        self.page_name = self.pages.currentText()
        self.page_people = [p for p in self.base_people if p.get("source_page") == self.page_name]
        self.people_list.blockSignals(True)
        self.people_list.clear()
        self.people_list.addItem("인물 선택", None)
        for index, person in enumerate(self.page_people, 1):
            self.people_list.addItem(f"{index}. {effective_name(person, self.state)}", person.get("person_id"))
        self.people_list.blockSignals(False)
        self.selected_id = None
        self.refresh_people_list()
        self.pending_parent = None
        self.parent_label.setText("선택된 부모 없음")
        self.current_scan_title.setText(f"현재 검수 페이지 · {self.page_name}")
        try:
            self.pixmap, self.offset, self.source_image = self.load_page_visual(self.page)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "이미지 오류", str(exc))
            self.pixmap, self.offset = QPixmap(), (0, 0)
            self.source_image = None
        self.load_previous_page()
        self.refresh_orphan_rows()
        self.person_changed()
        self.fit_scans()

    def select_person_id(self, pid):
        index = self.people_list.findData(pid)
        if index >= 0:
            self.people_list.setCurrentIndex(index)

    def refresh_people_list(self):
        self.person_results.blockSignals(True)
        self.person_results.clear()
        confirmed = 0
        labels = {"confirmed": "확인", "needs_review": "검토 대기", "rejected": "거절"}
        colors = {"confirmed": "#62d6ac", "needs_review": "#ffc577", "rejected": "#ef9abb"}
        for index, person in enumerate(self.page_people, 1):
            pid = person.get("person_id")
            status = self.state["people_updates"].get(pid, {}).get("review_status") or person.get("review_status", "needs_review")
            confirmed += status == "confirmed"
            name = effective_name(person, self.state)
            item = QListWidgetItem(f"{index:>2}.  {name}     ·     {labels.get(status, status)}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{name} {pid}".casefold())
            item.setForeground(QColor(colors.get(status, "#e5edf7")))
            self.person_results.addItem(item)
            if pid == self.selected_id:
                self.person_results.setCurrentItem(item)
        self.person_results.blockSignals(False)
        self.progress_label.setText(f"인명 확인 {confirmed} / {len(self.page_people)}   ·   색상과 상태로 구분")
        self.filter_people(self.search.text())

    def filter_people(self, text):
        query = text.strip().casefold()
        for row in range(self.person_results.count()):
            item = self.person_results.item(row)
            item.setHidden(bool(query) and query not in item.data(Qt.ItemDataRole.UserRole + 1))

    def result_selected(self, current, previous):
        if current:
            self.select_person_id(current.data(Qt.ItemDataRole.UserRole))
            if self.people_list.currentData() != current.data(Qt.ItemDataRole.UserRole):
                self.person_results.blockSignals(True)
                self.person_results.setCurrentItem(previous)
                self.person_results.blockSignals(False)

    def person_changed(self, *_):
        if self.dirty and not self.can_discard():
            self.people_list.blockSignals(True)
            self.people_list.setCurrentIndex(max(0, self.people_list.findData(self.selected_id)))
            self.people_list.blockSignals(False)
            return
        self.dirty = False
        self.selected_id = self.people_list.currentData()
        person = next((p for p in self.page_people if p.get("person_id") == self.selected_id), None)
        self.loading = True
        self.draft = extract_person_info_draft(person, self.page, self.page_people) if person else {}
        update = self.state["people_updates"].get(self.selected_id, {})
        draft_values = self.draft.get("draft_values") or {}
        self.raw_name.setText(str((person or {}).get("raw_name_ocr") or (person or {}).get("name_hanja_candidate") or ""))
        for key, widget in self.inputs.items():
            value = update.get(key, (person or {}).get(key, draft_values.get(key, "")))
            if key == "transcribed_name_hanja" and not value and person:
                value = strip_name_marker(person.get("name_hanja_candidate") or person.get("raw_name_ocr") or "")[0]
            if isinstance(widget, QTextEdit):
                widget.setPlainText(str(value or ""))
            else:
                widget.setText(str(value if value is not None else ""))
            widget.setEnabled(bool(person))
        marker = update.get("sex_marker", (person or {}).get("sex_marker"))
        if not marker and person:
            marker = strip_name_marker(person.get("raw_name_ocr") or person.get("name_hanja_candidate") or "")[1]
        self.marker.setCurrentIndex(max(0, self.marker.findData(marker)))
        existing_gender = update.get("gender", (person or {}).get("gender"))
        if existing_gender is None:
            existing_gender = {"子": "male", "女": "female"}.get(marker, "unknown")
        if self.gender.findData(existing_gender) < 0:
            self.gender.addItem(f"기존 값: {existing_gender}", existing_gender)
        self.gender.setCurrentIndex(self.gender.findData(existing_gender))
        status = update.get("review_status", (person or {}).get("review_status", "needs_review"))
        self.name_status.setCurrentIndex(max(0, self.name_status.findData(status)))
        self.info_confirmed.setChecked(update.get("information_review_status", (person or {}).get("information_review_status")) == "confirmed")
        self.partners.setPlainText(json.dumps(update.get("spouses", (person or {}).get("spouses") or []), ensure_ascii=False, indent=2))
        self.attached_records.setPlainText("\n\n".join(
            f"{link.get('source_page')} · {link.get('source_row_id')}\n{link.get('text', '')}"
            for link in self.state.get("continuation_links", []) if link.get("review_status") == "confirmed"
            and link.get("target_person_id") == self.selected_id
        ))
        self.loading = False
        self.person_results.blockSignals(True)
        for row in range(self.person_results.count()):
            item = self.person_results.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == self.selected_id:
                if item.isHidden():
                    self.search.clear()
                self.person_results.setCurrentItem(item)
                break
        self.person_results.blockSignals(False)
        self.render_scan()
        self.refresh_relations()

    def render_scan(self, *_):
        if not self.root or not hasattr(self, "pixmap"):
            return
        person = next((p for p in self.page_people if p.get("person_id") == self.selected_id), None)
        focus = self.focus.currentData()
        if self.tabs.currentIndex() == 2:
            sources = self.preview_link_sources if self.preview_link_sources is not None else [
                {"bbox": region["bbox"], "text": region["text"]} for region in self.checked_orphan_regions()]
        elif not person:
            sources = []
        elif focus == "name":
            sources = [{"bbox": person.get("bbox"), "text": person.get("raw_name_ocr") or person.get("name_hanja_candidate") or ""}]
        elif focus == "all":
            sources = self.draft.get("source_columns") or self.draft.get("columns") or []
            if not sources:
                sources = (self.draft.get("record_ocr") or {}).get("columns") or []
        else:
            sources = get_field_source_columns(self.draft, focus)
        if person and not sources:
            self.evidence.setText("이 항목의 OCR 위치 근거가 없습니다.")
        else:
            self.evidence.setText("OCR 박스에 마우스를 올려 원문을 확인하세요.")
        self.view.show_page(self.pixmap, self.offset, self.page_people, self.selected_id, sources,
                            [r for r in self.relationships() if r.get("source_page") == self.page_name])
        previous_target = self.continuation_target.currentData() if self.tabs.currentIndex() == 2 else None
        self.previous_view.show_page(
            self.previous_pixmap, self.previous_offset, self.previous_people, previous_target, [],
            [r for r in self.relationships() if self.previous_page and r.get("source_page") == page_name(self.previous_page)]
        )

    def refresh_relations(self):
        self.rel_list.clear()
        names = {p.get("person_id"): f"{i}. {effective_name(p, self.state)}" for i, p in enumerate(self.page_people, 1)}
        for rel in self.relationships():
            if rel.get("source_page") != self.page_name:
                continue
            if self.selected_id and self.selected_id not in (rel.get("parent_candidate_id"), rel.get("child_candidate_id")):
                continue
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(f"{rel.get('review_status', 'needs_review')} · {names.get(rel.get('parent_candidate_id'), '?')} → {names.get(rel.get('child_candidate_id'), '?')}")
            item.setData(Qt.ItemDataRole.UserRole, relationship_key(rel))
            self.rel_list.addItem(item)

    def persist(self):
        if file_digest(self.root / "review_state.json") != self.state_digest:
            QMessageBox.warning(self, "저장 충돌", "다른 프로그램에서 검수 상태를 변경했습니다. 다시 열어 확인하세요.")
            return False
        try:
            people, _, _ = merge_review_sources(self.base_people, self.base_rels, self.page_results, self.state)
            for person in people:
                ensure_person_uid(person, self.state)
            save_state(self.root, self.state, self.base_people, self.base_rels, self.page_results)
            self.state_digest = file_digest(self.root / "review_state.json")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "저장 오류", str(exc))
            return False
        return True

    def save_person(self):
        if not self.selected_id:
            return
        try:
            spouses = json.loads(self.partners.toPlainText())
            if not isinstance(spouses, list) or any(not isinstance(p, dict) for p in spouses):
                raise ValueError("배우자는 객체의 JSON 배열이어야 합니다.")
            values = {key: (widget.toPlainText() if isinstance(widget, QTextEdit) else widget.text()).strip() or None for key, widget in self.inputs.items()}
            values["generation_number"] = parse_optional_generation(values["generation_number"] or "")
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "입력 오류", str(exc))
            return
        name, inferred_marker, _ = strip_name_marker(values["transcribed_name_hanja"] or "")
        marker = self.marker.currentData() or inferred_marker
        values.update({"transcribed_name_hanja": name or None, "sex_marker": marker,
                       "gender": self.gender.currentData(), "spouses": spouses,
                       "review_status": self.name_status.currentData(),
                       "information_review_status": "confirmed" if self.info_confirmed.isChecked() else "needs_review",
                       "transcription_status": "manually_verified" if self.name_status.currentData() == "confirmed" else "pending_manual_verification"})
        old = self.state["people_updates"].get(self.selected_id)
        person = next(p for p in self.page_people if p.get("person_id") == self.selected_id)
        previous_spouses = (old or {}).get("spouses", person.get("spouses") or [])
        if spouses != previous_spouses:
            labels = {"wife": "부인", "concubine": "첩", "other": "기타"}
            values["spouse_text"] = " / ".join(
                f"{labels.get(p.get('type'), '기타')}: {p.get('name_and_record') or p.get('name_text')}"
                for p in spouses if p.get("name_and_record") or p.get("name_text")
            ) or None
        self.state["people_updates"][self.selected_id] = {**(old or {}), **values}
        if not self.persist():
            if old is None:
                del self.state["people_updates"][self.selected_id]
            else:
                self.state["people_updates"][self.selected_id] = old
            return
        self.dirty = False
        self.people_list.setItemText(self.people_list.currentIndex(), f"{self.people_list.currentIndex()}. {effective_name(next(p for p in self.page_people if p.get('person_id') == self.selected_id), self.state)}")
        self.statusBar().showMessage("인물을 저장했습니다.", 4000)
        self.refresh_people_list()
        self.refresh_relations()

    def review_relation(self, status):
        item = self.rel_list.currentItem()
        if not item or self.dirty:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        rel = next(r for r in self.relationships() if relationship_key(r) == key)
        others = [r for r in self.relationships() if relationship_key(r) != key]
        parent, child = rel.get("parent_candidate_id"), rel.get("child_candidate_id")
        if status == "confirmed" and (not parent or not child or parent == child or would_create_cycle(parent, child, others) or any(r.get("review_status") != "rejected" and r.get("parent_candidate_id") == parent and r.get("child_candidate_id") == child for r in others)):
            QMessageBox.warning(self, "관계 오류", "중복되거나 순환을 만드는 관계는 승인할 수 없습니다.")
            return
        old = self.state["relationship_updates"].get(key)
        self.state["relationship_updates"][key] = {**(old or {}), "review_status": status}
        if not self.persist():
            if old is None:
                del self.state["relationship_updates"][key]
            else:
                self.state["relationship_updates"][key] = old
            return
        self.refresh_relations()
        self.render_scan()

    def set_parent(self):
        if self.selected_id:
            self.pending_parent = self.selected_id
            self.parent_label.setText(f"부모: {self.people_list.currentText()}")

    def cancel_parent(self):
        self.pending_parent = None
        self.parent_label.setText("선택된 부모 없음")

    def add_child(self):
        parent, child = self.pending_parent, self.selected_id
        if not parent or not child or self.dirty:
            return
        rels = self.relationships()
        if parent == child or would_create_cycle(parent, child, rels) or any(r.get("parent_candidate_id") == parent and r.get("child_candidate_id") == child and r.get("review_status") != "rejected" for r in rels):
            QMessageBox.warning(self, "관계 오류", "동일 인물, 중복 관계 또는 순환 관계입니다.")
            return
        rel = {"relationship_id": f"{Path(self.page_name).stem}_MANUAL_{uuid.uuid4().hex}", "source_page": self.page_name,
               "type": "parent_child", "parent_candidate_id": parent, "child_candidate_id": child,
               "relationship_basis": "manual_visual_link", "placement_role": "manually_confirmed",
               "review_status": "confirmed", "warning": None}
        self.state["manual_relationships"].append(rel)
        if not self.persist():
            self.state["manual_relationships"].pop()
            return
        self.refresh_relations()
        self.render_scan()

    def closeEvent(self, event):
        if self.can_discard():
            event.accept()
        else:
            event.ignore()


def main():
    parser = argparse.ArgumentParser(description="족보 OCR PySide6 검수 앱")
    parser.add_argument("output", nargs="?", help="OCR 결과 폴더")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    if not configure_application(app):
        QMessageBox.warning(None, "글꼴 오류", "포함된 한글·한자 글꼴을 불러오지 못했습니다. assets/fonts 폴더를 확인하세요.")
    window = ReviewWindow(args.output)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
