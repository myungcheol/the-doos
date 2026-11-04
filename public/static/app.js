"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

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

const RELATION_LABEL = {
  self: "기준 인물",
  son: "아들",
  daughter: "딸",
  brother: "남동생",
  sister: "여동생",
  sibling: "동생",
  grandson: "손자",
  granddaughter: "고모 손자",
  descendant: "자손",
  spouse: "배우자",
  son_in_law: "사위(장손)",
  daughter_in_law: "사위(장손)",
  unknown: "미확인",
};

const state = {
  items: [],
  current: null,
  detail: null,
  zoom: 1,
  tx: 0,
  ty: 0,
  dragging: false,
  drag: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = payload && payload.error ? payload.error : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

// ---------- 목록 ----------

function renderStats(pages) {
  const people = pages.reduce((sum, item) => sum + (item.person_count || 0), 0);
  const needs = pages.reduce((sum, item) => sum + (item.needs_human || 0), 0);
  const container = $("#stats");
  container.replaceChildren();
  for (const [label, value] of [
    ["승인", pages.length],
    ["인물", people],
    ["검수필요", needs],
  ]) {
    const span = document.createElement("span");
    span.append(`${label} `);
    const b = document.createElement("b");
    b.textContent = String(value);
    span.append(b);
    container.append(span);
  }
}

function renderList() {
  const list = $("#page-list");
  list.replaceChildren();
  const query = $("#search").value.trim().toLowerCase();
  const items = state.items.filter((item) => {
    const label = `${item.section} ${item.printed_page_no} ${item.page_type}`.toLowerCase();
    return !query || label.includes(query);
  });
  $("#list-count").textContent = `${items.length}면`;

  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-item";
    button.dataset.section = item.section;
    button.dataset.no = String(item.printed_page_no);
    button.addEventListener("click", () => {
      location.hash = `#/page/${item.section}/${item.printed_page_no}`;
    });
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = String(item.printed_page_no).padStart(4, "0");
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${TYPE_LABEL[item.page_type] || item.page_type} · 인물 ${item.person_count || 0}`;
    button.append(no, meta);
    fragment.append(button);
  }
  list.append(fragment);
}

async function loadPages() {
  const data = await api("/api/pages");
  state.items = data.pages || [];
  renderStats(state.items);
  renderList();
}

// ---------- 상세 ----------

function setPageTitle(detail) {
  const label = TYPE_LABEL[detail.page_type] || detail.page_type;
  $("#page-title").textContent = `${detail.section} ${String(detail.printed_page_no).padStart(4, "0")} · ${label}`;
  const meta = [];
  if (detail.image_width) meta.push(`이미지 ${detail.image_width}×${detail.image_height}`);
  if (detail.people) meta.push(`인물 ${detail.people.length}명`);
  $("#page-meta").textContent = meta.join(" · ");
}

function renderPeople(detail) {
  const box = $("#people-list");
  box.replaceChildren();
  const people = detail.people || [];
  if (!people.length) {
    box.append(textNode("이 페이지에 승인된 인물이 없습니다."));
    return;
  }
  for (const person of people) {
    box.append(renderPerson(person));
  }
}

function textNode(text) {
  const node = document.createTextNode(text);
  return node;
}

function renderPerson(person) {
  const item = document.createElement("div");
  item.className = "person" + (person.is_subject ? " subject" : "");

  const head = document.createElement("div");
  head.className = "person-head";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = person.as_printed || person.name_hanja || "?";
  head.append(name);
  if (person.name_hanja) {
    const hanja = document.createElement("span");
    hanja.className = "hanja";
    hanja.textContent = person.name_hanja;
    head.append(hanja);
  }
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = person.generation_no ? `${person.generation_no}세대` : "세대?";
  head.append(badge);
  item.append(head);

  const meta = document.createElement("div");
  meta.className = "person-meta";
  const parts = [RELATION_LABEL[person.page_relation] || "미확인"];
  if (person.row_no) parts.push(`단 ${person.row_no} / 열 ${person.column_no}`);
  meta.textContent = parts.join(" · ");
  item.append(meta);

  const rows = document.createElement("div");
  rows.className = "person-rows";

  const fatherRow = document.createElement("div");
  fatherRow.append("아버지: ");
  if (person.father && person.father.as_printed) {
    fatherRow.append(`${person.father.as_printed} (근거: ${person.father.source || "unknown"})`);
  } else {
    fatherRow.append("미확인");
  }
  rows.append(fatherRow);

  const spouses = person.spouses || [];
  for (const spouse of spouses) {
    const row = document.createElement("div");
    row.append(
      `배우자: ${spouse.spouse_as_printed || spouse.spouse_name_hanja || "?"} (${spouse.relation || "unknown"})`
    );
    rows.append(row);
  }

  const burials = person.burial || [];
  for (const burial of burials) {
    const row = document.createElement("div");
    row.append(`묘소: ${burial.burial_raw || burial.location || "?"}`);
    rows.append(row);
  }

  item.append(rows);
  return item;
}

async function loadPage(section, pageNo) {
  state.current = { section, page_no: pageNo };
  const detail = await api(`/api/pages/${section}/${pageNo}`);
  state.detail = detail;
  setPageTitle(detail);
  renderPeople(detail);
  await loadImage(section, pageNo);
}

// ---------- 이미지 + 확대/축소 ----------

function applyTransform() {
  const image = $("#page-image");
  if (!image) return;
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

function bindImageEvents() {
  const stage = $("#image-stage");
  const image = $("#page-image");
  if (!stage || !image) return;

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

async function loadImage(section, pageNo) {
  const image = $("#page-image");
  const empty = $("#image-empty");
  const loading = $("#image-loading");
  const stage = $("#image-stage");
  if (stage) stage.classList.remove("dragging");
  image.onload = () => {
    if (loading) loading.remove();
    bindImageEvents();
    applyTransform();
  };
  image.onerror = () => {
    if (empty) empty.classList.remove("hidden");
    const msg = document.createElement("div");
    msg.className = "image-empty";
    msg.textContent = "이미지를 불러올 수 없습니다";
    empty.replaceWith(msg);
  };
  if (image.dataset.url !== `/images/${section}/${pageNo}.jpg`) {
    image.dataset.url = `/images/${section}/${pageNo}.jpg`;
    image.src = `/images/${section}/${pageNo}.jpg`;
  }
  if (empty) empty.classList.add("hidden");
}

// ---------- 라우팅 ----------

async function route() {
  const match = location.hash.match(/^#\/page\/([^/]+)\/(\d+)$/);
  if (match) {
    await loadPage(match[1], Number(match[2]));
    return;
  }
  await loadPages();
}

window.addEventListener("hashchange", () => {
  route().catch(() => {});
});
window.addEventListener("load", () => {
  route().catch(() => {});
});

$("#search").addEventListener("input", () => {
  renderList();
});
