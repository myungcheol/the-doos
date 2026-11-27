"""Run the T019 importer against synthetic OCR in a disposable Compose DB."""
from copy import deepcopy
from pathlib import Path
import sys
import uuid
import tempfile

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from import_page import SCANS, analyze, connect, import_page, ingest_scan, prepare
from ocr_batch import create_batch, process_batch
from verify_db_schema import docker_script


def fixture(scan):
    size = cv2.imread(str(scan)).shape[:2]
    def region(text, x, y, w, h, band):
        return dict(text=text, score=.9, band=band, polygon=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    layout = dict(height=size[0], width=size[1], bands=[
        dict(bbox=[0,0,300,200], columns=[]), dict(bbox=[0,200,300,400], columns=[])])
    ocr = dict(image=dict(path=str(scan)), run=dict(timestamp_utc='2026-11-23T12:00:00+00:00',
        config=dict(lang='chinese_cht',ocr_version='PP-OCRv5',device='cpu'), paddleocr='fixture',
        initialization_seconds=0, inference_seconds=0), regions=[
        region('子甲乙',200,20,32,90,1), region('配金氏至正十六年卒妾李氏甲辰生',150,20,10,140,1),
        region('子丙丁',200,220,32,90,2), region('下53',204,325,20,30,2)])
    return scan, size, None, layout, ocr, analyze(ocr, layout, SCANS)


def verify(db):
    scan = SCANS / '001.jpg'
    prepared = fixture(scan)
    def one(query, params=()):
        return db.execute(query, params).fetchone()[0]

    broken = deepcopy(prepared)
    broken[-1]['parent_candidates']['relations'][0]['child'] = 999
    try:
        import_page(db, scan, broken)
    except IndexError:
        pass
    else:
        raise AssertionError('expected late failure')
    assert one('SELECT count(*) FROM genealogy.pages') == 0
    assert one('SELECT count(*) FROM genealogy.persons') == 0
    assert one('SELECT count(*) FROM genealogy.review_history') == 0

    first = import_page(db, scan, prepared)
    assert first['status'] == 'applied'
    assert one('SELECT count(*) FROM genealogy.marriages') == 2
    assert one('SELECT count(*) FROM genealogy.parent_child') == 1
    assert one('SELECT status FROM genealogy.page_reference_candidates') == 'scan_missing'
    fact, spouse = db.execute("SELECT id,subject_person_id FROM genealogy.person_facts WHERE kind='death' "
                             "AND gregorian_year=1356 AND month_assumed AND day_assumed").fetchone()
    assert one("SELECT count(*) FROM genealogy.marriages WHERE spouse_id=%s AND relation_type='spouse'", (spouse,)) == 1
    assert one('SELECT count(*) FROM genealogy.fact_sources WHERE fact_id=%s', (fact,)) == 1
    one("SELECT genealogy.review_values('fact',%s,%s,'test','verified')",
        (fact, '{"explanation_manual":"검수한 값"}'))
    one("SELECT genealogy.review_values('person',%s,%s,'test','verified')",
        (spouse, '{"name_unknown":false,"name_hanja":"校正"}'))
    edge = one('SELECT id FROM genealogy.parent_child')
    one("SELECT genealogy.review_relation(%s,'rejected',false,'test','incorrect')", (edge,))

    replay = import_page(db, scan, prepared)
    assert replay['replay'] and replay['import_id'] == first['import_id']
    rerun = deepcopy(prepared)
    rerun[-2]['run']['timestamp_utc'] = '2026-11-23T13:00:00+00:00'
    assert import_page(db, scan, rerun)['import_id'] == first['import_id']
    assert one('SELECT count(*) FROM genealogy.ocr_runs') == 1
    assert one('SELECT count(*) FROM genealogy.page_imports') == 1
    changed = deepcopy(rerun)
    changed[-1]['candidates'][0]['name_text'] = '子乙甲'
    revised = import_page(db, scan, changed)
    assert revised['status'] == 'needs_review'
    changed[-2]['run']['timestamp_utc'] = '2026-11-23T14:00:00+00:00'
    assert import_page(db, scan, changed)['import_id'] == revised['import_id']
    assert one('SELECT count(*) FROM genealogy.page_imports') == 2
    assert one('SELECT count(*) FROM genealogy.ocr_runs') == 2
    assert one('SELECT count(*) FROM genealogy.persons') == 4
    assert one('SELECT count(*) FROM genealogy.person_occurrences') == 2
    assert one('SELECT count(*) FROM genealogy.marriages') == 2
    assert one('SELECT explanation_manual FROM genealogy.current_facts WHERE id=%s', (fact,)) == '검수한 값'
    assert one('SELECT name_hanja FROM genealogy.current_persons WHERE id=%s', (spouse,)) == '校正'
    assert one('SELECT review_status FROM genealogy.parent_child WHERE id=%s', (edge,)) == 'rejected'
    unassigned = deepcopy(prepared)
    unassigned[-2]['regions'].append(dict(text='附記',score=.8,band=1,
                                        polygon=[[1,1],[10,1],[10,15],[1,15]]))
    extra = import_page(db, scan, unassigned)
    assert extra['status'] == 'needs_review'
    assert not extra['replay']  # Even OCR outside recognized people remains evidence.


def verify_batch(db, database):
    db.commit()
    db.autocommit = True
    scan = SCANS / '001.jpg'
    missing = SCANS / '053.jpg'
    batch = create_batch(db, [missing, scan, scan], False)
    calls = []
    def ingest(path, corrected):
        calls.append(path)
        if path == missing:
            return ingest_scan(path, corrected)
        return import_page(db, scan, fixture(scan))
    counts = process_batch(db, batch, ingest)
    assert counts['succeeded'] == 1 and counts['failed'] == 1
    calls.clear()
    process_batch(db, batch, ingest)
    assert calls == [missing]
    recovered = process_batch(db, batch, lambda path, corrected: import_page(db, scan, fixture(scan)))
    assert recovered['succeeded'] == 2 and recovered['failed'] == 0

    # Corrupt input fails before a transaction can insert page records.
    with tempfile.TemporaryDirectory() as tmp:
        corrupt = Path(tmp) / 'corrupt.jpg'
        corrupt.write_bytes(b'not an image')
        try:
            prepare(corrupt, False, None)
        except ValueError:
            pass
        else:
            raise AssertionError('corrupt scan accepted')

    resumed = create_batch(db, [scan, missing], True)
    calls.clear()
    def interrupt_after_commit(path, corrected):
        assert corrected
        import_page(db, scan, fixture(scan))
        raise KeyboardInterrupt
    try:
        process_batch(db, resumed, interrupt_after_commit)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError('expected interruption')
    assert db.execute('SELECT status FROM genealogy.ocr_batch_items WHERE batch_id=%s AND position=0',
                      (resumed,)).fetchone()[0] == 'running'
    counts = process_batch(db, resumed, ingest)
    assert counts['succeeded'] == 1 and counts['failed'] == 1
    assert db.execute('SELECT attempts,replay FROM genealogy.ocr_batch_items WHERE batch_id=%s AND position=0',
                      (resumed,)).fetchone() == (2, True)
    assert db.execute('SELECT count(*) FROM genealogy.persons').fetchone()[0] == 4
    with connect(database) as other:
        other.autocommit = True
        other.execute('SELECT pg_advisory_lock(2020,%s::integer)', (resumed,))
        try:
            process_batch(db, resumed, ingest)
        except ValueError:
            pass
        else:
            raise AssertionError('concurrent batch worker accepted')


if __name__ == '__main__':
    database = 'the_doos_import_test_' + uuid.uuid4().hex
    docker_script('createdb -U "$POSTGRES_USER" -- "$1"', database)
    try:
        with connect(database) as db:
            for path in sorted((ROOT / 'db/migrations').glob('*.up.sql')):
                db.execute(path.read_text())
            db.commit()
            verify(db)
            verify_batch(db, database)
        print('PASS: storage, rollback, duplicate skipping, review protection, batch retry and interruption')
    finally:
        docker_script('dropdb -U "$POSTGRES_USER" -- "$1"', database)
