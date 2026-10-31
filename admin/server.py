#!/usr/bin/env python3
"""Local admin review tool.

Serves the scan image next to the parsed JSON so a human can check one page at
a time. No framework, no build step.

Usage:
    python3 scripts/link_pages.py
    python3 admin/server.py --port 8765
    # open http://127.0.0.1:8765

Data:
    data/manifests/pages.csv       inventory (read)
    data/parsed/...                AI output (read/write)
    data/ocr/...                   OCR sidecar (read)
    data/review/status.json        review status (read/write)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.parse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from common import (  # noqa: E402
    PARSED_DIR,
    REVIEW_STATUS,
    atomic_write_json,
    atomic_write_text,
    find_row,
    load_json,
    load_manifest,
    load_review_status,
    meta_path,
    ocr_path,
    page_key,
    parsed_path,
    resolve_image,
    save_review_status,
)
from validate_page import validate  # noqa: E402

STATIC = ROOT / "admin" / "static"
STATUSES = {"pending", "in_review", "approved", "needs_fix"}
MAX_BODY = 8 * 1024 * 1024

SUMMARY_CACHE: dict[str, tuple[int, dict]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parsed_summary(path: Path) -> dict:
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    cached = SUMMARY_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]

    data = load_json(path)
    summary: dict = {"names": [], "needs_human": 0, "rows": 0, "page_type": None}
    if isinstance(data, dict):
        page = data.get("page") or {}
        summary["page_type"] = page.get("page_type")
        people = []
        for subject in data.get("subjects") or []:
            if isinstance(subject, dict):
                people.append(subject)
        for entry in data.get("entries") or []:
            if isinstance(entry, dict):
                summary["rows"] = max(summary["rows"], int(entry.get("row") or 0))
                if entry.get("needs_human"):
                    summary["needs_human"] += 1
                person = entry.get("person")
                if isinstance(person, dict):
                    people.append(person)
        for person in people:
            if person.get("needs_human"):
                summary["needs_human"] += 1
            name = person.get("name_hanja") or person.get("raw_name")
            if name and name not in summary["names"]:
                summary["names"].append(str(name))
        summary["names"] = summary["names"][:4]
    SUMMARY_CACHE[str(path)] = (stamp, summary)
    return summary


def all_rows() -> list[dict]:
    rows = load_manifest()
    return sorted(rows, key=lambda row: (row["section"], row["printed_page_no"]))


def row_payload(row: dict, statuses: dict) -> dict:
    section, page_no = row["section"], row["printed_page_no"]
    path = parsed_path(section, page_no)
    summary = parsed_summary(path) if path.exists() else {}
    review = statuses.get(page_key(section, page_no), {})
    return {
        **row,
        "has_json": path.exists(),
        "names": summary.get("names", []),
        "needs_human": summary.get("needs_human", 0),
        "rows": summary.get("rows", 0),
        "status": review.get("status", "pending"),
        "status_note": review.get("note", ""),
        "status_updated_at": review.get("updated_at"),
    }


def stats_for(items: list[dict]) -> dict:
    present = [item for item in items if item["page_type"] != "missing"]
    parsed = [item for item in present if item["has_json"]]
    return {
        "total": len(items),
        "present": len(present),
        "missing": len(items) - len(present),
        "parsed": len(parsed),
        "approved": sum(1 for item in present if item["status"] == "approved"),
        "needs_fix": sum(1 for item in present if item["status"] == "needs_fix"),
        "in_review": sum(1 for item in present if item["status"] == "in_review"),
        "pending": sum(1 for item in present if item["status"] == "pending"),
        "needs_human": sum(1 for item in parsed if item["needs_human"]),
    }


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "DoosAdmin/0.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- helpers ----------

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: int, message: str, **extra) -> None:
        self.send_json({"error": message, **extra}, status)

    def send_file(self, path: Path, content_type: str | None = None, cache: bool = True) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error_json(404, "파일을 읽을 수 없습니다.")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("요청 본문이 너무 큽니다.")
        return self.rfile.read(length) if length else b""

    def read_json_body(self) -> object:
        body = self.read_body()
        if not body:
            raise ValueError("빈 요청입니다.")
        return json.loads(body.decode("utf-8"))

    def page_target(self, parts: list[str]) -> tuple[str, int] | None:
        # path.split("/") -> ["", "api", "pages", section, page, ...]
        if len(parts) < 5 or parts[1:3] != ["api", "pages"]:
            return None
        section = parts[3]
        if section not in {"frontmatter", "genealogy"}:
            return None
        try:
            page_no = int(parts[4])
        except ValueError:
            return None
        return section, page_no

    def item_for(self, section: str, page_no: int, statuses: dict) -> dict | None:
        row = find_row(section, page_no)
        return row_payload(row, statuses) if row else None

    # ---------- routes ----------

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.send_file(STATIC / "index.html", "text/html; charset=utf-8", cache=False)
            return
        if path.startswith("/static/"):
            target = (STATIC / path.removeprefix("/static/")).resolve()
            if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                self.send_error_json(404, "not found")
                return
            self.send_file(target, cache=False)
            return
        if path == "/api/health":
            self.send_json({"ok": True, "time": utc_now()})
            return
        if path == "/api/stats":
            items = [row_payload(row, load_review_status()) for row in all_rows()]
            self.send_json(stats_for(items))
            return
        if path == "/api/pages":
            self.handle_list(query)
            return
        if path == "/api/export":
            self.handle_export(query)
            return
        if path.startswith("/images/"):
            self.handle_image(path)
            return
        if path.startswith("/api/pages/"):
            parts = path.split("/")
            target = self.page_target(parts)
            if not target:
                self.send_error_json(404, "잘못된 페이지 경로입니다.")
                return
            if len(parts) >= 6 and parts[5] == "json":
                self.send_error_json(405, "GET이 아니라 PUT으로 저장하세요.")
                return
            self.handle_detail(*target)
            return

        self.send_error_json(404, "not found")

    def do_PUT(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.split("/")
        target = self.page_target(parts)
        if not target or len(parts) < 6 or parts[5] != "json":
            self.send_error_json(404, "not found")
            return
        section, page_no = target
        row = find_row(section, page_no)
        if row is None or row["page_type"] == "missing":
            self.send_error_json(404, "해당 페이지가 없습니다.")
            return
        try:
            payload = self.read_json_body()
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error_json(400, f"JSON을 읽지 못했습니다: {exc}")
            return
        errors, warnings = validate(payload, section, page_no)
        strict = urllib.parse.parse_qs(parsed.query).get("strict", ["0"])[0] == "1"
        if errors or (strict and warnings):
            self.send_json(
                {
                    "error": "검증에 실패했습니다." if errors else "경고가 있습니다.",
                    "errors": errors,
                    "warnings": warnings,
                },
                422,
            )
            return

        destination = parsed_path(section, page_no)
        if destination.exists():
            backup = destination.with_suffix(".json.bak")
            atomic_write_text(backup, destination.read_text(encoding="utf-8"))
        atomic_write_json(destination, payload)
        SUMMARY_CACHE.pop(str(destination), None)
        self.send_json({"ok": True, "saved": destination.relative_to(ROOT).as_posix(), "warnings": warnings})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.split("/")
        target = self.page_target(parts)
        if not target or len(parts) < 6 or parts[5] != "status":
            self.send_error_json(404, "not found")
            return
        section, page_no = target
        row = find_row(section, page_no)
        if row is None or row["page_type"] == "missing":
            self.send_error_json(404, "해당 페이지가 없습니다.")
            return
        try:
            payload = self.read_json_body()
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error_json(400, f"JSON을 읽지 못했습니다: {exc}")
            return
        if not isinstance(payload, dict) or payload.get("status") not in STATUSES:
            self.send_error_json(400, "status는 pending/in_review/approved/needs_fix 중 하나여야 합니다.")
            return

        statuses = load_review_status()
        key = page_key(section, page_no)
        statuses[key] = {
            "status": payload["status"],
            "note": str(payload.get("note") or ""),
            "updated_at": utc_now(),
        }
        save_review_status(statuses)
        self.send_json({"ok": True, "review": statuses[key]})

    # ---------- handlers ----------

    def handle_list(self, query: dict) -> None:
        statuses = load_review_status()
        section = (query.get("section") or ["all"])[0]
        status = (query.get("status") or ["all"])[0]
        has_json = (query.get("has_json") or ["all"])[0]
        text = (query.get("q") or [""])[0].strip().casefold()

        items = []
        for row in all_rows():
            if section != "all" and row["section"] != section:
                continue
            item = row_payload(row, statuses)
            if row["page_type"] != "missing":
                if status != "all" and item["status"] != status:
                    continue
                if has_json == "yes" and not item["has_json"]:
                    continue
                if has_json == "no" and item["has_json"]:
                    continue
            elif status != "all" or has_json == "yes":
                continue
            if text:
                haystack = " ".join(
                    [
                        item["section"],
                        str(item["printed_page_no"]),
                        item["page_type"],
                        item.get("notes") or "",
                        " ".join(item.get("names") or []),
                    ]
                ).casefold()
                if text not in haystack:
                    continue
            items.append(item)

        offset = max(0, int((query.get("offset") or ["0"])[0] or 0))
        limit = min(2000, max(1, int((query.get("limit") or ["2000"])[0] or 2000)))
        page_items = items[offset : offset + limit]

        self.send_json(
            {
                "items": page_items,
                "total": len(items),
                "offset": offset,
                "limit": limit,
                "stats": stats_for([row_payload(row, statuses) for row in all_rows()]),
            }
        )

    def handle_detail(self, section: str, page_no: int) -> None:
        statuses = load_review_status()
        item = self.item_for(section, page_no, statuses)
        if item is None:
            self.send_error_json(404, "해당 페이지가 없습니다.")
            return
        parsed = load_json(parsed_path(section, page_no))
        meta = load_json(meta_path(section, page_no))
        ocr_file = ocr_path(section, page_no)
        ocr = ocr_file.read_text(encoding="utf-8") if ocr_file.exists() else None
        errors, warnings = validate(parsed, section, page_no) if isinstance(parsed, dict) else ([], [])

        rows = [row for row in all_rows() if row["section"] == section and row["page_type"] != "missing"]
        index = next((i for i, row in enumerate(rows) if row["printed_page_no"] == page_no), None)
        neighbors = {
            "prev": rows[index - 1]["printed_page_no"] if index not in (None, 0) else None,
            "next": rows[index + 1]["printed_page_no"] if index is not None and index + 1 < len(rows) else None,
        }
        self.send_json(
            {
                "page": item,
                "manifest": item,
                "parsed": parsed,
                "meta": meta,
                "ocr": ocr,
                "validation": {"errors": errors, "warnings": warnings},
                "neighbors": neighbors,
                "image_url": f"/images/{section}/{page_no}.jpg",
            }
        )

    def handle_image(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) == 4 and parts[2] in {"frontmatter", "genealogy"}:
            try:
                page_no = int(parts[3].removesuffix(".jpg"))
            except ValueError:
                self.send_error_json(404, "not found")
                return
            row = find_row(parts[2], page_no)
            if row is None or row["page_type"] == "missing":
                self.send_error_json(404, "미수록 페이지입니다.")
                return
            image = resolve_image(row)
            if image is None:
                self.send_error_json(404, "이미지 파일이 없습니다.")
                return
            self.send_file(image, "image/jpeg")
            return
        if len(parts) == 4 and parts[2] == "cover" and parts[3] in {"front.jpg", "back.jpg"}:
            image = ROOT / "data" / "pages" / "covers" / parts[3]
            if not image.exists():
                image = ROOT / "scan" / ("앞표지.jpg" if parts[3] == "front.jpg" else "뒷표지.jpg")
            self.send_file(image, "image/jpeg")
            return
        self.send_error_json(404, "not found")

    def handle_export(self, query: dict) -> None:
        statuses = load_review_status()
        wanted = (query.get("status") or ["approved"])[0]
        section = (query.get("section") or ["all"])[0]
        lines = []
        for row in all_rows():
            if section != "all" and row["section"] != section:
                continue
            item = row_payload(row, statuses)
            if item["page_type"] == "missing" or (wanted != "all" and item["status"] != wanted):
                continue
            parsed = load_json(parsed_path(row["section"], row["printed_page_no"]))
            if not isinstance(parsed, dict):
                continue
            lines.append(
                json.dumps(
                    {
                        "section": row["section"],
                        "printed_page_no": row["printed_page_no"],
                        "review": statuses.get(page_key(row["section"], row["printed_page_no"]), {}),
                        "parsed": parsed,
                    },
                    ensure_ascii=False,
                )
            )
        body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="pages-{wanted}.jsonl"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not (ROOT / "data" / "manifests" / "pages.csv").exists():
        print("data/manifests/pages.csv가 없습니다. python3 scripts/build_manifest.py를 먼저 실행하세요.", file=sys.stderr)
        return 2
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_STATUS.parent.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), AdminHandler)
    print(f"admin: http://{args.host}:{args.port}")
    print(f"root : {ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n중지")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
