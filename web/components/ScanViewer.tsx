"use client";
import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff, Maximize, Minus, Plus, ScanLine } from "lucide-react";
import type { PageDetail, PersonSummary } from "@/lib/types";

export default function ScanViewer({
  page,
  selected,
  choose,
}: {
  page: PageDetail;
  selected: string | null;
  choose: (p: PersonSummary) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 700 });
  const [zoom, setZoom] = useState(1);
  const [boxes, setBoxes] = useState(true);
  const [failed, setFailed] = useState(false);
  const drag = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(node);
    const wheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        setZoom((z) =>
          Math.min(5, Math.max(0.5, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))),
        );
      }
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => {
      observer.disconnect();
      node.removeEventListener("wheel", wheel);
    };
  }, []);
  const image = page.image;
  const scale = image
    ? Math.max(
        0.01,
        Math.min(
          (size.width - 64) / image.width,
          (size.height - 64) / image.height,
        ),
      ) * zoom
    : 1;
  return (
    <section className="scan-panel" aria-label="원본 스캔 열람">
      <div className="scan-toolbar">
        <span>
          <ScanLine size={16} />
          <strong>원본 스캔</strong>
          <small>{image?.isRoi ? "표 영역" : "전체 페이지"}</small>
        </span>
        <div className="tools">
          <button
            aria-label={boxes ? "인물 표시 숨기기" : "인물 표시 보기"}
            aria-pressed={boxes}
            onClick={() => setBoxes(!boxes)}
          >
            {boxes ? <Eye size={17} /> : <EyeOff size={17} />}
          </button>
          <i />
          <button
            aria-label="축소"
            onClick={() => setZoom((z) => Math.max(0.5, z / 1.25))}
          >
            <Minus size={17} />
          </button>
          <output>{Math.round(zoom * 100)}%</output>
          <button
            aria-label="확대"
            onClick={() => setZoom((z) => Math.min(5, z * 1.25))}
          >
            <Plus size={17} />
          </button>
          <button
            aria-label="화면에 맞추기"
            onClick={() => {
              setZoom(1);
              viewport.current?.scrollTo(0, 0);
            }}
          >
            <Maximize size={16} />
          </button>
        </div>
      </div>
      <div
        className="scan-viewport"
        ref={viewport}
        onPointerDown={(e) => {
          if (e.button !== 0 || (e.target as HTMLElement).closest("button"))
            return;
          const el = e.currentTarget;
          drag.current = {
            x: e.clientX,
            y: e.clientY,
            left: el.scrollLeft,
            top: el.scrollTop,
          };
          el.setPointerCapture(e.pointerId);
          el.classList.add("dragging");
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) {
            e.currentTarget.scrollLeft = d.left - e.clientX + d.x;
            e.currentTarget.scrollTop = d.top - e.clientY + d.y;
          }
        }}
        onPointerUp={(e) => {
          drag.current = null;
          e.currentTarget.classList.remove("dragging");
          if (e.currentTarget.hasPointerCapture(e.pointerId))
            e.currentTarget.releasePointerCapture(e.pointerId);
        }}
        onPointerCancel={(e) => {
          drag.current = null;
          e.currentTarget.classList.remove("dragging");
        }}
      >
        {image && !failed ? (
          <div
            className="scan-stage"
            style={{
              minWidth: image.width * scale + 64,
              minHeight: image.height * scale + 64,
            }}
          >
            <div
              className="scan-paper"
              style={{
                width: image.width * scale,
                height: image.height * scale,
              }}
            >
              {/* Plain img retains the original image coordinate system. */}
              <img
                src={image.url}
                alt={`${page.name} 족보 원본 스캔`}
                draggable={false}
                onError={() => setFailed(true)}
              />
              {boxes &&
                page.peopleList.map((person, index) => {
                  const b = person.bbox;
                  if (!b) return null;
                  const left = Math.max(0, b.x - image.offsetX),
                    top = Math.max(0, b.y - image.offsetY);
                  const right = Math.min(
                      image.width,
                      b.x + b.width - image.offsetX,
                    ),
                    bottom = Math.min(
                      image.height,
                      b.y + b.height - image.offsetY,
                    );
                  if (right <= left || bottom <= top) return null;
                  return (
                    <button
                      key={person.occurrenceId}
                      className={`person-box ${selected === person.id ? "selected" : ""}`}
                      aria-label={`${index + 1}. ${person.name} 선택`}
                      aria-pressed={selected === person.id}
                      title={`${person.name} · ${person.status === "confirmed" ? "이름 확인" : "검토 대기"}`}
                      style={{
                        left: `${(left / image.width) * 100}%`,
                        top: `${(top / image.height) * 100}%`,
                        width: `${((right - left) / image.width) * 100}%`,
                        height: `${((bottom - top) / image.height) * 100}%`,
                      }}
                      onClick={() => choose(person)}
                    >
                      <span>{index + 1}</span>
                    </button>
                  );
                })}
            </div>
          </div>
        ) : (
          <div className="empty">
            <ScanLine size={32} />
            <strong>원본 이미지를 표시할 수 없습니다.</strong>
            <p>이미지 저장소 연결을 확인해 주세요.</p>
          </div>
        )}
      </div>
      <div className="scan-footer">
        <span>
          <span className="legend-square" />
          번호를 누르면 인물의 기록이 열립니다
        </span>
        <span>드래그로 이동 · Ctrl + 휠로 확대</span>
      </div>
    </section>
  );
}
