"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  ChevronRight,
  FileText,
  GitBranch,
  Library,
  LoaderCircle,
  Search,
  Users,
  X,
} from "lucide-react";
import type {
  Edition,
  Listing,
  PageDetail,
  PageSummary,
  PersonDetail,
  PersonSummary,
} from "@/lib/types";
import ScanViewer from "./ScanViewer";
import FamilyTree, { api } from "./FamilyTree";

const labels: Record<string, string> = {
  generation_number: "세대",
  courtesy_name_hanja: "자 (字)",
  pen_name_hanja: "호 (號)",
  birth_text: "출생",
  death_text: "사망",
  office_title: "관직",
  burial_text: "묘소",
  biography_text: "인물 기록",
};
const partnerKinds: Record<string, string> = {
  wife: "부인",
  concubine: "첩",
  husband: "남편",
  other: "배우자",
};
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge ${status === "confirmed" ? "verified" : "draft"}`}>
      {status === "confirmed" ? "이름 확인" : "검토 대기"}
    </span>
  );
}
function Loading() {
  return (
    <div className="empty" role="status">
      <LoaderCircle size={25} className="spin" />
      <p>기록을 불러오고 있습니다</p>
    </div>
  );
}

export default function Reader() {
  const [editions, setEditions] = useState<Edition[]>([]);
  const [edition, setEdition] = useState("");
  const [pageList, setPageList] = useState<Listing<PageSummary>>({
    items: [],
    hasMore: false,
    nextOffset: 0,
  });
  const [pageOffset, setPageOffset] = useState(0);
  const [pageFilter, setPageFilter] = useState("");
  const [pageId, setPageId] = useState("");
  const [page, setPage] = useState<PageDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [tab, setTab] = useState<"record" | "family">("record");
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [results, setResults] = useState<Listing<PersonSummary> | null>(null);
  const [searchOffset, setSearchOffset] = useState(0);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [error, setError] = useState("");
  const [pageError, setPageError] = useState("");
  const [personError, setPersonError] = useState("");
  const [pagesBusy, setPagesBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const initial = useRef<{ page: string; person: string } | null>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const c = new AbortController();
    const params = new URLSearchParams(window.location.search);
    initial.current = {
      page: params.get("page") || "",
      person: params.get("person") || "",
    };
    setError("");
    api<Edition[]>("/api/editions", c.signal)
      .then((data) => {
        setEditions(data);
        const eid =
          data.find((e) => e.id === params.get("edition"))?.id ||
          data[0]?.id ||
          "";
        setEdition(eid);
        if (initial.current?.page) setPageId(initial.current.page);
        if (initial.current?.person) setSelected(initial.current.person);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [retry]);

  useEffect(() => {
    if (!edition) return;
    const c = new AbortController();
    setPagesBusy(true);
    const timer = setTimeout(
      () => {
        api<Listing<PageSummary>>(
          `/api/pages?edition=${encodeURIComponent(edition)}&offset=${pageOffset}&q=${encodeURIComponent(pageFilter)}`,
          c.signal,
        )
          .then((data) => {
            setPageList((old) => ({
              ...data,
              items: pageOffset ? [...old.items, ...data.items] : data.items,
            }));
            if (!pageId && !initial.current?.person && data.items[0])
              setPageId(data.items[0].id);
          })
          .catch((e) => {
            if (e.name !== "AbortError") setError(e.message);
          })
          .finally(() => {
            if (!c.signal.aborted) setPagesBusy(false);
          });
      },
      pageFilter ? 200 : 0,
    );
    return () => {
      clearTimeout(timer);
      c.abort();
    };
    // pageId deliberately excluded: changing pages must not reload the catalog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edition, pageOffset, pageFilter, retry]);

  useEffect(() => {
    if (!pageId || !edition) return;
    const c = new AbortController();
    setPage(null);
    setPageError("");
    api<PageDetail>(`/api/pages/${pageId}`, c.signal)
      .then((data) => {
        if (data.edition !== edition) {
          setPageError("선택한 판본의 페이지가 아닙니다.");
          return;
        }
        setPage(data);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setPageError(e.message);
      });
    return () => c.abort();
  }, [pageId, edition, retry]);

  useEffect(() => {
    setDetail(null);
    setPersonError("");
    if (!selected || !edition) return;
    const c = new AbortController();
    api<PersonDetail>(
      `/api/people/${selected}?edition=${encodeURIComponent(edition)}`,
      c.signal,
    )
      .then((data) => {
        setDetail(data);
        if (!pageId && data.sources[0]) setPageId(data.sources[0].pageId);
        initial.current = null;
      })
      .catch((e) => {
        if (e.name !== "AbortError") setPersonError(e.message);
      });
    return () => c.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, edition, retry]);

  useEffect(() => {
    if (!edition) return;
    const params = new URLSearchParams({ edition });
    if (pageId) params.set("page", pageId);
    if (selected) params.set("person", selected);
    window.history.replaceState(null, "", `?${params}`);
  }, [edition, pageId, selected]);

  useEffect(() => {
    if (!searchTerm || !edition) {
      setResults(null);
      return;
    }
    const c = new AbortController();
    setSearchBusy(true);
    setSearchError("");
    api<Listing<PersonSummary>>(
      `/api/people?edition=${encodeURIComponent(edition)}&q=${encodeURIComponent(searchTerm)}&offset=${searchOffset}`,
      c.signal,
    )
      .then((data) =>
        setResults((old) => ({
          ...data,
          items: searchOffset
            ? [...(old?.items || []), ...data.items]
            : data.items,
        })),
      )
      .catch((e) => {
        if (e.name !== "AbortError") setSearchError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setSearchBusy(false);
      });
    return () => c.abort();
  }, [edition, searchTerm, searchOffset, retry]);

  function choose(p: PersonSummary) {
    setSelected(p.id);
    setPageId(p.pageId);
    setSearchTerm("");
    setResults(null);
  }
  function selectPage(id: string) {
    setPageId(id);
    setSelected(null);
    setTab("record");
  }
  function changeEdition(id: string) {
    setEdition(id);
    setPageId("");
    setPage(null);
    setSelected(null);
    setPageOffset(0);
    setPageFilter("");
    setPageList({ items: [], hasMore: false, nextOffset: 0 });
    setSearchTerm("");
    initial.current = null;
  }
  const currentEdition = editions.find((e) => e.id === edition);
  const currentIndex = pageList.items.findIndex((p) => p.id === pageId);
  const source =
    detail?.sources.find((s) => s.pageId === pageId) || detail?.sources[0];

  return (
    <div className="reader-app">
      <header className="site-header">
        <a className="brand" href="/" aria-label="족보 열람실 첫 화면">
          <span className="seal">杜</span>
          <span>
            <strong>두씨 족보 열람실</strong>
            <small>THE DOO FAMILY ARCHIVE</small>
          </span>
        </a>
        <form
          className="global-search"
          onSubmit={(e) => {
            e.preventDefault();
            setSearchOffset(0);
            setResults(null);
            setSearchTerm(query.trim());
          }}
          role="search"
        >
          <Search size={18} />
          <input
            aria-label="인물 이름 검색"
            placeholder="족보 속 인물 이름을 찾아보세요"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={80}
          />
          <button type="submit" disabled={!edition || !query.trim()}>
            검색
          </button>
        </form>
        <span className="header-note">
          <Library size={16} />
          세대를 잇는 기록
        </span>
      </header>
      <main>
        <div className="collection-heading">
          <div>
            <div className="eyebrow">FAMILY RECORDS · 原本 열람</div>
            <h1>
              기록에서 만나는 우리의 뿌리<span>杜氏世譜</span>
            </h1>
          </div>
          <div className="edition-select">
            <label htmlFor="edition">열람 중인 판본</label>
            <select
              id="edition"
              value={edition}
              onChange={(e) => changeEdition(e.target.value)}
            >
              {!editions.length && <option value="">판본 선택</option>}
              {editions.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.year ? `${e.year}년 발행` : e.id}
                  {e.volume ? ` · ${e.volume}권` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        {error ? (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => setRetry((r) => r + 1)}>
              다시 불러오기
            </button>
          </div>
        ) : null}
        {!error && !edition && (
          <div className="empty">
            <BookOpen size={32} />
            <p>열람할 판본을 불러오는 중이거나 공개된 판본이 없습니다.</p>
          </div>
        )}
        {edition && (
          <div className="workspace">
            <aside className="page-sidebar">
              <div className="sidebar-title">
                <BookOpen size={18} />
                <strong>족보 목차</strong>
                <span>{currentEdition?.pages}쪽</span>
              </div>
              <label className="page-search">
                <Search size={15} />
                <input
                  aria-label="페이지 찾기"
                  placeholder="페이지 찾기"
                  value={pageFilter}
                  onChange={(e) => {
                    setPageFilter(e.target.value);
                    setPageOffset(0);
                  }}
                />
              </label>
              <nav className="page-list" aria-label="스캔 페이지 목록">
                {pageList.items.map((p, i) => (
                  <button
                    key={p.id}
                    className={
                      p.id === pageId ? "page-link active" : "page-link"
                    }
                    onClick={() => selectPage(p.id)}
                    aria-current={p.id === pageId ? "page" : undefined}
                  >
                    <span className="page-icon">
                      <FileText size={19} />
                    </span>
                    <span>
                      <strong>{p.name.replace(/\.[^.]+$/, "")}쪽</strong>
                      <small>수록 인물 {p.people}명</small>
                    </span>
                    {p.id === pageId && <ChevronRight size={14} />}
                  </button>
                ))}
                {pagesBusy && <p className="subtle">불러오는 중…</p>}
                {!pagesBusy && !pageList.items.length && (
                  <p className="subtle">해당 페이지가 없습니다.</p>
                )}
                {pageList.hasMore && (
                  <button
                    className="text-button"
                    disabled={pagesBusy}
                    onClick={() => setPageOffset(pageList.nextOffset)}
                  >
                    페이지 더 보기
                  </button>
                )}
              </nav>
              <div className="sidebar-bottom">
                <span className="seal-small">譜</span>
                <p>
                  한 사람의 이름에서
                  <br />
                  이어지는 가족의 이야기
                </p>
              </div>
            </aside>
            <div className="document-area">
              <div className="document-heading">
                <div>
                  <span className="eyebrow">원본과 함께 읽는 족보</span>
                  <h2>
                    {page
                      ? `${page.name.replace(/\.[^.]+$/, "")}쪽`
                      : "페이지 열람"}
                    <span>{page ? `${page.people}명의 기록` : ""}</span>
                  </h2>
                </div>
                <div className="page-navigation">
                  <button
                    aria-label="이전 페이지"
                    disabled={currentIndex <= 0}
                    onClick={() =>
                      selectPage(pageList.items[currentIndex - 1].id)
                    }
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <button
                    aria-label="다음 페이지"
                    disabled={
                      currentIndex < 0 ||
                      currentIndex >= pageList.items.length - 1
                    }
                    onClick={() =>
                      selectPage(pageList.items[currentIndex + 1].id)
                    }
                  >
                    <ArrowRight size={18} />
                  </button>
                </div>
              </div>
              {pageError ? (
                <div className="empty" role="alert">
                  {pageError}
                  <button
                    className="text-button"
                    onClick={() => setRetry((r) => r + 1)}
                  >
                    다시 시도
                  </button>
                </div>
              ) : page ? (
                <ScanViewer
                  key={page.id}
                  page={page}
                  selected={selected}
                  choose={choose}
                />
              ) : (
                <Loading />
              )}
            </div>
            <aside className="people-panel">
              <div className="panel-heading">
                <Users size={18} />
                <h2>이 페이지의 인물</h2>
                <span>{page?.people || 0}</span>
              </div>
              <p className="section-help">
                이름 또는 원본의 번호를 선택해 보세요.
              </p>
              <div className="people-list">
                {page?.peopleList.map((p, i) => (
                  <button
                    key={p.occurrenceId}
                    className={`person-list-item ${selected === p.id ? "active" : ""}`}
                    onClick={() => {
                      choose(p);
                      setTab("record");
                    }}
                  >
                    <span className="person-number">{i + 1}</span>
                    <strong>{p.name}</strong>
                    <Badge status={p.status} />
                    <ChevronRight size={14} />
                  </button>
                ))}
                {page && !page.people && (
                  <p className="subtle">
                    이 페이지에는 등록된 인물이 없습니다.
                  </p>
                )}
              </div>
              {selected ? (
                <div className="detail-area">
                  {!detail && !personError ? (
                    <Loading />
                  ) : personError ? (
                    <div className="inline-error" role="alert">
                      {personError}
                      <button onClick={() => setRetry((r) => r + 1)}>
                        다시 시도
                      </button>
                    </div>
                  ) : (
                    source && (
                      <>
                        <div className="person-title">
                          <div>
                            <span className="eyebrow">인물 기록</span>
                            <h2 ref={detailHeading} tabIndex={-1}>
                              {source.name}
                            </h2>
                          </div>
                          <Badge status={source.status} />
                        </div>
                        <div
                          className="detail-tabs"
                          role="tablist"
                          aria-label="인물 정보 보기"
                        >
                          <button
                            role="tab"
                            aria-selected={tab === "record"}
                            onClick={() => setTab("record")}
                          >
                            <FileText size={15} />
                            상세 기록
                          </button>
                          <button
                            role="tab"
                            aria-selected={tab === "family"}
                            onClick={() => setTab("family")}
                          >
                            <GitBranch size={15} />
                            선조 · 후손
                          </button>
                        </div>
                        {tab === "record" ? (
                          <div className="record-panel">
                            <p
                              className={`record-notice ${source.informationStatus === "confirmed" ? "confirmed" : ""}`}
                            >
                              {source.informationStatus === "confirmed"
                                ? "원본과 대조해 확인한 정보입니다."
                                : "검토 중인 기록입니다. 원본 스캔과 함께 확인해 주세요."}
                            </p>
                            <dl>
                              <div>
                                <dt>이름 OCR 원문</dt>
                                <dd className="hanja">
                                  {source.rawName || "—"}
                                </dd>
                              </div>
                              {Object.entries(labels).map(([key, label]) =>
                                source.fields[key] != null &&
                                source.fields[key] !== "" ? (
                                  <div key={key}>
                                    <dt>{label}</dt>
                                    <dd>
                                      {source.fields[key]}
                                      {key === "generation_number" ? "세" : ""}
                                    </dd>
                                  </div>
                                ) : null,
                              )}
                            </dl>
                            {detail!.partners.length > 0 && (
                              <div className="partners">
                                <h3>배우자 기록</h3>
                                {detail!.partners.map((p, i) => (
                                  <div key={i}>
                                    <small>
                                      {partnerKinds[p.kind] || p.kind} ·{" "}
                                      {p.status === "confirmed"
                                        ? "확인"
                                        : "검토 대기"}
                                    </small>
                                    <p>{p.name}</p>
                                  </div>
                                ))}
                              </div>
                            )}
                            <div className="sources">
                              <h3>원본에서 찾기</h3>
                              {detail!.sources.map((s) => (
                                <button
                                  key={s.occurrenceId}
                                  onClick={() => setPageId(s.pageId)}
                                >
                                  <BookOpen size={14} />
                                  {s.pageName}
                                  <ArrowRight size={14} />
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <FamilyTree
                            person={source}
                            edition={edition}
                            choose={choose}
                          />
                        )}
                      </>
                    )
                  )}
                </div>
              ) : (
                <div className="choose-person">
                  <span>
                    <GitBranch size={29} />
                  </span>
                  <h3>한 사람의 기록을 펼쳐보세요</h3>
                  <p>
                    인물을 선택하면 상세 정보와
                    <br />
                    이어지는 선조·후손을 볼 수 있습니다.
                  </p>
                </div>
              )}
            </aside>
          </div>
        )}
        <footer className="site-footer">
          <span>
            杜氏世譜 <i /> 두씨 족보 열람실
          </span>
          <span>원본은 그대로, 기록은 다음 세대로.</span>
        </footer>
      </main>
      {searchTerm && (
        <div className="search-backdrop" onClick={() => setSearchTerm("")}>
          <section
            className="search-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="인물 검색 결과"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") setSearchTerm("");
            }}
          >
            <div className="search-dialog-heading">
              <div>
                <span className="eyebrow">족보 인물 검색</span>
                <h2>‘{searchTerm}’ 검색 결과</h2>
              </div>
              <button
                autoFocus
                aria-label="검색 닫기"
                onClick={() => setSearchTerm("")}
              >
                <X size={20} />
              </button>
            </div>
            <p className="section-help">
              현재 판본의 이름에서 찾습니다. 같은 이름도 출처를 보고 구분해
              주세요.
            </p>
            {searchError && <p role="alert">{searchError}</p>}
            <div className="search-results">
              {results?.items.map((p) => (
                <button
                  key={p.occurrenceId}
                  onClick={() => {
                    choose(p);
                    setTab("record");
                  }}
                >
                  <span className="search-avatar">{p.name.slice(0, 1)}</span>
                  <span>
                    <strong>{p.name}</strong>
                    <small>
                      {p.pageName} {p.generation ? `· ${p.generation}세` : ""}
                    </small>
                  </span>
                  <Badge status={p.status} />
                  <ArrowRight size={17} />
                </button>
              ))}
              {results && !results.items.length && (
                <div className="empty">
                  <Search size={26} />
                  <p>일치하는 인물이 없습니다.</p>
                  <small>
                    족보에 적힌 한자 이름이나 이름의 일부로 검색해 보세요.
                  </small>
                </div>
              )}
            </div>
            {searchBusy && <Loading />}
            {results?.hasMore && (
              <button
                className="text-button"
                disabled={searchBusy}
                onClick={() => setSearchOffset(results.nextOffset)}
              >
                검색 결과 더 보기
              </button>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
