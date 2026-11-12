"""Set JOKBO_TEST_DATABASE_URL to a disposable DB for PostgreSQL integration tests.

No tables are dropped/truncated; each test uses a fresh edition and synthetic data.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import cv2
import numpy as np

from database.store import (AssetStore, DatabaseError, PostgresStore, ReviewConflict,
                            load_database_environment)
from ocr.storage import save_page_result
from review.core import get_page_image


def fixture(root, name='001.png'):
    image = root / name
    cv2.imwrite(str(image), np.full((80, 100, 3), 255, dtype=np.uint8))
    people = [{'person_id': f'{Path(name).stem}_p{i}', 'source_page': name,
               'raw_name_ocr': '子甲' if i == 1 else '女乙',
               'name_hanja_candidate': '子甲' if i == 1 else '女乙',
               'bbox': {'x': 10*i, 'y': 10, 'width': 5, 'height': 20},
               'source_row_id': 'row1', 'source_column_id': f'col{i}',
               'review_status': 'needs_review'} for i in range(1, 5)]
    return {'schema_version': 1, 'source_image': str(image), 'source_page': name,
            'rows': [], 'people_candidates': people,
            'relationship_candidates': [], 'page_geometry': {'custom': '보존'},
            'unknown_future_field': {'한자': '原文', 'confidence': 72.3}}


class AssetTests(unittest.TestCase):
    def test_dotenv_loads_database_settings_without_overriding_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / '.env'
            env_file.write_text(
                'DATABASE_URL=postgresql://file-user:file-pass@db/file-db\n'
                'JOKBO_ASSET_ROOT=./file-assets\n', encoding='utf-8'
            )
            keys = ('DATABASE_URL', 'JOKBO_DATABASE_URL', 'JOKBO_ASSET_ROOT')
            saved = {key: os.environ.get(key) for key in keys}
            try:
                for key in keys:
                    os.environ.pop(key, None)
                load_database_environment(env_file)
                store = PostgresStore(env_file=env_file)
                self.assertEqual(store.dsn, 'postgresql://file-user:file-pass@db/file-db')
                self.assertEqual(store.assets.root, Path(__file__).resolve().parents[2] / 'file-assets')
                os.environ['DATABASE_URL'] = 'postgresql://shell/db'
                self.assertEqual(PostgresStore(env_file=env_file).dsn, 'postgresql://shell/db')
            finally:
                for key in keys:
                    if saved[key] is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = saved[key]

    def test_identical_copy_checksum_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            page = fixture(root)
            store = AssetStore(root / 'assets')
            asset = store.put(page['source_image'])
            self.assertEqual(asset, store.put(page['source_image']))
            self.assertEqual(store.path(asset[0]).read_bytes(), Path(page['source_image']).read_bytes())
            store.path(asset[0]).write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, '체크섬'):
                store.put(page['source_image'])

    def test_managed_scan_and_roi_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            page = fixture(root)
            store = AssetStore(root / 'assets')
            key, _, _ = store.put(page['source_image'])
            page['asset_path'] = str(store.path(key))
            Path(page['source_image']).unlink()
            _, offset, _ = get_page_image(page, root)
            self.assertEqual(offset, (0, 0))
            page['roi_asset_path'] = page.pop('asset_path')
            page['table_roi'] = {'x': 7, 'y': 13}
            _, offset, _ = get_page_image(page, root)
            self.assertEqual(offset, (7, 13))

    def test_postgres_cli_writes_directly_and_reports_partial_failure(self):
        from ocr.jokbo_ocr import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            page = fixture(root)
            output = root / 'out'
            with patch('sys.argv', ['ocr', page['source_image'], '--storage', 'postgres', '--output', str(output)]), \
                    patch('ocr.jokbo_ocr.initialize_paddle_ocr'), \
                    patch('database.store.PostgresStore') as store, \
                    patch('ocr.jokbo_ocr.ocr_one_image', return_value={**page, 'elapsed_seconds': 0, 'page_geometry': {}}):
                store.return_value.import_pages.return_value = [('001.png', 'added')]
                self.assertEqual(main(), 0)
                self.assertFalse(list(output.rglob('*.json')))
                store.return_value.import_pages.side_effect = DatabaseError('test')
                self.assertEqual(main(), 1)


@unittest.skipUnless(os.environ.get('JOKBO_TEST_DATABASE_URL'), '별도 PostgreSQL 테스트 DB 미지정')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PostgresStore(os.environ['JOKBO_TEST_DATABASE_URL'], self.root / 'assets')
        self.store.initialize()
        self.eid = 'test-' + uuid.uuid4().hex
        self.edition = {'edition_id': self.eid, 'publication_year': 1987}
        self.page = fixture(self.root)

    def import_page(self, state=None):
        return self.store.import_pages([self.page], self.edition, self.root, state)

    def rows(self, sql, params=()):
        with self.store.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def ids(self):
        return dict(self.rows('SELECT local_id,person_id FROM jokbo.occurrences WHERE edition_id=%s', (self.eid,)))

    def edge(self, name, parent, child, status='confirmed', kind='unspecified'):
        return {'relationship_id': name, 'source_page': '001.png', 'parent_candidate_id': parent,
                'child_candidate_id': child, 'review_status': status, 'parentage_type': kind}

    def test_import_idempotence_unknown_fields_and_uid_preservation(self):
        from review.data_model import person_local_key
        stable = 'PER_' + uuid.uuid4().hex.upper()
        key = person_local_key(self.page['people_candidates'][0], self.eid)
        state = {'edition': self.edition, 'person_uid_map': {key: stable}, 'custom': {'keep': True},
                 'people_updates': {'001_p1': {'notes': '검수 기록'}}}
        before = deepcopy(state)
        self.assertEqual(self.import_page(state)[0][1], 'added')
        self.assertEqual(state, before)
        self.assertEqual(self.import_page(state)[0][1], 'unchanged')
        pages, _, _, loaded, revision = self.store.load(self.eid)
        self.assertEqual(revision, 1)
        self.assertEqual(loaded['custom'], state['custom'])
        self.assertEqual(self.ids()['001_p1'], stable)
        self.assertEqual(pages[0]['unknown_future_field'], self.page['unknown_future_field'])
        raw, reviewed = self.rows('SELECT raw,reviewed FROM jokbo.occurrences WHERE edition_id=%s AND local_id=%s', (self.eid, '001_p1'))[0]
        self.assertEqual(raw['name_ocr']['raw_text'], '子甲')
        self.assertEqual(reviewed['name_hanja'], '甲')
        self.assertEqual(reviewed['notes'], '검수 기록')

    def test_changed_ocr_is_pending_without_rebinding_review(self):
        self.import_page()
        _, _, _, state, rev = self.store.load(self.eid)
        state['people_updates'] = {'001_p1': {'transcribed_name_hanja': '手修', 'review_status': 'confirmed'}}
        self.store.save_review(self.eid, state, rev)
        ids = self.ids()
        self.page['people_candidates'][0]['bbox']['x'] += 30
        self.page['people_candidates'][0]['raw_name_ocr'] = 'changed'
        self.assertEqual(self.import_page()[0][1], 'pending')
        self.assertEqual(self.import_page()[0][1], 'pending')
        pages, _, _, saved, new_rev = self.store.load(self.eid)
        self.assertEqual(pages[0]['people_candidates'][0]['raw_name_ocr'], '子甲')
        self.assertEqual(saved, state)
        self.assertEqual(new_rev, rev + 1)
        self.assertEqual(ids, self.ids())
        self.assertEqual(self.rows('SELECT count(*) FROM jokbo.ocr_runs r JOIN jokbo.pages p ON p.id=r.page_id WHERE p.edition_id=%s', (self.eid,))[0][0], 2)

    def test_graph_multiple_children_parents_statuses_depth_and_common(self):
        self.import_page()
        _, _, _, state, rev = self.store.load(self.eid)
        state['manual_relationships'] = [self.edge('a', '001_p1', '001_p2'),
            self.edge('b', '001_p1', '001_p3'), self.edge('c', '001_p2', '001_p4', kind='adoptive'),
            self.edge('d', '001_p3', '001_p4', 'needs_review')]
        self.store.save_review(self.eid, state, rev)
        ids = self.ids()
        ancestors = self.store.relatives(ids['001_p4'])
        self.assertEqual(ancestors, [{'person_id': ids['001_p2'], 'depth': 1}, {'person_id': ids['001_p1'], 'depth': 2}])
        self.assertEqual(len(self.store.relatives(ids['001_p1'], 'descendants')), 3)
        self.assertEqual(len(self.store.relatives(ids['001_p4'], max_depth=1)), 1)
        self.assertEqual(self.store.relatives(ids['001_p4'], kind='biological'), [])
        self.assertEqual(self.store.common_ancestors(ids['001_p2'], ids['001_p3']),
                         [{'person_id': ids['001_p1'], 'first_depth': 1, 'second_depth': 1}])
        self.assertEqual(self.store.common_ancestors(ids['001_p1'], ids['001_p4'])[0]['first_depth'], 0)

    def test_cycle_duplicate_fk_and_conflict_rollback(self):
        self.import_page()
        _, _, _, state, rev = self.store.load(self.eid)
        stale = deepcopy(state)
        state['manual_relationships'] = [self.edge('a', '001_p1', '001_p2')]
        new_rev = self.store.save_review(self.eid, state, rev)
        with self.assertRaises(ReviewConflict):
            self.store.save_review(self.eid, stale, rev)
        saved = deepcopy(state)
        for bad in (self.edge('cycle', '001_p2', '001_p1'), self.edge('duplicate', '001_p1', '001_p2'),
                    self.edge('self', '001_p3', '001_p3'), self.edge('missing', '001_p3', 'absent')):
            state = deepcopy(saved)
            state['manual_relationships'].append(bad)
            with self.assertRaises((DatabaseError, ValueError)):
                self.store.save_review(self.eid, state, new_rev)
            self.assertEqual(self.store.load(self.eid)[3:], (saved, new_rev))
        self.assertEqual(len(self.rows('SELECT * FROM jokbo.parent_child WHERE edition_id=%s', (self.eid,))), 1)

    def test_partners_multiple_types_unknown_identity_and_known_identity(self):
        self.import_page()
        _, _, _, state, rev = self.store.load(self.eid)
        state['people_updates'] = {'001_p1': {'spouses': [
            {'type': 'wife', 'name_and_record': '甲氏', 'review_status': 'confirmed', 'person_uid': self.ids()['001_p2']},
            {'type': 'wife', 'name_and_record': '乙氏'},
            {'type': 'concubine', 'name_and_record': '丙氏'},
            {'type': 'concubine', 'name_and_record': '丁氏'}]}}
        self.store.save_review(self.eid, state, rev)
        rows = self.rows('SELECT kind,partner_id FROM jokbo.partners WHERE edition_id=%s', (self.eid,))
        self.assertEqual([x[0] for x in rows].count('wife'), 2)
        self.assertEqual([x[0] for x in rows].count('concubine'), 2)
        self.assertEqual(sum(uid is None for _, uid in rows), 3)

    def test_import_export_existing_state_and_images_survive_source_removal(self):
        save_page_result(self.root, self.page)
        state = {'edition': self.edition, 'custom': 'keep', 'people_updates': {'001_p1': {'notes': '수기'}}}
        path = self.root / 'review_state.json'
        path.write_text(json.dumps(state))
        before = path.read_bytes()
        self.store.import_directory(self.root)
        self.store.import_directory(self.root)
        self.assertEqual(path.read_bytes(), before)
        source_bytes = Path(self.page['source_image']).read_bytes()
        Path(self.page['source_image']).unlink()
        pages, _, _, _, _ = self.store.load(self.eid)
        self.assertEqual(get_page_image(pages[0], self.root)[1], (0, 0))
        target = self.root / 'export'
        self.store.export(self.eid, target)
        self.assertEqual((target / 'scans' / '001.png').read_bytes(), source_bytes)
        exported = json.loads((target / 'review_state.json').read_text())
        self.assertEqual(exported['custom'], 'keep')
        self.assertEqual(exported['people_updates'], state['people_updates'])
        self.assertEqual(json.loads((target / '001/page.json').read_text())['unknown_future_field'], self.page['unknown_future_field'])
        with self.assertRaises(FileExistsError):
            self.store.export(self.eid, target)

    def test_missing_image_and_bad_local_ids_roll_back_import(self):
        second = fixture(self.root, '002.png')
        Path(second['source_image']).unlink()
        with self.assertRaises(ValueError):
            self.store.import_pages([self.page, second], self.edition, self.root)
        self.assertEqual(self.rows('SELECT * FROM jokbo.editions WHERE id=%s', (self.eid,)), [])
        second = fixture(self.root, '002.png')
        second['people_candidates'][0]['person_id'] = '001_p1'
        with self.assertRaisesRegex(ValueError, '중복'):
            self.store.import_pages([self.page, second], self.edition, self.root)

    def test_roi_only_import_and_metadata_conflict(self):
        folder = self.root / '001'
        folder.mkdir()
        source = Path(self.page['source_image'])
        source.rename(folder / 'table_roi.jpg')
        self.page['page_output_dir'] = str(folder)
        with self.assertRaisesRegex(ValueError, 'table_roi.x/y'):
            self.import_page()
        self.page['table_roi'] = {'x': 11, 'y': 17, 'width': 100, 'height': 80}
        self.import_page()
        pages, _, _, _, _ = self.store.load(self.eid)
        self.assertEqual(get_page_image(pages[0], self.root)[1], (11, 17))
        with self.assertRaisesRegex(ValueError, 'publication_year'):
            self.store.import_pages([self.page], {**self.edition, 'publication_year': 2000}, self.root)
        key = Path(pages[0]['roi_asset_path']).name
        self.assertNotIn(key, self.store.verify_assets()['missing_or_corrupt'])
        Path(pages[0]['roi_asset_path']).write_bytes(b'corrupted')
        self.assertIn(key, self.store.verify_assets()['missing_or_corrupt'])

    def test_cross_edition_identity_and_cycle_detection(self):
        self.import_page()
        first_ids = self.ids()
        second = deepcopy(self.page)
        for person in second['people_candidates']:
            person['person_uid'] = first_ids[person['person_id']]
        eid2 = 'test-' + uuid.uuid4().hex
        self.store.import_pages([second], {'edition_id': eid2, 'publication_year': 2000}, self.root)
        _, _, _, state, rev = self.store.load(self.eid)
        state['manual_relationships'] = [self.edge('a', '001_p1', '001_p2')]
        self.store.save_review(self.eid, state, rev)
        _, _, _, other, other_rev = self.store.load(eid2)
        other['manual_relationships'] = [self.edge('reverse', '001_p2', '001_p1')]
        with self.assertRaises(DatabaseError):
            self.store.save_review(eid2, other, other_rev)
        found = self.store.find_people('甲')
        self.assertEqual({item['edition_id'] for item in found if item['person_id'] == first_ids['001_p1']}, {self.eid, eid2})
        # Same text without explicit identity is a different person in a new edition.
        eid3 = 'test-' + uuid.uuid4().hex
        self.store.import_pages([self.page], {'edition_id': eid3}, self.root)
        new_id = self.rows('SELECT person_id FROM jokbo.occurrences WHERE edition_id=%s AND local_id=%s', (eid3, '001_p1'))[0][0]
        self.assertNotEqual(new_id, first_ids['001_p1'])

    def test_concurrent_writers_only_one_revision_commits(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.import_page()
        _, _, _, state, revision = self.store.load(self.eid)
        barrier = Barrier(2)

        def save(note):
            working = deepcopy(state)
            working['people_updates'] = {'001_p1': {'notes': note}}
            barrier.wait(timeout=10)
            try:
                self.store.save_review(self.eid, working, revision)
                return True
            except ReviewConflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['first', 'second']))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.store.load(self.eid)[4], revision + 1)

    def test_continuation_and_recovered_candidates_preserve_evidence(self):
        from review.extensions import make_continuation
        second = fixture(self.root, '002.png')
        second['people_candidates'] = []
        column = {'column_id': '002_col1', 'text': '原文 生',
                  'bbox': {'x': 20, 'y': 20, 'width': 5, 'height': 30}, 'confidence': 61,
                  'tokens': [{'text': '生', 'bbox': {'x': 20, 'y': 40, 'width': 5, 'height': 10}}]}
        row = {'row_id': '002_row1', 'row_number': 1, 'columns': [column]}
        second['rows'] = [row]
        self.store.import_pages([self.page, second], self.edition, self.root)
        _, _, _, state, revision = self.store.load(self.eid)
        state['continuation_links'] = [make_continuation(second, row, [column], self.page['people_candidates'][0], state)]
        recovered = {**self.page['people_candidates'][0], 'person_id': '001_recovered',
                     'bbox': {'x': 80, 'y': 40, 'width': 5, 'height': 10}, 'source_column_id': 'new'}
        state['additional_people'] = [recovered]
        self.store.save_review(self.eid, state, revision)
        sources = self.rows('SELECT source,raw FROM jokbo.occurrences WHERE edition_id=%s AND local_id=%s', (self.eid, '001_p1'))
        self.assertEqual(len(sources), 2)
        extra = next(source for source, _ in sources if source.get('occurrence_type') == 'record_continuation')
        self.assertEqual(extra['scan_page'], '002.png')
        self.assertEqual(extra['bbox'], column['bbox'])
        self.assertIn('001_recovered', self.ids())

    def test_no_selection_desktop_db_save_reload_and_stale_save(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            from review.desktop_review import ReviewWindow
        except ImportError:
            self.skipTest('PySide6 미설치')
        app = QApplication.instance() or QApplication([])
        self.import_page()
        window = ReviewWindow(store=self.store, edition=self.eid)
        try:
            self.assertIsNone(window.selected_id)
            self.assertFalse(window.pixmap.isNull())
            window.select_person_id('001_p1')
            window.inputs['notes'].setPlainText('DB에서 검수')
            window.save_person()
            self.assertEqual(self.store.load(self.eid)[3]['people_updates']['001_p1']['notes'], 'DB에서 검수')
            _, _, _, state, revision = self.store.load(self.eid)
            self.store.save_review(self.eid, state, revision)
            with patch.object(QMessageBox, 'critical') as warning:
                self.assertFalse(window.persist())
                warning.assert_called_once()
            window.open_database()
            self.assertIsNone(window.selected_id)
            self.assertFalse((self.store.assets.root / 'review_state.json').exists())
        finally:
            window.dirty = False
            window.close()
            app.processEvents()
