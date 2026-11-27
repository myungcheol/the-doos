"""Import one genealogy scan using local Compose PostgreSQL and PaddleOCR."""
import argparse
import hashlib
from functools import lru_cache
from itertools import product
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from name_readings import DEFAULT_SOURCE, build_index, lookup_name
from person_candidates import analyze, box
from preprocess_page import deskew, preprocess

ROOT = Path(__file__).resolve().parents[1]
SCANS = ROOT / 'scan/genealogy'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def connect(database=None):
    if os.environ.get('PGDATABASE') or os.environ.get('PGSERVICE'):
        return psycopg.connect(**({'dbname': database} if database else {}))
    compose = ['docker', 'compose']
    # Capture only the three container settings; never log credentials or put
    # passwords on a command line. The published port may differ from 5432.
    values = subprocess.check_output(compose + ['exec', '-T', 'postgres', 'sh', '-c',
        'printf "%s\\0" "$POSTGRES_DB" "$POSTGRES_USER" "$POSTGRES_PASSWORD"'], cwd=ROOT)
    db, user, password, _ = values.decode().split('\0')
    port = subprocess.check_output(compose + ['port', 'postgres', '5432'], cwd=ROOT, text=True)
    return psycopg.connect(host='127.0.0.1', port=int(port.strip().rsplit(':', 1)[1]),
                           dbname=database or db, user=user, password=password)


def insert(db, table, **values):
    fields = sql.SQL(',').join(map(sql.Identifier, values))
    placeholders = sql.SQL(',').join(sql.Placeholder() for _ in values)
    query = sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING id').format(
        sql.Identifier(table), fields, placeholders)
    return db.execute(query, list(values.values())).fetchone()[0]


def coords(bbox):
    return dict(zip(('left_px', 'top_px', 'right_px', 'bottom_px'), bbox, strict=True))


def prepare(scan, corrected, saved_ocr):
    original = cv2.imread(str(scan))
    if original is None:
        raise ValueError('Cannot read scan')
    image = original
    rotation = None
    selected = scan
    if corrected:
        image, rotation = deskew(original)
        if rotation['applied']:
            ok, encoded = cv2.imencode('.png', image)
            if not ok:
                raise ValueError('Cannot encode corrected scan')
            payload = encoded.tobytes()
            selected = ROOT / 'data/ocr/deskew' / f'{scan.stem}-{digest(payload)}.png'
            selected.parent.mkdir(parents=True, exist_ok=True)
            # Publish an already-complete file; concurrent readers cannot see a partial PNG.
            with tempfile.NamedTemporaryFile(dir=selected.parent) as tmp:
                tmp.write(payload)
                tmp.flush()
                try:
                    os.link(tmp.name, selected)
                except FileExistsError:
                    if digest(selected.read_bytes()) != digest(payload):
                        raise ValueError('Corrected image content differs from its filename')
    layout = preprocess(image)
    if layout['status'] != 'candidate':
        raise ValueError('Page bands could not be identified')
    if saved_ocr:
        ocr = json.loads(saved_ocr.read_text())
    else:
        from ocr_image import recognize
        ocr = recognize(selected, layout)
    expected = (digest(selected.read_bytes()), layout['width'], layout['height'])
    if tuple(ocr['image'][k] for k in ('sha256', 'width', 'height')) != expected:
        raise ValueError('OCR checksum or dimensions do not match the selected scan')
    people = analyze(ocr, layout, SCANS)
    return selected, original.shape[:2], rotation, layout, ocr, people


def image_id(db, page, path, height, width, **fields):
    checksum = digest(path.read_bytes())
    stored = str(path.relative_to(ROOT))
    row = db.execute('SELECT id,sha256 FROM page_images WHERE page_id=%s AND storage_path=%s',
                     (page, stored)).fetchone()
    if row:
        if row[1] != checksum:
            raise ValueError('Previously registered image has changed')
        return row[0]
    return insert(db, 'page_images', page_id=page, storage_path=stored, sha256=checksum,
                  width=width, height=height, **fields)


def store_evidence(db, image, layout, ocr):
    run = ocr['run']
    config = run['config']
    finish = datetime.fromisoformat(run['timestamp_utc'])
    start = finish - timedelta(seconds=run['initialization_seconds'] + run['inference_seconds'])
    run_id = insert(db, 'ocr_runs', image_id=image, started_at=start, finished_at=finish,
                    status='succeeded', engine_version=run['paddleocr'], model_version=config['ocr_version'],
                    language=config['lang'], device=config['device'], code_version=run.get('code_version','unknown'),
                    configuration=Jsonb(config), environment=Jsonb(run), raw_result=Jsonb(ocr))
    bands = {}
    for n, band in enumerate(layout['bands'], 1):
        bands[n] = insert(db, 'ocr_regions', run_id=run_id, kind='band', reading_order=n-1, **coords(band['bbox']))
        for order, col in enumerate(band['columns']):
            insert(db, 'ocr_regions', run_id=run_id, kind='column', parent_region_id=bands[n],
                   reading_order=order, **coords(col['bbox']))
    regions = {}
    for order, region in enumerate(ocr['regions']):
        if not region['polygon']:
            continue
        key = (tuple(box(region)), region['text'])
        region_id = insert(db, 'ocr_regions', run_id=run_id, kind='text', reading_order=order,
                           parent_region_id=bands[region['band']] if 'band' in region else None,
                           raw_text=region['text'], confidence=region['score'], polygon=Jsonb(region['polygon']),
                           metadata=Jsonb({'ocr_index': order}), **coords(key[0]))
        if key in regions:
            raise ValueError('OCR contains indistinguishable source regions')
        regions[key] = region_id
    return run_id, regions


def original_bounds(bbox, rotation, size):
    if not rotation or not rotation['applied']:
        return bbox
    a, b = rotation['inverse_matrix']
    corners = [(x,y) for x in bbox[::2] for y in bbox[1::2]]
    xs = [a[0]*x+a[1]*y+a[2] for x,y in corners]
    ys = [b[0]*x+b[1]*y+b[2] for x,y in corners]
    height, width = size
    return [max(0,min(xs)), max(0,min(ys)), min(width,max(xs)), min(height,max(ys))]


def save_fact(db, item, owner, subject, occurrence, info, regions, version):
    date = item.get('date', {})
    date_columns = ('year_text','month_text','day_text','year_number','calendar','leap_month',
                    'gregorian_year','normalized_month','normalized_day','month_assumed','day_assumed',
                    'conversion_status')
    fields = {key: date[key] for key in date_columns if key in date}
    # Invalid OCR numbers stay in the evidence JSON and original text.
    fields.update(month=date.get('normalized_month') if not date.get('month_assumed') else None,
                  day=date.get('normalized_day') if not date.get('day_assumed') else None)
    fact = insert(db, 'person_facts', subject_person_id=subject, recorded_person_id=owner,
                  occurrence_id=occurrence, kind=item['kind'], raw_text=item['raw'], origin='automatic',
                  explanation_automatic=item.get('explanation',{}).get('automatic'), parser_version=str(version),
                  date_details=Jsonb(date), **fields)
    fragments = []
    for n, ref in enumerate(item['source_refs']):
        source = info[ref['region_index']]
        region = regions[tuple(source['bbox']), source['text']]
        fragments.append(source['text'][ref['start']:ref['end']])
        db.execute('INSERT INTO fact_sources VALUES (%s,%s,%s,%s,%s)',
                   (fact, region, ref['start'], ref['end'], n))
    if ''.join(fragments) != item['raw']:
        raise ValueError('Fact source text differs from extraction')
    return fact


def store_facts(db, person, owner, occurrence, regions, version):
    spouses = {p['id']:p for p in person['spouses']['people']}
    def save(item, subject):
        return save_fact(db, item, owner, subject, occurrence, person['information_candidates'], regions, version)

    for item in person['information']['items']:
        if item['kind'] != 'spouse_information':
            save(item, owner)
            continue
        subject = item['subject']
        spouse = spouses.get(subject['id'])
        spouse_id = insert(db, 'persons', name_unknown=True) if spouse else None
        fact = save(item, spouse_id)
        if spouse:
            db.execute('SELECT ingest_marriage(%s,%s,%s,%s)', (owner, spouse_id, subject['relation_type'], fact))
            for child in spouse['information_items']:
                save(child, spouse_id)
            for child in spouse['unresolved_items']:
                save(child, None)
        else:
            for child in item['items']:
                save(child, None)


@lru_cache(maxsize=1)
def reading_dictionary():
    return build_index(), digest(DEFAULT_SOURCE.read_bytes())


def store_readings(db, owner, name):
    index, version = reading_dictionary()
    characters = lookup_name(name, index)['characters']
    for choices in product(*(c['candidates'] for c in characters)):
        reading = ''.join(c['reading'] for c in choices)
        insert(db, 'person_readings', person_id=owner, name_hanja_snapshot=name, reading=reading, status='candidate',
               origin='automatic', source='local_name_hanja_table', source_version=version,
               details=Jsonb({'characters': characters}))


def store_people(db, import_id, baseline, people, original, rotation, size, regions):
    endpoints = []
    for index, person in enumerate(people['candidates']):
        if baseline:
            occurrence, owner = db.execute(
                'SELECT o.id,o.person_id FROM import_occurrences m JOIN person_occurrences o ON o.id=m.occurrence_id '
                'WHERE m.import_id=%s AND m.candidate_index=%s', (baseline, index)).fetchone()
        else:
            marker = person['marker']
            bbox = original_bounds(person['name_bbox'], rotation, size)
            occurrence = insert(db, 'person_occurrences', original_image_id=original, marker_raw=marker,
                                female_entry_status='unresolved' if marker in ('女','女') else 'not_applicable',
                                **coords(bbox))
            name = person['name_text']
            if marker in ('子','女','女'):
                name = name.removeprefix(marker)
            owner = db.execute('SELECT ingest_person(%s,%s)', (occurrence, name or None)).fetchone()[0]
            if name:
                store_readings(db, owner, name)
            store_facts(db, person, owner, occurrence, regions, people['information_parser_version'])
        db.execute('INSERT INTO import_occurrences VALUES (%s,%s,%s)', (import_id, index, occurrence))
        for r in person['source_regions']:
            key = (tuple(r.get('source_ocr_bbox', r['bbox'])), r.get('source_ocr_text', r['text']))
            db.execute('INSERT INTO occurrence_sources VALUES (%s,%s) ON CONFLICT DO NOTHING',
                       (occurrence, regions[key]))
        endpoints.append((occurrence, owner))
    if not baseline:
        for relation in people['parent_candidates']['relations']:
            parent, child = endpoints[relation['parent']], endpoints[relation['child']]
            insert(db, 'parent_child', parent_occurrence_id=parent[0], parent_id=parent[1],
                   child_occurrence_id=child[0], child_id=child[1], method=relation['method'],
                   evidence=Jsonb(relation))
    return endpoints


def import_page(db, scan, prepared):
    selected, size, rotation, layout, ocr, people = prepared
    # Execution timestamps and timings do not change the recognized content.
    artifact = fingerprint(ocr)
    projection = fingerprint({k:v for k,v in people.items() if k != 'image'})
    with db.transaction():
        db.execute('SET LOCAL search_path TO genealogy, pg_catalog')
        db.execute('SELECT pg_advisory_xact_lock(1987,%s)', (int(scan.stem),))
        db.execute("INSERT INTO pages(section,page_key,sort_order,scan_status) VALUES ('genealogy',%s,%s,'available') "
                   "ON CONFLICT(section,page_key) DO NOTHING", (scan.stem, 66 + int(scan.stem)))
        page = db.execute("SELECT id FROM pages WHERE section='genealogy' AND page_key=%s", (scan.stem,)).fetchone()[0]
        original = image_id(db, page, scan, *size, variant='original')
        image = original
        if selected != scan:
            image = image_id(db, page, selected, layout['height'], layout['width'], variant='deskewed',
                             original_image_id=original, rotation_degrees=rotation['angle_degrees'],
                             forward_matrix=sum(rotation['matrix'], []), inverse_matrix=sum(rotation['inverse_matrix'], []))
        previous = db.execute('SELECT i.id,i.status,i.run_id,r.raw_result FROM page_imports i '
                              'JOIN ocr_runs r ON r.id=i.run_id WHERE i.page_id=%s AND r.image_id=%s '
                              'AND i.projection_hash=%s ORDER BY i.id', (page, image, projection)).fetchall()
        for prior in previous:
            if prior[3]['regions'] == ocr['regions'] and prior[3].get('vertical_retries') == ocr.get('vertical_retries'):
                return dict(import_id=prior[0], status=prior[1], run_id=prior[2], replay=True,
                            message='같은 결과가 이미 저장되어 있어 건너뜁니다.')
        baseline = db.execute("SELECT id,projection_hash FROM page_imports WHERE page_id=%s AND status='applied'",
                              (page,)).fetchone()
        if baseline is None:
            existing = db.execute('SELECT 1 FROM person_occurrences WHERE original_image_id=%s LIMIT 1',
                                  (original,)).fetchone()
            if existing:
                raise ValueError('Page already has unmapped occurrences; reconcile before importing')
            status = 'applied'
        else:
            status = 'needs_review'
        same_run = db.execute('SELECT run_id FROM page_imports WHERE page_id=%s AND artifact_hash=%s LIMIT 1',
                              (page, artifact)).fetchone()
        if same_run:
            run = same_run[0]
            rows = db.execute("SELECT left_px,top_px,right_px,bottom_px,raw_text,id FROM ocr_regions "
                              "WHERE run_id=%s AND kind='text'", (run,))
            regions = {(tuple(row[:4]), row[4]): row[5] for row in rows}
        else:
            run, regions = store_evidence(db, image, layout, ocr)
        import_id = insert(db, 'page_imports', page_id=page, run_id=run, artifact_hash=artifact,
                           projection_hash=projection, status=status, extraction=Jsonb(people))
        endpoints = []
        if status != 'needs_review':
            endpoints = store_people(db, import_id, baseline[0] if baseline else None, people, original,
                                     rotation, size, regions)
        for ref in people['page_references']:
            source = endpoints[ref['person']][0] if endpoints and ref['person'] is not None else None
            db.execute('INSERT INTO page_reference_candidates VALUES (%s,%s,%s,%s,%s,%s,%s)',
                       (import_id, regions[tuple(ref['bbox']),ref['raw']], source, f"{ref['target_page']:03}",
                        ref['direction'], ref['status'], ref['ocr_direction_uncertain']))
        return dict(import_id=import_id, status=status, run_id=run, replay=False)


def ingest_scan(scan, corrected=False, saved_ocr=None):
    scan = scan.resolve()
    if scan.parent != SCANS or not re.fullmatch(r'[0-9]{3}\.jpg', scan.name) or not scan.is_file():
        raise ValueError('select an existing scan/genealogy/NNN.jpg')
    prepared = prepare(scan, corrected, saved_ocr)
    with connect() as db:
        return import_page(db, scan, prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scan', type=Path)
    parser.add_argument('--ocr', type=Path, help='reuse OCR JSON from the selected image')
    parser.add_argument('--deskew', action='store_true', help='use corrected image when indicated')
    args = parser.parse_args()
    result = ingest_scan(args.scan, args.deskew, args.ocr)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
