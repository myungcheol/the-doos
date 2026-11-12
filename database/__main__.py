"""python -m database: initialize, migrate, export, and query genealogy."""
import argparse
import json
import sys

from .store import DatabaseError, PostgresStore


def main():
    parser = argparse.ArgumentParser(description='족보 PostgreSQL 저장·이관·계보 조회 (접속 정보는 환경변수)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='jokbo 스키마 생성 (기존 데이터 유지)')
    commands.add_parser('verify-assets', help='관리 이미지 파일의 존재·크기·SHA-256 검사')
    finder = commands.add_parser('find', help='이름으로 인물 UID·판본·검수 상태 조회 (정확히 일치)')
    finder.add_argument('name')
    importer = commands.add_parser('import', help='기존 JSON·검수 기록·이미지를 한 트랜잭션으로 가져오기')
    importer.add_argument('output')
    importer.add_argument('--edition')
    exporter = commands.add_parser('export', help='새 폴더에 JSON·검수 기록·이미지 내보내기')
    exporter.add_argument('output')
    exporter.add_argument('--edition', default='jokbo-1987')
    runs = commands.add_parser('runs', help='OCR 이력과 활성 여부 확인')
    runs.add_argument('--edition', default='jokbo-1987')
    for name in ('ancestors', 'descendants', 'common-ancestors'):
        command = commands.add_parser(name)
        command.add_argument('person_id')
        if name == 'common-ancestors':
            command.add_argument('other_id')
        command.add_argument('--kind', choices=['biological', 'adoptive', 'unspecified'])
        command.add_argument('--max-depth', type=int, default=100)
    args = parser.parse_args()
    try:
        store = PostgresStore()
        if args.command == 'init':
            store.initialize()
            result = {'schema_version': 1}
        elif args.command == 'import':
            result = store.import_directory(args.output, args.edition)
        elif args.command == 'export':
            store.export(args.edition, args.output)
            result = {'output': args.output}
        elif args.command == 'find':
            result = store.find_people(args.name)
        elif args.command == 'verify-assets':
            result = store.verify_assets()
        elif args.command == 'runs':
            with store.connection() as conn:
                result = conn.execute('''SELECT p.name,r.id,r.active,r.digest FROM jokbo.ocr_runs r
                    JOIN jokbo.pages p ON p.id=r.page_id WHERE p.edition_id=%s ORDER BY p.name,r.id''', (args.edition,)).fetchall()
        elif args.command == 'common-ancestors':
            result = store.common_ancestors(args.person_id, args.other_id, args.kind, args.max_depth)
        else:
            result = store.relatives(args.person_id, args.command, args.kind, args.max_depth)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == 'verify-assets' and result['missing_or_corrupt'] else 0
    except (DatabaseError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
