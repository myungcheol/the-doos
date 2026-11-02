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

function migrateRawName(value) {
  if (Array.isArray(value)) {
    value.forEach(migrateRawName);
    return;
  }
  if (!value || typeof value !== "object") return;
  if (Object.prototype.hasOwnProperty.call(value, "raw_name") && !Object.prototype.hasOwnProperty.call(value, "as_printed")) {
    value.as_printed = value.raw_name;
    delete value.raw_name;
  }
  for (const key of Object.keys(value)) migrateRawName(value[key]);
}

async function loadPage(section, pageNo) {
  if (state.loading) return;
  if (state.dirty && !confirm("저장하지 않은 JSON이 있습니다. 이동할까요?")) return;
  state.loading = true;
  try {
    const detail = await api(`/api/pages/${section}/${pageNo}`);
    migrateRawName(detail.parsed);
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
  renderStructure(detail.parsed);
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

const RELATION_LABEL = {
  self: "본인",
  son: "아들",
  daughter: "딸",
  brother: "형제",
  sister: "자매",
  sibling: "형제/자매",
  grandson: "손자",
  granddaughter: "손녀",
  descendant: "후손",
  spouse: "배우자",
  son_in_law: "사위",
  daughter_in_law: "며느리",
  unknown: "미상",
};

const RELATION_OPTIONS = Object.keys(RELATION_LABEL).map((value) => ({
  value,
  label: RELATION_LABEL[value],
}));
// 기준 인물은 subjects[]에만 두므로 entries에는 self를 허용하지 않는다.
const ENTRY_RELATION_OPTIONS = RELATION_OPTIONS.filter((option) => option.value !== "self");

function text(value) {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function appendField(container, label, value) {
  const normalized = text(value);
  if (normalized === null) return;
  const row = document.createElement("div");
  row.className = "struct-field";
  const dt = document.createElement("span");
  dt.className = "struct-label";
  dt.textContent = label;
  const dd = document.createElement("span");
  dd.className = "struct-value";
  dd.textContent = normalized;
  row.append(dt, dd);
  container.append(row);
}

function appendList(container, label, values) {
  const filtered = (values || []).map(text).filter(Boolean);
  if (!filtered.length) return;
  appendField(container, label, filtered.join(" · "));
}

function dateText(value) {
  if (!value) return null;
  const parts = [value.raw, value.king_era, value.ganji, value.date_text].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function burialText(value) {
  if (!value) return null;
  const parts = [value.raw];
  if (value.location) parts.push(`위치: ${value.location}`);
  if (value.orientation) parts.push(`방향: ${value.orientation}`);
  if (value.note) parts.push(`비고: ${value.note}`);
  return parts.filter(Boolean).join(" · ");
}

function pageRefText(value) {
  if (!value) return null;
  return `${value.raw || ""} → ${value.target_section || ""} ${value.target_page_no || ""}`.trim();
}

function syncJsonFromParsed() {
  if (!state.detail || !state.detail.parsed) return;
  const editor = $("#json-editor");
  editor.value = JSON.stringify(state.detail.parsed, null, 2);
  state.dirty = true;
  setSaveState("수정됨 (저장 필요)");
}

function makeField(container, label, value, onInput, options = {}) {
  const row = document.createElement("div");
  row.className = "struct-field";
  const dt = document.createElement("span");
  dt.className = "struct-label";
  dt.textContent = label;
  const input = document.createElement("input");
  input.type = options.number ? "number" : (options.type || "text");
  input.className = "struct-input";
  input.value = value === null || value === undefined ? "" : value;
  if (options.placeholder) input.placeholder = options.placeholder;
  const update = () => {
    let next = input.value;
    if (options.number) next = next.trim() === "" ? null : Number(next);
    if (options.nullable && next === "") next = null;
    onInput(next);
    syncJsonFromParsed();
  };
  input.addEventListener("input", update);
  input.addEventListener("change", update);
  row.append(dt, input);
  container.append(row);
  return input;
}

function makeSelect(container, label, value, choices, onInput) {
  const row = document.createElement("div");
  row.className = "struct-field";
  const dt = document.createElement("span");
  dt.className = "struct-label";
  dt.textContent = label;
  const select = document.createElement("select");
  select.className = "struct-input";
  for (const choice of choices) {
    const option = document.createElement("option");
    option.value = choice.value;
    option.textContent = choice.label;
    select.append(option);
  }
  select.value = value || choices[0].value;
  select.addEventListener("change", () => {
    onInput(select.value);
    syncJsonFromParsed();
  });
  row.append(dt, select);
  container.append(row);
  return select;
}

function makeTextareaField(container, label, values, onInput, placeholder = "") {
  const row = document.createElement("div");
  row.className = "struct-field struct-field-block";
  const dt = document.createElement("span");
  dt.className = "struct-label";
  dt.textContent = label;
  const textarea = document.createElement("textarea");
  textarea.className = "struct-textarea struct-textarea-small";
  textarea.value = Array.isArray(values) ? values.join("\\n") : (values || "");
  textarea.placeholder = placeholder;
  const update = () => {
    const lines = textarea.value.split("\\n").map((line) => line.trim()).filter(Boolean);
    onInput(lines);
    syncJsonFromParsed();
  };
  textarea.addEventListener("input", update);
  textarea.addEventListener("change", update);
  row.append(dt, textarea);
  container.append(row);
  return textarea;
}

function renderAliasesEditor(container, person) {
  if (!Array.isArray(person.aliases)) person.aliases = [];
  const wrap = document.createElement("div");
  wrap.className = "struct-sublist";
  const label = document.createElement("div");
  label.className = "struct-subtitle";
  label.textContent = "자/호";
  wrap.append(label);
  const list = document.createElement("div");
  wrap.append(list);
  const rebuild = () => {
    list.replaceChildren();
    person.aliases.forEach((alias, index) => {
      const row = document.createElement("div");
      row.className = "struct-alias-row";
      const typeSelect = document.createElement("select");
      typeSelect.className = "struct-input struct-input-small";
      for (const type of ["字", "號", "其他"]) {
        const option = document.createElement("option");
        option.value = type;
        option.textContent = type;
        typeSelect.append(option);
      }
      typeSelect.value = alias.type || "字";
      typeSelect.addEventListener("change", () => {
        alias.type = typeSelect.value;
        syncJsonFromParsed();
      });
      const valueInput = document.createElement("input");
      valueInput.type = "text";
      valueInput.className = "struct-input";
      valueInput.value = alias.value || "";
      valueInput.addEventListener("input", () => {
        alias.value = valueInput.value;
        syncJsonFromParsed();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "struct-remove";
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        person.aliases.splice(index, 1);
        rebuild();
        syncJsonFromParsed();
      });
      row.append(typeSelect, valueInput, remove);
      list.append(row);
    });
  };
  rebuild();
  const add = document.createElement("button");
  add.type = "button";
  add.className = "struct-add";
  add.textContent = "+ 자/호";
  add.addEventListener("click", () => {
    person.aliases.push({ type: "字", value: "" });
    rebuild();
    syncJsonFromParsed();
  });
  wrap.append(add);
  container.append(wrap);
}

function renderSpousesEditor(container, person) {
  if (!Array.isArray(person.spouses)) person.spouses = [];
  const wrap = document.createElement("div");
  wrap.className = "struct-sublist";
  const label = document.createElement("div");
  label.className = "struct-subtitle";
  label.textContent = "배우자";
  wrap.append(label);
  const list = document.createElement("div");
  wrap.append(list);
  const rebuild = () => {
    list.replaceChildren();
    person.spouses.forEach((spouse, index) => {
      if (!spouse || typeof spouse !== "object") person.spouses[index] = { as_printed: "" };
      const s = person.spouses[index];
      const card = document.createElement("div");
      card.className = "struct-subcard";
      makeField(card, "이름", s.as_printed, (v) => { s.as_printed = v; }, { nullable: true });
      makeField(card, "한자", s.name_hanja, (v) => { s.name_hanja = v; }, { nullable: true });
      makeField(card, "본관", s.bonkwan, (v) => { s.bonkwan = v; }, { nullable: true });
      makeField(card, "부", s.father, (v) => { s.father = v; }, { nullable: true });
      makeSelect(card, "관계", s.relation || "wife", [
        { value: "wife", label: "wife" },
        { value: "husband", label: "husband" },
        { value: "concubine", label: "concubine" },
        { value: "unknown", label: "unknown" },
      ], (v) => { s.relation = v; });
      if (!s.birth || typeof s.birth !== "object") s.birth = { raw: null };
      makeField(card, "생 원문", s.birth.raw, (v) => { s.birth.raw = v; }, { nullable: true });
      makeField(card, "생 간지", s.birth.ganji, (v) => { s.birth.ganji = v; }, { nullable: true });
      makeField(card, "생 날짜", s.birth.date_text, (v) => { s.birth.date_text = v; }, { nullable: true });
      makeField(card, "생 연호", s.birth.king_era, (v) => { s.birth.king_era = v; }, { nullable: true });
      if (!s.death || typeof s.death !== "object") s.death = { raw: null };
      makeField(card, "졸 원문", s.death.raw, (v) => { s.death.raw = v; }, { nullable: true });
      makeField(card, "졸 간지", s.death.ganji, (v) => { s.death.ganji = v; }, { nullable: true });
      makeField(card, "졸 날짜", s.death.date_text, (v) => { s.death.date_text = v; }, { nullable: true });
      makeField(card, "졸 연호", s.death.king_era, (v) => { s.death.king_era = v; }, { nullable: true });
      if (!s.burial || typeof s.burial !== "object") s.burial = { raw: null };
      makeField(card, "묘 원문", s.burial.raw, (v) => { s.burial.raw = v; }, { nullable: true });
      makeField(card, "묘 위치", s.burial.location, (v) => { s.burial.location = v; }, { nullable: true });
      makeField(card, "묘 방향", s.burial.orientation, (v) => { s.burial.orientation = v; }, { nullable: true });
      makeField(card, "묘 비고", s.burial.note, (v) => { s.burial.note = v; }, { nullable: true });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "struct-remove";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => {
        person.spouses.splice(index, 1);
        rebuild();
        syncJsonFromParsed();
      });
      card.append(remove);
      list.append(card);
    });
  };
  rebuild();
  const add = document.createElement("button");
  add.type = "button";
  add.className = "struct-add";
  add.textContent = "+ 배우자";
  add.addEventListener("click", () => {
    person.spouses.push({ as_printed: "", relation: "wife" });
    rebuild();
    syncJsonFromParsed();
  });
  wrap.append(add);
  container.append(wrap);
}

function renderChildrenEditor(container, person) {
  if (!Array.isArray(person.children)) person.children = [];
  const wrap = document.createElement("div");
  wrap.className = "struct-sublist";
  const label = document.createElement("div");
  label.className = "struct-subtitle";
  label.textContent = "자녀";
  wrap.append(label);
  const list = document.createElement("div");
  wrap.append(list);
  const rebuild = () => {
    list.replaceChildren();
    person.children.forEach((child, index) => {
      if (!child || typeof child !== "object") person.children[index] = { as_printed: "" };
      const c = person.children[index];
      const card = document.createElement("div");
      card.className = "struct-subcard";
      makeField(card, "이름", c.as_printed, (v) => { c.as_printed = v; }, { nullable: true });
      makeField(card, "한자", c.name_hanja, (v) => { c.name_hanja = v; }, { nullable: true });
      makeField(card, "접두", c.prefix, (v) => { c.prefix = v; }, { nullable: true });
      makeSelect(card, "관계", c.relation || "son", [
        { value: "son", label: "son" },
        { value: "daughter", label: "daughter" },
        { value: "adopted_son", label: "adopted_son" },
        { value: "unknown", label: "unknown" },
      ], (v) => { c.relation = v; });
      if (!c.page_ref || typeof c.page_ref !== "object") c.page_ref = null;
      makeField(card, "페이지 참조", c.page_ref ? c.page_ref.raw : null, (v) => {
        if (!v) { c.page_ref = null; return; }
        if (!c.page_ref) c.page_ref = { raw: v, direction: "down", target_section: "genealogy", target_page_no: 1 };
        else c.page_ref.raw = v;
      }, { nullable: true });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "struct-remove";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => {
        person.children.splice(index, 1);
        rebuild();
        syncJsonFromParsed();
      });
      card.append(remove);
      list.append(card);
    });
  };
  rebuild();
  const add = document.createElement("button");
  add.type = "button";
  add.className = "struct-add";
  add.textContent = "+ 자녀";
  add.addEventListener("click", () => {
    person.children.push({ as_printed: "", relation: "son" });
    rebuild();
    syncJsonFromParsed();
  });
  wrap.append(add);
  container.append(wrap);
}

function renderPersonCard(container, person, embedded = false) {
  if (!person || typeof person !== "object") return;
  const card = embedded ? container : document.createElement("article");
  if (!embedded) card.className = "struct-card";

  if (!embedded) {
    const title = document.createElement("div");
    title.className = "struct-card-title";
    title.textContent = person.as_printed || "(이름 없음)";
    if (person.needs_human) {
      const badge = document.createElement("span");
      badge.className = "struct-badge bad";
      badge.textContent = "확인 필요";
      title.append(badge);
    }
    card.append(title);
  }

  makeField(card, "이름", person.as_printed, (v) => { person.as_printed = v; });
  makeField(card, "한자", person.name_hanja, (v) => { person.name_hanja = v; }, { nullable: true });
  makeField(card, "한글", person.name_hangul, (v) => { person.name_hangul = v; }, { nullable: true });
  makeField(card, "접두", person.prefix, (v) => { person.prefix = v; }, { nullable: true });
  makeField(card, "세대", person.generation_no, (v) => { person.generation_no = v; }, { number: true, nullable: true });
  makeField(card, "항렬자", person.generation_char, (v) => { person.generation_char = v; }, { nullable: true });

  renderAliasesEditor(card, person);

  if (!person.birth || typeof person.birth !== "object") person.birth = { raw: null };
  makeField(card, "생 원문", person.birth.raw, (v) => { person.birth.raw = v; }, { nullable: true });
  makeField(card, "생 간지", person.birth.ganji, (v) => { person.birth.ganji = v; }, { nullable: true });
  makeField(card, "생 날짜", person.birth.date_text, (v) => { person.birth.date_text = v; }, { nullable: true });
  makeField(card, "생 연호", person.birth.king_era, (v) => { person.birth.king_era = v; }, { nullable: true });

  if (!person.death || typeof person.death !== "object") person.death = { raw: null };
  makeField(card, "졸 원문", person.death.raw, (v) => { person.death.raw = v; }, { nullable: true });
  makeField(card, "졸 간지", person.death.ganji, (v) => { person.death.ganji = v; }, { nullable: true });
  makeField(card, "졸 날짜", person.death.date_text, (v) => { person.death.date_text = v; }, { nullable: true });
  makeField(card, "졸 연호", person.death.king_era, (v) => { person.death.king_era = v; }, { nullable: true });

  if (!person.burial || typeof person.burial !== "object") person.burial = { raw: null };
  makeField(card, "묘 원문", person.burial.raw, (v) => { person.burial.raw = v; }, { nullable: true });
  makeField(card, "묘 위치", person.burial.location, (v) => { person.burial.location = v; }, { nullable: true });
  makeField(card, "묘 방향", person.burial.orientation, (v) => { person.burial.orientation = v; }, { nullable: true });
  makeField(card, "묘 비고", person.burial.note, (v) => { person.burial.note = v; }, { nullable: true });

  makeTextareaField(card, "관직", person.offices, (v) => { person.offices = v; }, "한 줄에 하나");
  makeTextareaField(card, "메모", person.notes, (v) => { person.notes = v; }, "한 줄에 하나");

  if (!person.page_ref || typeof person.page_ref !== "object") person.page_ref = null;
  makeField(card, "페이지 참조", person.page_ref ? person.page_ref.raw : null, (v) => {
    if (!v) { person.page_ref = null; return; }
    if (!person.page_ref) person.page_ref = { raw: v, direction: "down", target_section: "genealogy", target_page_no: 1 };
    else person.page_ref.raw = v;
  }, { nullable: true });

  const needs = document.createElement("label");
  needs.className = "struct-checkbox";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = !!person.needs_human;
  checkbox.addEventListener("change", () => {
    person.needs_human = checkbox.checked;
    syncJsonFromParsed();
  });
  needs.append(checkbox, document.createTextNode(" 사람 확인 필요"));
  card.append(needs);

  renderSpousesEditor(card, person);
  renderChildrenEditor(card, person);

  if (!embedded) container.append(card);
}

function renderStructure(parsed) {
  const container = $("#structure-view");
  container.replaceChildren();
  if (!parsed) {
    const empty = document.createElement("div");
    empty.className = "structure-empty";
    empty.textContent = "파싱 결과가 없습니다.";
    container.append(empty);
    return;
  }

  const pageSection = document.createElement("section");
  pageSection.className = "struct-section";
  const pageHeading = document.createElement("h3");
  pageHeading.textContent = "페이지 정보";
  pageSection.append(pageHeading);
  const pageCard = document.createElement("div");
  pageCard.className = "struct-card";
  appendField(pageCard, "구분", parsed.page && parsed.page.section === "frontmatter" ? "전편" : "본편");
  appendField(pageCard, "면번호", parsed.page && parsed.page.printed_page_no);
  appendField(pageCard, "유형", parsed.page && (TYPE_LABEL[parsed.page.page_type] || parsed.page.page_type));
  if (parsed.page && parsed.page.quality) {
    appendField(pageCard, "품질", [
      parsed.page.quality.blur ? `흐림 ${parsed.page.quality.blur}` : null,
      parsed.page.quality.bleed_through ? `비침 ${parsed.page.quality.bleed_through}` : null,
      parsed.page.quality.needs_human ? "사람 확인 필요" : null,
    ].filter(Boolean).join(" · ") || "양호");
  }
  if (parsed.page && parsed.page.header) {
    appendField(pageCard, "면머리", parsed.page.header.running_head);
    appendField(pageCard, "부", parsed.page.header.father_name);
    if (Array.isArray(parsed.page.header.notes)) appendField(pageCard, "주기", parsed.page.header.notes.join(" · "));
  }
  pageSection.append(pageCard);
  container.append(pageSection);

  if (Array.isArray(parsed.subjects) && parsed.subjects.length) {
    const section = document.createElement("section");
    section.className = "struct-section";
    const heading = document.createElement("h3");
    heading.textContent = "기준 인물";
    section.append(heading);
    for (const subject of parsed.subjects) {
      const card = document.createElement("article");
      card.className = "struct-card";
      const title = document.createElement("div");
      title.className = "struct-card-title";
      title.textContent = subject.as_printed || "(기준 인물)";
      if (subject.needs_human) {
        const badge = document.createElement("span");
        badge.className = "struct-badge bad";
        badge.textContent = "확인 필요";
        title.append(badge);
      }
      card.append(title);
      makeField(card, "단(row)", subject.row, (v) => { subject.row = v; }, { number: true, nullable: true });
      makeField(card, "열(column)", subject.column, (v) => { subject.column = v; }, { number: true, nullable: true });
      makeSelect(card, "관계", subject.relation_to_subject || "self", RELATION_OPTIONS, (v) => { subject.relation_to_subject = v; });
      makeField(card, "세대 차이", subject.generation_offset, (v) => { subject.generation_offset = v; }, { number: true, nullable: true });
      renderPersonCard(card, subject, true);
      section.append(card);
    }
    container.append(section);
  }

  if (Array.isArray(parsed.entries) && parsed.entries.length) {
    const rows = new Map();
    for (const entry of parsed.entries) {
      const row = Number.isInteger(entry.row) ? entry.row : "?";
      if (!rows.has(row)) rows.set(row, []);
      rows.get(row).push(entry);
    }
    const section = document.createElement("section");
    section.className = "struct-section";
    const heading = document.createElement("h3");
    heading.textContent = `인물 목록 (${parsed.entries.length}명)`;
    section.append(heading);
    for (const row of [...rows.keys()].sort((a, b) => a - b)) {
      const group = document.createElement("div");
      group.className = "struct-row-group";
      const rowTitle = document.createElement("h4");
      rowTitle.textContent = `${row}단`;
      group.append(rowTitle);
      const entries = rows.get(row).slice().sort((a, b) => (a.column || 0) - (b.column || 0));
      for (const entry of entries) {
        const card = document.createElement("article");
        card.className = "struct-card";
        const title = document.createElement("div");
        title.className = "struct-card-title";
        title.textContent = (entry.person && entry.person.as_printed) || "(이름 없음)";
        const badge = document.createElement("span");
        badge.className = "struct-badge";
        badge.textContent = `${RELATION_LABEL[entry.relation_to_subject] || entry.relation_to_subject || "미상"} · 열 ${entry.column || "?"}`;
        title.append(badge);
        if (entry.needs_human || (entry.person && entry.person.needs_human)) {
          const warn = document.createElement("span");
          warn.className = "struct-badge bad";
          warn.textContent = "확인 필요";
          title.append(warn);
        }
        card.append(title);
        makeField(card, "단(row)", entry.row, (v) => { entry.row = v; }, { number: true, nullable: true });
        makeField(card, "열(column)", entry.column, (v) => { entry.column = v; }, { number: true, nullable: true });
        makeSelect(card, "관계", entry.relation_to_subject || "unknown", ENTRY_RELATION_OPTIONS, (v) => { entry.relation_to_subject = v; });
        makeField(card, "세대 차이", entry.generation_offset, (v) => { entry.generation_offset = v; }, { number: true, nullable: true });

        const needs = document.createElement("label");
        needs.className = "struct-checkbox";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = !!entry.needs_human;
        checkbox.addEventListener("change", () => {
          entry.needs_human = checkbox.checked;
          syncJsonFromParsed();
        });
        needs.append(checkbox, document.createTextNode(" 사람 확인 필요"));
        card.append(needs);

        renderPersonCard(card, entry.person || {}, true);
        // remove duplicate title by not rendering as_printed again? person card already has title; keep compact by hiding nested title? We'll leave as nested card.
        group.append(card);
      }
      section.append(group);
    }
    container.append(section);
  }

  const generic = document.createElement("section");
  generic.className = "struct-section";
  let hasGeneric = false;
  function addGeneric(title, content) {
    if (!content) return;
    if (!hasGeneric) {
      const heading = document.createElement("h3");
      heading.textContent = "기타 정보";
      generic.append(heading);
      hasGeneric = true;
    }
    const card = document.createElement("div");
    card.className = "struct-card";
    const h = document.createElement("div");
    h.className = "struct-card-title";
    h.textContent = title;
    card.append(h);
    if (typeof content === "string") {
      const p = document.createElement("div");
      p.className = "struct-generic";
      p.textContent = content;
      card.append(p);
    } else {
      card.append(content);
    }
    generic.append(card);
  }

  if (Array.isArray(parsed.captions) && parsed.captions.length) {
    addGeneric("캡션", parsed.captions.map((item) => item.raw).filter(Boolean).join(" · "));
  }
  if (Array.isArray(parsed.index_entries) && parsed.index_entries.length) {
    addGeneric("색인", parsed.index_entries.map((item) => `${item.name_hanja || ""}${item.page_ref ? ` (${item.page_ref.raw || ""})` : ""}`).filter(Boolean).join(" · "));
  }
  if (Array.isArray(parsed.annotations) && parsed.annotations.length) {
    addGeneric("주석", parsed.annotations.map((item) => item.raw).filter(Boolean).join(" · "));
  }
  if (Array.isArray(parsed.page_texts) && parsed.page_texts.length) {
    addGeneric("본문 텍스트", parsed.page_texts.map((item) => item.raw).filter(Boolean).join(" · "));
  }
  if (Array.isArray(parsed.generation_chars) && parsed.generation_chars.length) {
    addGeneric("항렬", parsed.generation_chars.map((item) => `${item.generation_no ?? ""}: ${(item.chars || []).join("")}`).filter(Boolean).join(" · "));
  }
  if (Array.isArray(parsed.tables) && parsed.tables.length) {
    addGeneric("표", parsed.tables.map((item) => `${item.title || "표"} (${(item.rows || []).length}행)`).join(" · "));
  }
  if (Array.isArray(parsed.unreadable_regions) && parsed.unreadable_regions.length) {
    addGeneric("판독 불가", parsed.unreadable_regions.map((item) => item.reason).join(" · "));
  }
  if (hasGeneric) container.append(generic);
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
  const next = Math.min(12, Math.max(0.2, state.zoom * factor));
  state.zoom = next;
  applyTransform();
}

function zoomTo(value) {
  state.zoom = Math.min(12, Math.max(0.2, value));
  state.tx = 0;
  state.ty = 0;
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

  function bindRepeatZoom(button, factor) {
    let timer = null;
    let interval = null;
    let repeated = false;
    const action = () => zoomBy(factor);
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      repeated = false;
      action();
      timer = setTimeout(() => {
        repeated = true;
        interval = setInterval(action, 110);
      }, 260);
    });
    const stop = () => {
      clearTimeout(timer);
      clearInterval(interval);
      timer = null;
      interval = null;
    };
    button.addEventListener("pointerup", stop);
    button.addEventListener("pointerleave", stop);
    button.addEventListener("pointercancel", stop);
    button.addEventListener("click", (event) => {
      if (repeated) {
        repeated = false;
        event.preventDefault();
      }
    });
  }
  bindRepeatZoom($("#zoom-in"), 1.2);
  bindRepeatZoom($("#zoom-out"), 1 / 1.2);
  $("#zoom-100").addEventListener("click", () => zoomTo(1));
  $("#zoom-200").addEventListener("click", () => zoomTo(2));
  $("#zoom-400").addEventListener("click", () => zoomTo(4));
  $("#zoom-fit").addEventListener("click", resetZoom);
  $("#zoom-actual").addEventListener("click", () => {
    const image = $("#page-image");
    const stage = $("#image-stage");
    if (!image.naturalWidth || !stage.clientWidth) {
      zoomTo(1);
      return;
    }
    const scale = Math.max(image.naturalWidth / stage.clientWidth, image.naturalHeight / stage.clientHeight);
    zoomTo(Math.max(1, scale));
  });
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
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomBy(1.25);
      return;
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoomBy(1 / 1.25);
      return;
    } else if (event.key === "0") {
      event.preventDefault();
      resetZoom();
      return;
    }
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
