"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const STATUS_LABEL = {
  pending: "대기",
  in_review: "검수 중",
  approved: "승인",
  needs_fix: "수정 필요",
};

const TYPE_LABEL = {
  genealogy: "세보",
  preface: "서문",
  photo: "사진",
  index: "색인",
  generation_name_table: "항렬표",
  property: "재산목록",
  officers: "임원록",
  subscription: "수단",
  colophon: "간기",
  cover: "표지",
  unknown: "미분류",
  missing: "미수록",
};

const state = {
  items: [],
  current: null,
  detail: null,
  dirty: false,
  zoom: 1,
  tx: 0,
  ty: 0,
  dragging: false,
  drag: null,
  searchTimer: null,
  loading: false,
};

function sectionLabel(section) {
  return section === "frontmatter" ? "전편" : "본편";
}

function keyOf(section, pageNo) {
  return `${section}:${pageNo}`;
}

function debounce(fn, delay) {
  return (...args) => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => fn(...args), delay);
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = payload && payload.error ? payload.error : `HTTP ${response.status}`;
    const error = new Error(message);
    error.payload = payload;
    throw error;
  }
  return payload;
}

// ---------- list ----------

function filterParams() {
  return new URLSearchParams({
    section: $("#filter-section").value,
    status: $("#filter-status").value,
    has_json: $("#filter-json").value,
    q: $("#search").value.trim(),
  });
}

async function loadList({ initial = false } = {}) {
  try {
    const data = await api(`/api/pages?${filterParams()}`);
    state.items = data.items;
    renderStats(data.stats);
    renderList();
    if (initial) {
      const fromHash = readHash();
      const match = fromHash && state.items.find((item) => keyOf(item.section, item.printed_page_no) === keyOf(fromHash.section, fromHash.page));
      const fallback =
        state.items.find((item) => item.has_json) ||
        state.items.find((item) => item.page_type !== "missing");
      const target = match || fallback;
      if (target) loadPage(target.section, target.printed_page_no);
    }
  } catch (error) {
    setListMessage(`목록을 불러오지 못했습니다: ${error.message}`);
  }
}

function setListMessage(message) {
  const list = $("#page-list");
  list.replaceChildren();
  const div = document.createElement("div");
  div.className = "list-count";
  div.textContent = message;
  list.append(div);
}

function renderStats(stats) {
  const parts = [
    ["전체", stats.total],
    ["수록", stats.present],
    ["파싱", stats.parsed],
    ["승인", stats.approved],
    ["수정", stats.needs_fix],
    ["검수필요", stats.needs_human],
  ];
  const container = $("#stats");
  container.replaceChildren();
  for (const [label, value] of parts) {
    const span = document.createElement("span");
    span.append(`${label} `);
    const b = document.createElement("b");
    b.textContent = value;
    span.append(b);
    container.append(span);
  }
}

function renderList() {
  const list = $("#page-list");
  list.replaceChildren();
  $("#list-count").textContent = `${state.items.length}면`;

  const fragment = document.createDocumentFragment();
  for (const item of state.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-item";
    button.dataset.section = item.section;
    button.dataset.page = String(item.printed_page_no);
    button.title = item.notes || `${sectionLabel(item.section)} ${item.printed_page_no}면`;
    if (item.page_type === "missing") button.classList.add("missing");
    if (state.current && state.current.section === item.section && state.current.page === item.printed_page_no) {
      button.classList.add("active");
    }

    const dot = document.createElement("span");
    dot.className = `dot ${item.status || "pending"}`;
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = `${item.section === "frontmatter" ? "전" : "본"} ${item.printed_page_no}`;
    const names = document.createElement("span");
    names.className = "names";
    if (item.page_type === "missing") {
      names.textContent = "미수록";
    } else if (item.names && item.names.length) {
      names.textContent = item.names.join(" · ");
      if (item.needs_human) {
        const mark = document.createElement("small");
        mark.textContent = " ⚑";
        mark.title = "사람 확인 필요";
        names.append(mark);
      }
    } else {
      names.textContent = TYPE_LABEL[item.page_type] || item.page_type;
      if (!item.has_json) names.classList.add("muted");
    }

    button.append(dot, no, names);
    button.addEventListener("click", () => loadPage(item.section, item.printed_page_no));
    fragment.append(button);
  }
  list.append(fragment);

  const active = list.querySelector(".page-item.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

// ---------- page ----------

function readHash() {
  const match = location.hash.match(/^#(frontmatter|genealogy)\/(\d+)$/);
  return match ? { section: match[1], page: Number(match[2]) } : null;
}

function writeHash(section, page) {
  history.replaceState(null, "", `#${section}/${page}`);
}

async function loadPage(section, pageNo) {
  if (state.loading) return;
  if (state.dirty && !confirm("저장하지 않은 JSON이 있습니다. 이동할까요?")) return;
  state.loading = true;
  try {
    const detail = await api(`/api/pages/${section}/${pageNo}`);
    state.current = { section, page: pageNo };
    state.detail = detail;
    state.dirty = false;
    writeHash(section, pageNo);
    renderDetail();
    renderList();
  } catch (error) {
    setSaveState(`불러오기 실패: ${error.message}`, "bad");
  } finally {
    state.loading = false;
  }
}

function renderDetail() {
  const detail = state.detail;
  if (!detail) return;
  const item = detail.page;

  $("#page-title").textContent = `${sectionLabel(item.section)} ${item.printed_page_no}면`;
  $("#page-meta").textContent = [
    TYPE_LABEL[item.page_type] || item.page_type,
    item.source_path || "파일 없음",
    item.width && item.height ? `${item.width}×${item.height}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const image = $("#page-image");
  const empty = $("#image-empty");
  if (item.page_type === "missing") {
    image.classList.add("hidden");
    empty.classList.remove("hidden");
    empty.textContent = "미수록 페이지입니다.";
  } else {
    image.classList.remove("hidden");
    empty.classList.add("hidden");
    image.onload = () => {
      empty.classList.add("hidden");
    };
    image.onerror = () => {
      image.classList.add("hidden");
      empty.classList.remove("hidden");
      empty.textContent = "이미지를 불러올 수 없습니다.";
    };
    image.src = `${detail.image_url}?t=${Date.now()}`;
    image.alt = `${sectionLabel(item.section)} ${item.printed_page_no}면 스캔`;
  }
  resetZoom();

  const editor = $("#json-editor");
  editor.value = detail.parsed ? JSON.stringify(detail.parsed, null, 2) : "";
  editor.disabled = item.page_type === "missing";

  $("#ocr-text").textContent = detail.ocr || "OCR 텍스트가 없습니다. (vision 전용 파싱이면 정상입니다.)";
  $("#note-editor").value = item.status_note || "";

  renderStatus(item);
  renderQuality(detail);
  renderValidation(detail.validation, detail.parsed);
  setSaveState("", "");
}

function renderStatus(item) {
  for (const button of $$(".review-bar button[data-status]")) {
    button.classList.toggle("active", button.dataset.status === (item.status || "pending"));
    button.disabled = item.page_type === "missing";
  }
  $("#review-state").textContent = item.status_updated_at
    ? `마지막 변경 ${item.status_updated_at}`
    : STATUS_LABEL[item.status || "pending"];
}

function renderQuality(detail) {
  const item = detail.page;
  const container = $("#quality");
  container.replaceChildren();
  const chips = [];
  chips.push([TYPE_LABEL[item.page_type] || item.page_type, ""]);
  if (item.has_json) {
    const people = detail.parsed && Array.isArray(detail.parsed.entries) ? detail.parsed.entries.length : 0;
    chips.push([`인물 ${people}`, ""]);
    if (item.rows) chips.push([`단 ${item.rows}`, ""]);
  }
  if (item.needs_human) chips.push([`사람 확인 ${item.needs_human}`, "warn"]);
  const errors = detail.validation ? detail.validation.errors.length : 0;
  const warnings = detail.validation ? detail.validation.warnings.length : 0;
  if (errors) chips.push([`오류 ${errors}`, "bad"]);
  if (warnings) chips.push([`경고 ${warnings}`, "warn"]);
  if (item.has_json && !errors) chips.push(["검증 통과", "ok"]);
  if (item.page_type === "missing") chips.push(["미수록", "bad"]);

  for (const [text, tone] of chips) {
    const span = document.createElement("span");
    span.className = `chip ${tone}`.trim();
    span.textContent = text;
    container.append(span);
  }
}

function renderValidation(validation, parsed) {
  const container = $("#validation");
  container.replaceChildren();
  if (!parsed) {
    container.textContent = "파싱 결과가 없습니다.";
    return;
  }
  const errors = validation ? validation.errors : [];
  const warnings = validation ? validation.warnings : [];
  if (!errors.length && !warnings.length) {
    container.textContent = "검증 통과";
    return;
  }
  for (const message of errors) {
    const div = document.createElement("div");
    div.className = "error";
    div.textContent = `오류: ${message}`;
    container.append(div);
  }
  for (const message of warnings) {
    const div = document.createElement("div");
    div.className = "warning";
    div.textContent = `경고: ${message}`;
    container.append(div);
  }
}

function setSaveState(message, tone = "") {
  const element = $("#save-state");
  element.textContent = message;
  element.className = `save-state ${tone}`.trim();
}

// ---------- actions ----------

async function saveJson() {
  if (!state.current) return;
  const { section, page } = state.current;
  const editor = $("#json-editor");
  const text = editor.value.trim();
  if (!text) {
    setSaveState("JSON이 비었습니다.", "bad");
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    setSaveState(`JSON 구문 오류: ${error.message}`, "bad");
    return;
  }
  setSaveState("저장 중…");
  try {
    const result = await api(`/api/pages/${section}/${page}/json`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed),
    });
    state.detail.parsed = parsed;
    state.dirty = false;
    const warningText = result.warnings && result.warnings.length ? ` (경고 ${result.warnings.length})` : "";
    setSaveState(`저장됨${warningText}`, "ok");
    renderValidation({ errors: [], warnings: result.warnings || [] }, parsed);
    await loadList();
  } catch (error) {
    const details = error.payload && error.payload.errors ? error.payload.errors : [error.message];
    setSaveState("저장 실패", "bad");
    renderValidation({ errors: details, warnings: (error.payload && error.payload.warnings) || [] }, parsed);
  }
}

async function saveStatus(status) {
  if (!state.current || !state.detail) return;
  const { section, page } = state.current;
  if (state.detail.page.page_type === "missing") {
    setSaveState("미수록 페이지는 상태를 바꿀 수 없습니다.", "bad");
    return;
  }
  const note = $("#note-editor").value;
  try {
    const result = await api(`/api/pages/${section}/${page}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, note }),
    });
    state.detail.page.status = result.review.status;
    state.detail.page.status_note = result.review.note;
    state.detail.page.status_updated_at = result.review.updated_at;
    renderStatus(state.detail.page);
    setSaveState(`상태: ${STATUS_LABEL[status]}`, "ok");
    await loadList();
  } catch (error) {
    setSaveState(`상태 저장 실패: ${error.message}`, "bad");
  }
}

async function saveNote() {
  if (!state.detail) return;
  await saveStatus(state.detail.page.status || "pending");
}

function navigate(delta) {
  if (!state.detail) return;
  const target = delta > 0 ? state.detail.neighbors.next : state.detail.neighbors.prev;
  if (target) loadPage(state.current.section, target);
}

function formatJson() {
  const editor = $("#json-editor");
  try {
    editor.value = JSON.stringify(JSON.parse(editor.value), null, 2);
    state.dirty = true;
    setSaveState("정렬됨 (저장 필요)");
  } catch (error) {
    setSaveState(`JSON 구문 오류: ${error.message}`, "bad");
  }
}

// ---------- image zoom / pan ----------

function applyTransform() {
  const image = $("#page-image");
  image.style.transform = `translate(${state.tx}px, ${state.ty}px) scale(${state.zoom})`;
  $("#zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function resetZoom() {
  state.zoom = 1;
  state.tx = 0;
  state.ty = 0;
  applyTransform();
}

function zoomBy(factor) {
  const next = Math.min(6, Math.max(0.3, state.zoom * factor));
  state.zoom = next;
  applyTransform();
}

function bindImage() {
  const stage = $("#image-stage");
  const image = $("#page-image");

  stage.addEventListener(
    "wheel",
    (event) => {
      if (event.target.closest(".zoom-controls")) return;
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12);
    },
    { passive: false }
  );

  stage.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (event.target.closest(".zoom-controls")) return;
    state.dragging = true;
    state.drag = { x: event.clientX, y: event.clientY, tx: state.tx, ty: state.ty };
    stage.classList.add("dragging");
    stage.setPointerCapture(event.pointerId);
  });

  stage.addEventListener("pointermove", (event) => {
    if (!state.dragging || !state.drag) return;
    state.tx = state.drag.tx + (event.clientX - state.drag.x);
    state.ty = state.drag.ty + (event.clientY - state.drag.y);
    applyTransform();
  });

  const endDrag = () => {
    state.dragging = false;
    state.drag = null;
    stage.classList.remove("dragging");
  };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);
  stage.addEventListener("dblclick", resetZoom);

  $("#zoom-in").addEventListener("click", () => zoomBy(1.2));
  $("#zoom-out").addEventListener("click", () => zoomBy(1 / 1.2));
  $("#zoom-fit").addEventListener("click", resetZoom);
}

// ---------- events ----------

function bind() {
  $("#filter-section").addEventListener("change", () => loadList());
  $("#filter-status").addEventListener("change", () => loadList());
  $("#filter-json").addEventListener("change", () => loadList());
  $("#search").addEventListener("input", debounce(() => loadList(), 220));

  $("#save").addEventListener("click", saveJson);
  $("#format").addEventListener("click", formatJson);
  $("#json-editor").addEventListener("input", () => {
    state.dirty = true;
    setSaveState("수정됨 (저장 필요)");
  });

  for (const button of $$(".review-bar button[data-status]")) {
    button.addEventListener("click", () => saveStatus(button.dataset.status));
  }
  $("#prev").addEventListener("click", () => navigate(-1));
  $("#next").addEventListener("click", () => navigate(1));

  for (const tab of $$(".tab")) {
    tab.addEventListener("click", () => {
      for (const other of $$(".tab")) other.classList.toggle("active", other === tab);
      for (const panel of $$(".tab-panel")) panel.classList.add("hidden");
      $(`#tab-${tab.dataset.tab}`).classList.remove("hidden");
    });
  }

  // Notes are saved together with the review status.
  const noteSave = document.createElement("button");
  noteSave.id = "save-note";
  noteSave.textContent = "메모 저장";
  noteSave.className = "primary";
  noteSave.style.margin = "0 12px 12px";
  noteSave.addEventListener("click", saveNote);
  $("#tab-notes").append(noteSave);

  window.addEventListener("hashchange", () => {
    const target = readHash();
    if (target) loadPage(target.section, target.page);
  });

  window.addEventListener("beforeunload", (event) => {
    if (state.dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  document.addEventListener("keydown", (event) => {
    const typing = event.target.matches("textarea, input, select");
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveJson();
      return;
    }
    if (typing) return;
    if (event.key === "j" || event.key === "ArrowDown") {
      event.preventDefault();
      navigate(1);
    } else if (event.key === "k" || event.key === "ArrowUp") {
      event.preventDefault();
      navigate(-1);
    } else if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveJson();
    } else if (["1", "2", "3", "4"].includes(event.key)) {
      event.preventDefault();
      saveStatus(["pending", "in_review", "approved", "needs_fix"][Number(event.key) - 1]);
    }
  });

  bindImage();
}

bind();
loadList({ initial: true });
