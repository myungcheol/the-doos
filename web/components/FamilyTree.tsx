"use client";
import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
} from "lucide-react";
import type { Listing, PersonSummary, Relative } from "@/lib/types";

export async function api<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal, cache: "no-store" });
  const value = await r.json();
  if (!r.ok) throw new Error(value.error || "자료를 불러올 수 없습니다.");
  return value;
}
const kinds: Record<string, string> = {
  biological: "친생",
  adoptive: "입양",
  unspecified: "유형 미확정",
};
function Branch({
  person,
  edition,
  direction,
  path,
  choose,
  initial = false,
}: {
  person: PersonSummary;
  edition: string;
  direction: "ancestors" | "descendants";
  path: string[];
  choose: (p: PersonSummary) => void;
  initial?: boolean;
}) {
  const [open, setOpen] = useState(initial);
  const [data, setData] = useState<Listing<Relative> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pageOffset, setPageOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<Listing<Relative>>(
      `/api/people/${person.id}/relatives?edition=${encodeURIComponent(edition)}&direction=${direction}&offset=${pageOffset}`,
      controller.signal,
    )
      .then((next) =>
        setData((previous) => ({
          ...next,
          items: pageOffset
            ? [...(previous?.items || []), ...next.items]
            : next.items,
        })),
      )
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, person.id, edition, direction, pageOffset, retry]);
  return (
    <div className="tree-branch">
      <div className={`tree-person ${initial ? "root-person" : ""}`}>
        <button
          className="branch-toggle"
          aria-label={`${person.name} ${direction === "ancestors" ? "선조" : "후손"} ${open ? "접기" : "펼치기"}`}
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
            setData(null);
            setPageOffset(0);
          }}
        >
          {loading ? (
            <LoaderCircle size={17} className="spin" />
          ) : open ? (
            <ChevronDown size={17} />
          ) : (
            <ChevronRight size={17} />
          )}
        </button>
        <button className="tree-name" onClick={() => choose(person)}>
          <strong>{person.name}</strong>
          <small>
            {person.generation ? `${person.generation}세 · ` : ""}
            {person.pageName}
          </small>
        </button>
        {initial && <span className="tiny-label">기준 인물</span>}
      </div>
      {open && (
        <div className="tree-children">
          {error && (
            <div className="inline-error">
              {error}
              <button onClick={() => setRetry((r) => r + 1)}>다시 시도</button>
            </div>
          )}
          {data?.items.map((p) => (
            <div key={p.edgeId} className="tree-entry">
              <span className="relation-label">{kinds[p.kind] || p.kind}</span>
              {path.includes(p.id) ? (
                <button className="linked-person" onClick={() => choose(p)}>
                  {p.name} · 앞에서 본 인물
                </button>
              ) : (
                <Branch
                  person={p}
                  edition={edition}
                  direction={direction}
                  path={[...path, p.id]}
                  choose={choose}
                />
              )}
            </div>
          ))}
          {data && !data.items.length && !loading && (
            <p className="tree-end">
              등록된 확정 {direction === "ancestors" ? "부모" : "자녀"} 관계가
              없습니다.
            </p>
          )}
          {data?.hasMore && (
            <button
              className="text-button"
              disabled={loading}
              onClick={() => setPageOffset(data.nextOffset)}
            >
              관계 더 보기
            </button>
          )}
        </div>
      )}
    </div>
  );
}
export default function FamilyTree({
  person,
  edition,
  choose,
}: {
  person: PersonSummary;
  edition: string;
  choose: (p: PersonSummary) => void;
}) {
  const [direction, setDirection] = useState<"ancestors" | "descendants">(
    "descendants",
  );
  return (
    <section className="family-panel">
      <div className="segmented">
        <button
          className={direction === "ancestors" ? "active" : ""}
          onClick={() => setDirection("ancestors")}
        >
          <ArrowUp size={15} />
          선조 찾아가기
        </button>
        <button
          className={direction === "descendants" ? "active" : ""}
          onClick={() => setDirection("descendants")}
        >
          <ArrowDown size={15} />
          후손 펼치기
        </button>
      </div>
      <p className="section-help">
        화살표를 눌러 한 세대씩 펼쳐보세요. 이름을 누르면 그 인물의 기록으로
        이동합니다.
      </p>
      <Branch
        key={`${person.id}:${direction}:${edition}`}
        person={person}
        edition={edition}
        direction={direction}
        path={[person.id]}
        choose={choose}
        initial
      />
      <p className="tree-note">
        검수에서 확인한 관계만 표시합니다. ‘유형 미확정’은 친생·입양 여부가
        정해지지 않은 연결입니다.
      </p>
    </section>
  );
}
