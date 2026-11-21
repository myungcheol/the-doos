"""Verify migrations in a uniquely named disposable database on local Compose."""
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker_script(script, *arguments, sql=None):
    return subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'postgres', 'sh', '-c', script, 'schema-test', *arguments],
        cwd=ROOT, input=sql, text=True, check=True, capture_output=True,
    ).stdout


def main():
    database = 'the_doos_schema_test_' + uuid.uuid4().hex
    docker_script('createdb -U "$POSTGRES_USER" -- "$1"', database)
    try:
        def sql(text):
            return docker_script('psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$1"', database, sql=text)

        def migration(name):
            sql((ROOT / 'db/migrations' / name).read_text(encoding='utf-8'))

        up = ['001_page_ocr_schema.up.sql', '002_person_schema.up.sql']
        down = ['002_person_schema.down.sql', '001_page_ocr_schema.down.sql']
        for name in up:
            migration(name)
        sql((ROOT / 'tests/fixtures/page-person-schema.sql').read_text(encoding='utf-8'))
        for name in down:
            migration(name)
        sql("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='genealogy') THEN RAISE EXCEPTION 'rollback incomplete'; END IF; END $$;")
        for name in up:
            migration(name)
        print('PASS: apply, storage/evidence constraints, rollback, reapply')
    finally:
        docker_script('dropdb -U "$POSTGRES_USER" -- "$1"', database)
        print('Removed disposable database:', database)


if __name__ == '__main__':
    main()
