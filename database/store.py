"""Transactional PostgreSQL storage and content-addressed local image assets.

SQL columns are deliberately short. Original JSON keys remain untouched in raw
evidence and review snapshots, so old files and future unknown fields survive.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from ocr.storage import load_ocr_output, page_name, validate_page_result


class DatabaseError(RuntimeError):
    pass


class ReviewConflict(DatabaseError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


class AssetStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def put(self, source):
        """Copy bytes unchanged; publish only complete objects, never remove originals."""
        source = Path(source)
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.asset-', dir=self.root)
        try:
            checksum = hashlib.sha256()
            size = 0
            with os.fdopen(descriptor, 'wb') as target, source.open('rb') as original:
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    target.write(chunk)
                    checksum.update(chunk)
                    size += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            if not size:
                raise ValueError('빈 이미지 파일은 저장할 수 없습니다.')
            key = checksum.hexdigest()
            relative = f'{key[:2]}/{key}'
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if file_hash(target) != key:
                    raise ValueError('이미지 저장소 체크섬 불일치: ' + relative)
            else:
                # Atomic create without clobbering a concurrently published object.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if file_hash(target) != key:
                        raise ValueError('이미지 저장소 체크섬 불일치: ' + relative)
            if os.name == 'posix':
                for directory in (target.parent, self.root):
                    descriptor = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            return key, relative, size
        finally:
            Path(temporary).unlink(missing_ok=True)

    def path(self, key):
        return self.root / key[:2] / key


class PostgresStore:
    def __init__(self, dsn=None, asset_root=None):
        self.dsn = dsn or os.environ.get('JOKBO_DATABASE_URL')
        root = asset_root or os.environ.get('JOKBO_ASSET_ROOT')
        if not self.dsn or not root:
            raise DatabaseError('JOKBO_DATABASE_URL과 JOKBO_ASSET_ROOT를 설정하세요.')
        self.assets = AssetStore(root)

    @contextmanager
    def connection(self):
        try:
            import psycopg
        except ImportError as exc:
            raise DatabaseError('requirements-postgres.txt를 설치하세요.') from exc
        try:
            with psycopg.connect(self.dsn, connect_timeout=10) as conn:
                yield conn
        except psycopg.Error as exc:
            # libpq errors can include DSNs/passwords: do not send them to the UI.
            code = exc.sqlstate or 'connection'
            raise DatabaseError(f'PostgreSQL 작업 실패 ({code}). 연결·제약조건·서버 로그를 확인하세요. 변경은 취소되었습니다.') from None

    @staticmethod
    def json(value):
        from psycopg.types.json import Jsonb
        # Reject non-standard JSON rather than silently converting NaN to null.
        return Jsonb(value, dumps=lambda x: json.dumps(x, ensure_ascii=False, allow_nan=False))

    def initialize(self):
        with self.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(1987, 1)')
            conn.execute(Path(__file__).with_name('schema.sql').read_text())

    @staticmethod
    def _lock(conn):
        # Lock before any reads, across editions, for UID links and graph checks.
        conn.execute('SELECT pg_advisory_xact_lock(1987, 1)')

    def _edition(self, conn, edition, initial=None):
        if not edition.get('edition_id'):
            raise ValueError('edition_id가 필요합니다.')
        eid = edition['edition_id']
        conn.execute('INSERT INTO jokbo.editions(id, meta, state) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                     (eid, self.json(edition), self.json(initial or {'edition': edition})))
        state, revision, meta = conn.execute('SELECT state, revision, meta FROM jokbo.editions WHERE id=%s FOR UPDATE', (eid,)).fetchone()
        if (state.get('edition') or {}).get('edition_id', eid) != eid:
            raise ValueError('검수 상태의 판본이 다릅니다.')
        for key in ('publication_year', 'volume'):
            if edition.get(key) is not None and meta.get(key) is not None and edition[key] != meta[key]:
                raise ValueError('기존 판본 메타데이터와 다릅니다: ' + key)
        return state, revision

    def _asset(self, conn, path):
        key, relative, size = self.assets.put(path)
        conn.execute('INSERT INTO jokbo.assets(id,path,size) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', (key, relative, size))
        return key

    @staticmethod
    def _resolve(path, root):
        path = Path(path).expanduser()
        candidates = [path, root / path, root.parent / path]
        return next((item for item in candidates if item.is_file()), None)

    def _import_page(self, conn, eid, page, root):
        page = deepcopy(page)
        page.setdefault('schema_version', 1)
        # Validator adds a runtime path; retain the actual input evidence intact.
        validate_page_result(deepcopy(page), root / Path(page['source_image']).stem / 'page.json')
        name = page_name(page)
        if Path(name).name != name or name in ('.', '..') or '\\' in name:
            raise ValueError('페이지 이름은 경로를 포함할 수 없습니다.')
        names = conn.execute('SELECT name FROM jokbo.pages WHERE edition_id=%s', (eid,)).fetchall()
        if any(other != name and Path(other).stem == Path(name).stem for (other,) in names):
            raise ValueError('같은 판본의 페이지 stem이 중복됩니다. 원본 파일 이름을 구분하세요.')
        conn.execute('INSERT INTO jokbo.pages(edition_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (eid, name))
        pid = conn.execute('SELECT id FROM jokbo.pages WHERE edition_id=%s AND name=%s', (eid, name)).fetchone()[0]
        # Output relocation is not a new OCR run. All OCR/geometry/unknown fields are.
        identity = {k: v for k, v in page.items() if k not in ('page_output_dir', 'asset_path', 'roi_asset_path')}
        checksum = digest(identity)
        previous = conn.execute('SELECT id,active FROM jokbo.ocr_runs WHERE page_id=%s AND digest=%s', (pid, checksum)).fetchone()
        if previous:
            return 'unchanged' if previous[1] else 'pending'
        source = self._resolve(page['source_image'], root)
        folder = Path(page.get('page_output_dir') or root / Path(page['source_image']).stem)
        roi = self._resolve(folder / 'table_roi.jpg', root)
        if source is None and roi is None:
            raise ValueError(f'{name}: 원본 스캔 또는 원본 좌표 table_roi.jpg가 필요합니다.')
        if source is None and not all(key in (page.get('table_roi') or {}) for key in ('x', 'y')):
            raise ValueError(f'{name}: ROI만 저장할 때는 원본 좌표 table_roi.x/y가 필요합니다.')
        scan_id = self._asset(conn, source) if source else None
        roi_id = self._asset(conn, roi) if roi else None
        active = not conn.execute('SELECT 1 FROM jokbo.ocr_runs WHERE page_id=%s AND active', (pid,)).fetchone()
        conn.execute('INSERT INTO jokbo.ocr_runs(page_id,digest,raw,scan_id,roi_id,active) VALUES (%s,%s,%s,%s,%s,%s)',
                     (pid, checksum, self.json(page), scan_id, roi_id, active))
        return 'added' if active else 'pending'

    def _pages(self, conn, eid):
        rows = conn.execute('''SELECT p.name,p.id,r.id,r.raw,r.scan_id,r.roi_id
            FROM jokbo.pages p JOIN jokbo.ocr_runs r ON r.page_id=p.id AND r.active
            WHERE p.edition_id=%s ORDER BY p.name''', (eid,)).fetchall()
        pages, locators = [], {}
        for name, pid, rid, raw, scan, roi in rows:
            page = deepcopy(raw)
            page.pop('asset_path', None)
            page.pop('roi_asset_path', None)
            if scan:
                page['asset_path'] = str(self.assets.path(scan))
            if roi:
                page['roi_asset_path'] = str(self.assets.path(roi))
            pages.append(page)
            locators[name] = (pid, rid)
        return pages, locators

    def load(self, eid):
        with self.connection() as conn:
            row = conn.execute('SELECT state,revision FROM jokbo.editions WHERE id=%s FOR SHARE', (eid,)).fetchone()
            if row is None:
                raise ValueError('판본을 찾을 수 없습니다: ' + eid)
            pages, _ = self._pages(conn, eid)
            people = [p for page in pages for p in page.get('people_candidates', [])]
            rels = [{**r, 'source_page': page_name(page)} for page in pages for r in page.get('relationship_candidates', [])]
            return pages, people, rels, row[0], row[1]

    def import_pages(self, pages, edition, root, state=None):
        """One transaction per import; file copies may leave harmless orphan assets."""
        root = Path(root).resolve()
        with self.connection() as conn:
            self._lock(conn)
            current, revision = self._edition(conn, edition, state)
            eid = edition['edition_id']
            if state:
                imported = conn.execute('SELECT import_digest FROM jokbo.editions WHERE id=%s', (eid,)).fetchone()[0]
                if revision and imported != digest(state):
                    raise ReviewConflict('기존 DB 검수가 있습니다. JSON 검수 상태로 덮어쓸 수 없습니다.')
                if not revision:
                    conn.execute('UPDATE jokbo.editions SET import_digest=%s WHERE id=%s', (digest(state), eid))
            results = [(page_name(page), self._import_page(conn, eid, page, root)) for page in pages]
            if any(status == 'added' for _, status in results) or not revision:
                self._project(conn, eid, current)
                self._snapshot(conn, eid, current, revision, 'import')
            return results

    def import_directory(self, root, edition_id=None):
        root = Path(root).resolve()
        pages, _, _, warnings = load_ocr_output(root)
        if warnings:
            raise ValueError('일부 페이지를 읽지 못해 가져오기를 취소합니다: ' + '; '.join(warnings))
        path = root / 'review_state.json'
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(state, dict):
            raise ValueError('검수 상태는 JSON 객체여야 합니다.')
        edition = state.get('edition') or {'edition_id': edition_id or 'jokbo-1987', 'publication_year': 1987}
        if edition_id and edition_id != edition['edition_id']:
            raise ValueError('기존 검수 상태와 --edition이 다릅니다. UID를 보존하려면 원래 판본을 사용하세요.')
        state['edition'] = edition
        # Promote supplemental source pages to the same immutable page storage.
        for entry in state.get('supplemental_pages', []):
            page = {**entry['page_result'], 'people_candidates': entry['people'], 'relationship_candidates': entry['relationships']}
            if page_name(page) not in {page_name(p) for p in pages}:
                pages.append(page)
        if not pages:
            raise ValueError('가져올 페이지가 없습니다.')
        return self.import_pages(pages, edition, root, state)

    def _snapshot(self, conn, eid, state, revision, reason):
        revision += 1
        conn.execute('UPDATE jokbo.editions SET state=%s, revision=%s WHERE id=%s', (self.json(state), revision, eid))
        conn.execute('INSERT INTO jokbo.reviews(edition_id,revision,state,reason) VALUES (%s,%s,%s,%s)',
                     (eid, revision, self.json(state), reason))
        return revision

    def save_review(self, eid, state, expected_revision):
        working = deepcopy(state)
        if (working.get('edition') or {}).get('edition_id') != eid:
            raise ValueError('검수 판본을 변경할 수 없습니다.')
        with self.connection() as conn:
            self._lock(conn)
            row = conn.execute('SELECT revision FROM jokbo.editions WHERE id=%s FOR UPDATE', (eid,)).fetchone()
            if row is None or row[0] != expected_revision:
                raise ReviewConflict('다른 창에서 검수 또는 OCR 페이지를 변경했습니다. 다시 열어 확인하세요.')
            for entry in working.get('supplemental_pages', []):
                page = {**entry['page_result'], 'people_candidates': entry['people'], 'relationship_candidates': entry['relationships']}
                if not conn.execute('SELECT 1 FROM jokbo.pages WHERE edition_id=%s AND name=%s', (eid, page_name(page))).fetchone():
                    self._import_page(conn, eid, page, Path.cwd())
            self._project(conn, eid, working)
            working['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            revision = self._snapshot(conn, eid, working, expected_revision, 'review')
        state.clear()
        state.update(working)
        return revision

    def _project(self, conn, eid, state):
        from review.core import build_review_data, relationship_key
        pages, locators = self._pages(conn, eid)
        base = [p for page in pages for p in page.get('people_candidates', [])]
        rels = [{**r, 'source_page': page_name(page)} for page in pages for r in page.get('relationship_candidates', [])]
        # The desktop state uses local IDs for edits; ambiguous IDs must never be applied.
        from review.extensions import merge_review_sources
        merged, _, _ = merge_review_sources(base, rels, pages, state)
        ids = [p.get('person_id') for p in merged]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('판본 내 인물 후보 ID가 비어 있거나 중복됩니다.')
        people, relationships = build_review_data(self.assets.root, base, rels, state, pages)
        for table in ('partners', 'parent_child', 'occurrences'):
            conn.execute(f'DELETE FROM jokbo.{table} WHERE edition_id=%s', (eid,))
        for person in people:
            conn.execute('INSERT INTO jokbo.persons(id) VALUES (%s) ON CONFLICT DO NOTHING', (person['person_uid'],))
        for person in people:
            uid = person['person_uid']
            reviewed = person['reviewed_data']
            for source in person['source_occurrences']:
                name = source.get('scan_page') or person['source_page']
                if name not in locators:
                    raise ValueError('출처 페이지를 찾을 수 없습니다: ' + name)
                pid, rid = locators[name]
                oid = uuid.uuid5(uuid.NAMESPACE_URL, f"{eid}/{person['person_id']}/{source['source_occurrence_id']}").hex
                conn.execute('''INSERT INTO jokbo.occurrences
                    (id,edition_id,page_id,run_id,person_id,local_id,name,status,source,raw,reviewed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (oid, eid, pid, rid, uid, person['person_id'], reviewed.get('name_hanja'),
                     reviewed.get('review_status', 'needs_review'), self.json(source), self.json(person['raw_data']), self.json(reviewed)))
            for index, partner in enumerate(reviewed.get('spouses') or []):
                conn.execute('''INSERT INTO jokbo.partners(edition_id,id,person_id,partner_id,kind,status,record)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                    (eid, f"{person['person_id']}:{index}", uid, partner.get('person_uid') or None,
                     partner.get('type', 'other'), partner.get('review_status', 'needs_review'),
                     self.json({'source_occurrences': person['source_occurrences'], **partner})))
        for rel in relationships:
            parent, child = rel.get('parent_person_uid'), rel.get('child_person_uid')
            if not parent or not child:
                raise ValueError('관계의 부모/자녀 후보를 찾을 수 없습니다: ' + relationship_key(rel))
            conn.execute('''INSERT INTO jokbo.parent_child(edition_id,id,parent_id,child_id,kind,status,evidence)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (eid, relationship_key(rel), parent, child, rel.get('parentage_type', 'unspecified'),
                 rel.get('review_status', 'needs_review'), self.json(rel)))

    def relatives(self, person_id, direction='ancestors', kind=None, max_depth=100):
        """Shortest generation distance; confirmed edges only, no path explosion."""
        if direction not in ('ancestors', 'descendants'):
            raise ValueError('ancestors 또는 descendants가 필요합니다.')
        if kind not in (None, 'unspecified', 'biological', 'adoptive') or not 1 <= max_depth <= 1000:
            raise ValueError('관계 유형 또는 최대 깊이가 올바르지 않습니다.')
        start, target = ('child_id', 'parent_id') if direction == 'ancestors' else ('parent_id', 'child_id')
        with self.connection() as conn:
            rows = conn.execute(f'''WITH RECURSIVE walk(id,depth) AS (
                SELECT %s::text, 0
                UNION
                SELECT e.{target}, w.depth+1 FROM walk w JOIN jokbo.parent_child e ON e.{start}=w.id
                WHERE e.status='confirmed' AND (%s::text IS NULL OR e.kind=%s)
                  AND w.depth < %s
            ) SELECT id,min(depth) FROM walk WHERE depth>0 AND id<>%s GROUP BY id ORDER BY min(depth),id''',
                (person_id, kind, kind, max_depth, person_id)).fetchall()
        return [{'person_id': uid, 'depth': depth} for uid, depth in rows]

    def common_ancestors(self, first, second, kind=None, max_depth=100):
        # One connection/snapshot for both walks, including self at depth zero.
        if kind not in (None, 'unspecified', 'biological', 'adoptive') or not 1 <= max_depth <= 1000:
            raise ValueError('관계 유형 또는 최대 깊이가 올바르지 않습니다.')
        with self.connection() as conn:
            existing = conn.execute('SELECT id FROM jokbo.persons WHERE id = ANY(%s)', ([first, second],)).fetchall()
            if {row[0] for row in existing} != {first, second}:
                raise ValueError('인물 ID를 찾을 수 없습니다.')
            rows = conn.execute('''WITH RECURSIVE walk(root,id,depth) AS (
                VALUES (1,%s::text,0),(2,%s::text,0)
                UNION
                SELECT w.root,e.parent_id,w.depth+1 FROM walk w JOIN jokbo.parent_child e ON e.child_id=w.id
                WHERE e.status='confirmed' AND (%s::text IS NULL OR e.kind=%s) AND w.depth<%s
            ), distances AS (SELECT root,id,min(depth) depth FROM walk GROUP BY root,id)
            SELECT a.id,a.depth,b.depth FROM distances a JOIN distances b USING(id)
            WHERE a.root=1 AND b.root=2 ORDER BY a.depth+b.depth,a.depth,b.depth,a.id''',
                (first, second, kind, kind, max_depth)).fetchall()
        return [{'person_id': uid, 'first_depth': a, 'second_depth': b} for uid, a, b in rows]

    def find_people(self, name):
        """Exact name search, without merging namesakes or implying confirmation."""
        with self.connection() as conn:
            rows = conn.execute('''SELECT DISTINCT person_id,name,status,edition_id
                FROM jokbo.occurrences WHERE name=%s ORDER BY person_id,edition_id,status''', (name,)).fetchall()
        return [dict(zip(('person_id', 'name', 'status', 'edition_id'), row)) for row in rows]

    def verify_assets(self):
        with self.connection() as conn:
            assets = conn.execute('SELECT id,size FROM jokbo.assets ORDER BY id').fetchall()
        problems = []
        for key, size in assets:
            path = self.assets.path(key)
            if not path.is_file() or path.stat().st_size != size or file_hash(path) != key:
                problems.append(key)
        return {'checked': len(assets), 'missing_or_corrupt': problems}

    def export(self, eid, target):
        """Explicit portable export to a NEW directory, never over a user's work."""
        from ocr.storage import save_page_result
        from review.core import build_review_data, write_exports
        target = Path(target).resolve()
        target.mkdir(parents=True, exist_ok=False)
        pages, people, rels, state, _ = self.load(eid)
        import shutil
        for page in pages:
            if page.get('asset_path'):
                image = target / 'scans' / page_name(page)
                image.parent.mkdir(exist_ok=True)
                shutil.copyfile(page.pop('asset_path'), image)
                page['original_source_image'] = page['source_image']
                page['source_image'] = str(image)
            if page.get('roi_asset_path'):
                folder = target / Path(page['source_image']).stem
                folder.mkdir(exist_ok=True)
                shutil.copyfile(page.pop('roi_asset_path'), folder / 'table_roi.jpg')
            save_page_result(target, page)
        exported, edges = build_review_data(target, people, rels, state, pages)
        (target / 'review_state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        write_exports(target, exported, edges)
