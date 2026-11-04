# db

PostgreSQL 적재용 DDL과 사용법.

- `schema.sql`: 페이지·인물·관계·참조 테이블 DDL과 공개 뷰
- `verify.sql`: 적재 후 확인 쿼리 (읽기 전용)
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

```bash
psql "$DATABASE_URL" -X -f db/verify.sql
```

`db/verify.sql`이 요약·미해결 아버지·미해결 참조·아버지 순환·세대 번호 누락·마지막 적재 기록을 한 번에 보여준다. 개별로 볼 때는:

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

## 공개 뷰

공개 앱은 `approved_*`가 아니라 `public_*` 뷰를 쓴다.

| 뷰 | 내용 |
|---|---|
| `public_pages` | 승인된 페이지 |
| `public_page_inventory` | 전체 면 목록 + `is_published`. 미수록 면을 `page_type = 'missing'`으로 표시 |
| `public_people` | 인물 + 아버지의 자연 키 |
| `public_person_names` | 이름·자·호 |
| `public_person_events` | 생몰 |
| `public_marriages` | 배우자 |
| `public_burials` | 묘소 |
| `public_page_refs` | `上###`/`下###` |
| `public_relations` | `children[]` 등 |
| `public_index_entries` | 색인 |
| `public_page_texts` | 서문·캡션 등 본문 |

```sql
SELECT * FROM public_people
WHERE printed_page_no = 25
ORDER BY row_no, column_no;
```

- 정책: **승인분은 그대로 공개**한다. 생존자·주소·묘소 좌표를 가리지 않는다(1986년 간행본과 같은 범위).
- 대신 검수 내부 값은 공개하지 않는다: `raw` JSON, `confidence`, `father_confidence`, `needs_human`, `ocr_status`, `quality_flags`, `manifest_notes`, `image_sha256`.
- bigserial `id`도 공개하지 않는다. 재적재마다 인물 행이 새로 들어가 id가 바뀌기 때문이다. 공개 식별자는 `(section_code, printed_page_no, row_no, column_no)`다.
- 정책을 바꿀 때는 `public_*` 뷰 정의만 고친다. 원본 테이블은 그대로 둔다.

## 규칙

- `generation_no`는 스캔에 인쇄된 `世` 값을 그대로 넣는다. `father_id` 체인으로 계산하지 않는다.
- `father_id`는 모든 페이지를 넣은 뒤 `person.father`의 `row`/`column` 또는 `page_ref`로 해석한다.
- 재실행하면 승인 페이지의 인물·관계·참조 행을 지우고 다시 넣는다. 같은 입력이면 결과가 같다.
- 승인 목록에서 빠진 페이지의 인물·관계·참조 행도 삭제된다. DB는 `approved.jsonl`의 스냅샷이다. 페이지 행은 `pending`으로 남는다.
- 대상 면이 미수록이면 `page_refs.target_page_id`가 `NULL`로 남는다. 오류가 아니다.
- `approved_pages`/`approved_people` 뷰는 승인 페이지만 거르는 내부용이다. 공개 앱은 `public_*` 뷰를 쓴다.
- `data/exports/import.sql`은 생성물이므로 git에 올리지 않는다.
