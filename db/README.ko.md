# db

PostgreSQL 적재용 DDL과 사용법.

- `schema.sql`: 페이지·인물·관계·참조 테이블 DDL
- `scripts/import_db.py`: `data/exports/approved.jsonl` → SQL 생성 또는 `psql` 적재

## 빠른 실행

```bash
# 1) 스키마
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql

# 2) 승인분을 SQL로 만들기 (data/exports/import.sql)
python3 scripts/import_db.py

# 3) 적용
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f data/exports/import.sql
```

스키마와 적재를 한 파일로 만들려면:

```bash
python3 scripts/import_db.py --include-schema --sql /tmp/doos.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/doos.sql
```

`psql`이 PATH에 있으면 바로 적용할 수 있다.

```bash
python3 scripts/import_db.py --dsn "$DATABASE_URL" --include-schema
```

## 확인 쿼리

```sql
-- 페이지/인물 수
SELECT count(*) FROM pages;
SELECT count(*) FROM people;

-- 아버지 연결이 끝나지 않은 인물
SELECT count(*) FROM people
WHERE father_raw IS NOT NULL AND father_id IS NULL;

-- 대상 페이지를 찾지 못한 참조 (미수록 면이면 정상)
SELECT count(*) FROM page_refs WHERE target_page_id IS NULL;

-- 승인된 페이지만
SELECT count(*) FROM approved_pages;
```

## 규칙

- `generation_no`는 스캔에 인쇄된 `世` 값을 그대로 넣는다. `father_id` 체인으로 계산하지 않는다.
- `father_id`는 모든 페이지를 넣은 뒤 `person.father`의 `row`/`column` 또는 `page_ref`로 해석한다.
- 재실행하면 승인 페이지의 인물·관계·참조 행을 지우고 다시 넣는다. 같은 입력이면 결과가 같다.
- 승인 목록에서 빠진 페이지의 인물·관계·참조 행도 삭제된다. DB는 `approved.jsonl`의 스냅샷이다. 페이지 행은 `pending`으로 남는다.
- 대상 면이 미수록이면 `page_refs.target_page_id`가 `NULL`로 남는다. 오류가 아니다.
- `approved_pages`/`approved_people` 뷰는 승인 페이지만 거르는 내부용이다. **masking 뷰가 아니다.**
- `data/exports/import.sql`은 생성물이므로 git에 올리지 않는다.
