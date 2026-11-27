"""Process genealogy scans sequentially, with durable progress and retry in PostgreSQL."""
import argparse
from pathlib import Path

from import_page import connect, ingest_scan


def create_batch(db, paths, deskew):
    unique = list(dict.fromkeys(str(path.resolve()) for path in paths))
    with db.transaction():
        batch = db.execute('INSERT INTO genealogy.ocr_batches(deskew) VALUES (%s) RETURNING id',
                           (deskew,)).fetchone()[0]
        for position, path in enumerate(unique):
            db.execute('INSERT INTO genealogy.ocr_batch_items(batch_id,position,scan_path) VALUES (%s,%s,%s)',
                       (batch, position, path))
    return batch


def summary(db, batch):
    rows = db.execute('SELECT position,scan_path,status,attempts,import_id,replay,error '
                      'FROM genealogy.ocr_batch_items WHERE batch_id=%s ORDER BY position', (batch,)).fetchall()
    counts = {state: sum(row[2] == state for row in rows)
              for state in ('pending','running','succeeded','failed')}
    for _, path, status, attempts, import_id, replay, error in rows:
        detail = error or ('이미 저장됨' if replay else f'적재 {import_id}' if import_id else '')
        print(f'{Path(path).name}: {status} · 시도 {attempts} · {detail}', flush=True)
    print(f'배치 {batch} · 전체 {len(rows)} · 성공 {counts["succeeded"]} · 실패 {counts["failed"]} '
          f'· 대기 {counts["pending"]} · 처리 중 {counts["running"]}', flush=True)
    return counts


def process_batch(db, batch, ingest=ingest_scan):
    # Session lock survives per-item commits and is released on process death.
    locked = db.execute('SELECT pg_try_advisory_lock(2020,%s::integer)', (batch,)).fetchone()[0]
    if not locked:
        raise ValueError('이 배치를 다른 프로세스가 처리 중입니다.')
    try:
        row = db.execute('SELECT deskew FROM genealogy.ocr_batches WHERE id=%s', (batch,)).fetchone()
        if row is None:
            raise ValueError('해당 배치가 없습니다.')
        items = db.execute("SELECT position,scan_path FROM genealogy.ocr_batch_items "
                           "WHERE batch_id=%s AND status<>'succeeded' ORDER BY position", (batch,)).fetchall()
        for position, path in items:
            db.execute("UPDATE genealogy.ocr_batch_items SET status='running',attempts=attempts+1,"
                       "started_at=now(),finished_at=NULL,error=NULL WHERE batch_id=%s AND position=%s",
                       (batch, position))
            print(f'배치 {batch} · {Path(path).name} 처리 중', flush=True)
            try:
                result = ingest(Path(path), corrected=row[0])
            except Exception as error:
                # DB exceptions can include credential-bearing connection strings.
                detail = str(error) if isinstance(error, (ValueError, FileNotFoundError)) else type(error).__name__
                db.execute("UPDATE genealogy.ocr_batch_items SET status='failed',finished_at=now(),error=%s "
                           'WHERE batch_id=%s AND position=%s', (detail[:2000], batch, position))
                print(f'{Path(path).name} 실패 · {detail}', flush=True)
            else:
                db.execute("UPDATE genealogy.ocr_batch_items SET status='succeeded',finished_at=now(),"
                           'import_id=%s,replay=%s WHERE batch_id=%s AND position=%s',
                           (result['import_id'], result['replay'], batch, position))
                print(f'{Path(path).name} · {result.get("message", result["status"])}', flush=True)
        return summary(db, batch)
    finally:
        db.execute('SELECT pg_advisory_unlock(2020,%s::integer)', (batch,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scans', nargs='*', type=Path)
    parser.add_argument('--list', type=Path, help='UTF-8 file with one scan path per line, relative to this file')
    parser.add_argument('--deskew', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--retry', type=int, help='retry failed, interrupted and pending items in a batch')
    mode.add_argument('--status', type=int, help='show stored progress without processing')
    args = parser.parse_args()
    if args.retry is not None or args.status is not None:
        if args.scans or args.list or args.deskew:
            parser.error('retry/status uses the saved file list and options')
    elif not args.scans and not args.list:
        parser.error('provide scan paths or --list')
    paths = args.scans
    if args.list:
        for line in args.list.read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                paths.append(args.list.resolve().parent / line.strip())
    if args.retry is None and args.status is None and not paths:
        parser.error('the file list is empty')
    with connect() as db:
        db.autocommit = True
        if args.status is not None:
            if not db.execute('SELECT id FROM genealogy.ocr_batches WHERE id=%s', (args.status,)).fetchone():
                parser.error('batch does not exist')
            summary(db, args.status)
            return 0
        batch = args.retry if args.retry is not None else create_batch(db, paths, args.deskew)
        print(f'배치 {batch} · 재시도 명령: .venv/bin/python scripts/ocr_batch.py --retry {batch}', flush=True)
        try:
            counts = process_batch(db, batch)
        except KeyboardInterrupt:
            print(f'중단됨 · 같은 --retry {batch} 명령으로 이어서 처리할 수 있습니다.', flush=True)
            return 130
        return 1 if counts['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
