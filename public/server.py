#!/usr/bin/env python3
"""Public web app for approved data.

Serves the published genealogy over plain HTTP. Every database read goes
through `psql` (no Python database driver required).

Usage:
    DATABASE_URL=postgresql://postgres@127.0.0.1:5432/doos python3 public/server.py --port 8080
    python3 public/server.py --port 8080

Routes:
    GET /                        list approved pages (client side)
    GET /api/health               {"ok": true, "source": "public"}
    GET /api/pages                approved pages + per page counts
    GET /api/pages/{section}/{page_no}   one approved page + people
    GET /images/{section}/{n}.jpg          scan image
    GET /static/style.css, /static/app.js
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "public" / "static"
SECTIONS = {"frontmatter", "genealogy"}

sys.path.insert(0, str(ROOT / "scripts"))

from common import find_row, resolve_image  # noqa: E402

LIST_SQL = """
SELECT COALESCE(jsonb_agg(
         jsonb_build_object(
           'section', s.code,
           'printed_page_no', p.printed_page_no,
           'page_type', p.page_type,
           'has_image', p.image_path IS NOT NULL,
           'image_width', p.width,
           'image_height', p.height,
           'person_count', (SELECT count(*) FROM people pe WHERE pe.source_page_id = p.id),
           'needs_human', (SELECT count(*) FROM people pe WHERE pe.source_page_id = p.id AND pe.needs_human)
         ) ORDER BY s.code, p.printed_page_no
       ), '[]'::jsonb) AS pages
FROM pages p
JOIN sections s ON s.id = p.section_id
WHERE p.review_status IN ('approved', 'published');
"""

DETAIL_SQL = """
SELECT jsonb_build_object(
       'section', s.code,
       'printed_page_no', p.printed_page_no,
       'page_type', p.page_type,
       'image_path', p.image_path,
       'image_width', p.width,
       'image_height', p.height,
       'people', (
         SELECT COALESCE(jsonb_agg(jsonb_build_object(
                  'section', s2.code,
                  'printed_page_no', p.printed_page_no,
                  'row_no', pe.row_no,
                  'column_no', pe.column_no,
                  'is_subject', pe.is_subject,
                  'as_printed', pe.as_printed,
                  'name_hanja', pe.name_hanja,
                  'name_hangul', pe.name_hangul,
                  'prefix', pe.prefix,
                  'generation_no', pe.generation_no,
                  'generation_char', pe.generation_char,
                  'generation_offset', pe.generation_offset,
                  'page_relation', pe.page_relation,
                  'father', (
                    SELECT jsonb_build_object(
                           'section', fs.code,
                           'printed_page_no', fp.printed_page_no,
                           'row_no', f.row_no,
                           'column_no', f.column_no,
                           'as_printed', f.as_printed,
                           'source', pe.father_source
                         )
                    FROM people f
                    JOIN pages fp ON fp.id = f.source_page_id
                    JOIN sections fs ON fs.id = fp.section_id
                    WHERE f.id = pe.father_id
                  ),
                  'spouses', (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                           'ordinal', m.ordinal,
                           'spouse_as_printed', m.spouse_as_printed,
                           'spouse_name_hanja', m.spouse_name_hanja,
                           'spouse_bonkwan', m.spouse_bonkwan,
                           'relation', m.relation,
                           'birth', m.birth,
                           'death', m.death
                         ) ORDER BY m.ordinal), '[]'::jsonb)
                    FROM marriages m
                    WHERE m.person_id = pe.id
                  ),
                  'burial', (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                           'burial_raw', b.burial_raw,
                           'location', b.location,
                           'orientation', b.orientation,
                           'certainty', b.certainty
                         ) ORDER BY b.id), '[]'::jsonb)
                    FROM burials b
                    WHERE b.person_id = pe.id
                  )
                ) ORDER BY pe.row_no, pe.column_no
       ), '[]'::jsonb)
         FROM people pe
         JOIN pages pp ON pp.id = pe.source_page_id
         JOIN sections s2 ON s2.id = pp.section_id
         WHERE pe.source_page_id = p.id
       )
     ) AS payload
FROM pages p
JOIN sections s ON s.id = p.section_id
WHERE s.code = '%s'
  AND p.printed_page_no = %d
  AND p.review_status IN ('approved', 'published');
"""


def build_dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER") or "doos"
    password = os.environ.get("POSTGRES_PASSWORD") or "doos"
    db = os.environ.get("POSTGRES_DB") or "doos"
    host = os.environ.get("PGHOST") or "127.0.0.1"
    port = os.environ.get("PGPORT") or "5432"
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def psql_json(dsn: str, sql: str):
    completed = subprocess.run(
        ["psql", dsn, "-X", "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"psql 실패: {completed.stderr.strip()}")
    return json.loads(completed.stdout.strip() or "{}")


def run() -> ThreadingHTTPServer:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args) -> None:  # quieter logs
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

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

        def send_html(self, path: Path) -> None:
            self.send_file(path, "text/html; charset=utf-8", cache=False)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/":
                self.send_html(STATIC / "index.html")
                return
            if path.startswith("/static/"):
                target = (STATIC / path.removeprefix("/static/")).resolve()
                if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                    self.send_error_json(404, "not found")
                    return
                if target.suffix == ".css":
                    self.send_file(target, "text/css; charset=utf-8", cache=False)
                elif target.suffix == ".js":
                    self.send_file(target, "application/javascript; charset=utf-8", cache=False)
                else:
                    self.send_error_json(404, "not found")
                return
            if path == "/api/health":
                self.send_json({"ok": True, "source": "public", "db": build_dsn()})
                return
            if path == "/api/pages":
                try:
                    pages = psql_json(build_dsn(), LIST_SQL)
                    items = pages if isinstance(pages, list) else (pages.get("pages") or [])
                    self.send_json({"pages": items})
                except Exception as exc:  # noqa: BLE001
                    self.send_error_json(503, f"DB 조회 실패: {exc}")
                return
            if path.startswith("/api/pages/"):
                parts = path.split("/")
                # /api/pages/{section}/{page_no} -> ["", "api", "pages", section, page_no]
                if len(parts) == 5 and parts[2] == "pages" and parts[3] in SECTIONS and parts[4].isdigit():
                    section = parts[3]
                    page_no = int(parts[4])
                    try:
                        payload = psql_json(build_dsn(), DETAIL_SQL % (section, page_no))
                        if not payload.get("printed_page_no"):
                            self.send_error_json(404, "승인되지 않은 페이지입니다.")
                            return
                        self.send_json(payload)
                    except Exception as exc:  # noqa: BLE001
                        self.send_error_json(503, f"DB 조회 실패: {exc}")
                else:
                    self.send_error_json(404, "not found")
                return

            if path.startswith("/images/"):
                self.handle_image(path)
                return

            self.send_error_json(404, "not found")

        def handle_image(self, path: str) -> None:
            parts = path.split("/")
            if len(parts) == 4 and parts[2] in SECTIONS:
                try:
                    page_no = int(parts[3].removesuffix(".jpg"))
                except ValueError:
                    self.send_error_json(404, "not found")
                    return
                row = find_row(parts[2], page_no)
                if row is None or row.get("page_type") == "missing":
                    self.send_error_json(404, "미수록 페이지입니다.")
                    return
                image = resolve_image(row)
                if image is None:
                    self.send_error_json(404, "이미지 파일이 없습니다.")
                    return
                self.send_file(image, "image/jpeg")
                return
            self.send_error_json(404, "not found")

        def do_HEAD(self) -> None:
            self.do_GET()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"public: http://{args.host}:{args.port}", file=sys.stderr)
    print(f"public: db {build_dsn()}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server


if __name__ == "__main__":
    raise SystemExit(run())
