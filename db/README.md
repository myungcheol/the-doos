# 페이지·OCR·인물 저장 구조 (T015·T016)

PostgreSQL 17 기준. 기존 `jokbo` 스키마와 독립된 `genealogy` 스키마를 사용한다. 이미지 파일은 파일시스템에 두고 DB에는 상대 경로·해시·크기를 저장한다. 실제 OCR 결과 적재는 T019, 수정 이력·현재 채택값 조회는 T018이다.

## 마이그레이션

저장소 루트에서 실행한다. 각 파일은 하나의 트랜잭션으로 적용한다. `schema_migrations`가 적용된 번호를 기록한다. 이미 적용한 파일을 재실행하면 오류가 발생하므로, 이후 변경은 새 번호 파일로 추가한다.

```bash
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/001_page_ocr_schema.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/002_person_schema.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/003_parent_child.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/004_review_history.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/005_current_values.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/006_marriages.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/007_remove_wife_rank.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/008_page_imports.up.sql
docker compose exec -T postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "TABLE genealogy.schema_migrations;"'
```

`down.sql`은 해당 변경을 되돌린다. 롤백은 격리된 검증 DB에서 `008` → `007` → `006` → `005` → `004` → `003` → `002` → `001` 순서로 검증한다. 005 롤백은 현재 수동 값을 004의 테이블 구조로 보존한다. 007 롤백은 제거된 `wife_rank` 열을 빈 값으로 되살리므로 과거 값을 복원하지는 못한다.

검증 명령:

```bash
.venv/bin/python scripts/verify_db_schema.py
```

Compose PostgreSQL 안에 UUID 이름의 임시 DB를 생성해서 적용 → fixture 검증 → 롤백 → 재적용을 수행한다. 마지막에 그 임시 DB만 삭제한다. `.env`의 비밀값을 읽어 출력하지 않는다. 검증에 사용하는 DB 계정에는 임시 DB 생성 권한이 필요하다.

## T015 데이터 사전

| 테이블 | 주요 필드와 의미 |
|---|---|
| `pages` | `id`: 식별자. `section`: cover/frontmatter/genealogy. `page_key`: 파일 번호·표지 식별자. `sort_order`: 전체 책 읽기 순서. `scan_status`: available/missing. |
| `page_images` | `page_id`, `variant`: original/deskewed. `original_image_id`: 보정본의 원본. `storage_path`, `sha256`, `width`, `height`: 파일과 픽셀 크기. `rotation_degrees`, `forward_matrix`, `inverse_matrix`: 좌표 변환. |
| `ocr_runs` | `image_id`: 실행 입력. `status`, 시작/종료 시각. `engine_version`, `model_version`, `language`, `device`, `code_version`: 실행 식별 정보. `configuration`: 모델별 이름·전처리 설정. `environment`: PaddlePaddle/PaddleX/Python 버전 등. `raw_result`: 원시 JSON. `error_message`: 실패 원인. |
| `ocr_regions` | `run_id`, `parent_region_id`, `kind`: band/column/text. `reading_order`: 실행 내 읽기 순서. `left_px`, `top_px`, `right_px`, `bottom_px`: 상자. `polygon`: OCR 사각형 네 점. `raw_text`, `confidence`, `metadata`: 원문·신뢰도·재판독 근거 등. |
| `schema_migrations` | 적용된 `version`, 설명, 적용 시각. |

페이지는 이미지가 없어도 존재할 수 있다. missing 페이지에 이미지 등록은 거부한다. frontmatter와 표지도 책 열람용으로 저장할 수 있으나 OCR 입력 선정은 T019에서 genealogy로 제한한다.

원본은 페이지당 하나다. 보정본은 같은 페이지의 원본을 가리킨다. 동일 페이지·동일 이미지에서 실행을 여러 번 만들 수 있다. 영역의 부모는 같은 실행 안에서 단 → 열 또는 단/열 → 문자열로 연결한다. 현재 OCR처럼 문자열이 열 경계에 걸치면 단을 직접 부모로 둘 수 있다.

좌표는 왼쪽 위가 원점인 해당 이미지 픽셀이며, 상자는 `[left, top, right, bottom)`이다. polygon은 네 점의 `[x,y]` 배열이고 오른쪽·아래 경계점도 허용한다. 보정 이미지의 변환 행렬은 행 우선 6개 숫자 `[a,b,c,d,e,f]`로 저장한다.

```text
x' = a*x + b*y + c
y' = d*x + e*y + f
```

`forward_matrix`는 원본 → 보정본, `inverse_matrix`는 보정본 → 원본이다. 원본은 항등행렬이다. `ocr_regions`는 실행 이미지 좌표를 사용하고, 출현 위치는 원본 이미지 좌표로 고정한다. 이미지·영역의 수정/삭제 및 실행의 이미지 교체는 트리거가 거부한다. OCR 수정은 후속 티켓에서 별도 값으로 보존한다.

## T016 데이터 사전

| 테이블 | 주요 필드와 의미 |
|---|---|
| `persons` | `id`: 인물 식별자. `name_hanja`: 표지를 뺀 이름. `name_unknown`: 이름 미상 여부. `review_status`: pending/confirmed/rejected. 이름은 유일하지 않다. |
| `person_occurrences` | `person_id`: 연결 인물, 미연결은 NULL. `original_image_id`와 상자: 책 속 한 출현의 원본 위치. `marker_raw`: 子/女 등. `female_entry_status`: unresolved/daughter/son_in_law/not_applicable. `review_status`: 소속 검수 상태. |
| `occurrence_sources` | `occurrence_id` ↔ `region_id`. 같은 출현에 원본·보정본·재실행의 여러 OCR 영역을 연결한다. 이름의 판독 문자열은 각 OCR 영역에 남는다. |
| `person_readings` | `person_id`, `name_hanja_snapshot`, `reading`. `status`: candidate/confirmed/rejected. `origin`: automatic/manual. `source`, `source_version`, `details`: 사전 버전과 글자별 후보 근거. 인물당 확정 독음은 최대 하나다. |
| `person_facts` | `subject_person_id`: 내용 대상, 소속 미해결은 NULL. `recorded_person_id`: 설명이 실린 인물. `occurrence_id`: 설명이 나온 출현. `kind`, `raw_text`, `origin`, `review_status`, `parser_version`: 분류·원문·생성 근거. `explanation_automatic`, `explanation_manual`: 자동/수동 풀이. 아래 날짜 열도 이 테이블에 포함한다. |
| `fact_sources` | `fact_id`, `region_id`, `char_start`, `char_end`, `source_order`: 사실에 사용한 OCR 문자 범위와 조합 순서. 한 사실은 여러 영역, 한 영역은 여러 사실의 근거가 될 수 있다. |

한 인물은 여러 출현·독음 후보·사실을 가진다. OCR을 다시 돌려도 책 속 출현 자체를 새로 만들 필요가 없다. 어느 출현과 새 영역을 연결할지는 T019에서 판단하고 동명이인을 이름만으로 합치지 않는다. 女의 딸/사위 판정은 출현에 저장한다. 사위와 이름 미상 딸의 연결·혼인은 T039/T040에서 만든다.

배우자 B의 설명이 A 옆에 실렸으면 `recorded_person_id=A`, 내용이 B에게 해당하는 사실은 `subject_person_id=B`로 저장한다. A의 부가 정보 조회와 B의 생몰 조회가 같은 근거를 참조할 수 있다. 관직·학력은 각각 여러 사실 행으로, 자·호·효행은 일반 부가 정보로 저장한다.

원문 문자 범위는 0부터 시작하는 Unicode 코드 포인트의 `[start,end)`이다. Python 슬라이스 및 PostgreSQL `char_length` 기준이며 JavaScript UTF-16 문자열 인덱스와는 보충 한자에서 다를 수 있다. 입력 프로그램에서 인덱스를 변환해야 한다. 문자열 길이 초과와 출현 페이지가 다른 근거 연결은 DB가 거부한다. 수동 사실은 OCR 근거가 없어도 저장할 수 있다.

### 날짜 열

| 열 | 의미 |
|---|---|
| `year_text`, `month_text`, `day_text` | 원문에서 읽은 구성요소. 누락은 NULL. |
| `year_number`, `month`, `day` | 읽은 숫자. 네 자리 숫자 연도와 연호 기년을 혼동하지 않는다. |
| `calendar`, `leap_month` | unknown/lunar/solar 및 윤달 true/false/NULL. |
| `gregorian_year` | 근거를 갖고 환산한 서기 연도. 미환산은 NULL. |
| `normalized_month`, `normalized_day` | 원래 월일 또는 누락 시 1로 보충한 값. |
| `month_assumed`, `day_assumed` | 자동 보충 여부. true이면 원문 월/일은 NULL이고 정규화 값은 반드시 1이다. |
| `conversion_status` | not_attempted/resolved/ambiguous/unresolved/conflict. |
| `date_details` | 연호·왕대 식별자, 환산 출처/버전, 여러 연도 후보, OCR 경고 등을 저장하는 확장 정보. T038에서 확정 형식을 정한다. |

원문 정밀도는 원문 세 구성요소의 존재로 알 수 있다. 월일이 없는 해의 보충값과 실제 1월 1일은 flag로 구분한다. 음력 2월 30일을 저장할 수 있으며 PostgreSQL `DATE`로 강제 변환하지 않는다. 월 13처럼 판독 범위를 벗어난 값은 숫자 열에 넣지 않고 원문과 경고를 보존한다.

현재값 선택과 수정 이력은 아래 T018에 설명한다. 부모/자녀는 T017, 혼인은 T039, 실제 OCR 적재는 T019이다.

## 사용자 검수

1. 위 `schema_migrations` 조회 명령에서 1~8이 보이는지 확인한다. 이미 적용되어 있으면 up 파일을 다시 실행하지 않는다.
2. 검증 명령을 실행해 `PASS: apply, storage/evidence constraints, rollback, reapply`가 나오는지 확인한다. 이 명령은 기존 DB 데이터를 사용하지 않는다.
3. 데이터 사전에서 `person_occurrences` 한 행에 여러 OCR 근거를 연결하는 방식, `subject_person_id`/`recorded_person_id`의 구분, 날짜 원문과 보충 flag가 합의와 맞는지 검토한다.

검증 fixture의 간지→서기 예시는 테스트용이며 역사적 환산 결과를 주장하지 않는다. 조회와 편집을 위한 Web UI는 이 티켓의 범위에 포함되지 않는다.

## T017 부모·자녀

`parent_child`에는 부모와 자녀의 인물 ID 한 쌍을 한 번 저장한다. 양쪽의 출현 ID는 각각 해당 인물에 속해야 한다. `method`에는 판정 규칙을, `evidence`에는 위치·경고 등 판정 근거를 담는다. 부모가 확인되지 않은 인물은 연결 없이도 존재할 수 있다.

`parents_of(인물ID)`와 `children_of(인물ID)`는 한 단계의 상대 인물 ID, 관계 ID, 검수 상태를 반환한다. 트리에서 선택한 상대 ID로 같은 함수를 다시 호출하면 다음 단계가 열린다. 결과는 인물 ID 순이며 출생 순위는 뜻하지 않는다. 예시 호출은 다음과 같다.

```sql
SELECT * FROM genealogy.children_of(42);
SELECT * FROM genealogy.parents_of(42);
```

`relation_type`은 족보에 명시된 친생·입양·구분 미상이다. 탐색에는 `in_lineage=true`인 미검수 또는 확정 관계를 사용한다. 거절 관계는 보존하며 탐색에서 제외한다. 자기 참조와 거절되지 않은 관계 사이의 순환을 DB에서 거부한다. `lineage_write_guard` 한 행으로 관계 추가·수정 트랜잭션을 직렬화해 동시 입력에도 순환 검사가 순서대로 이루어지게 한다.

## T018 수정·삭제와 현재값

`persons`와 `person_facts`에 현재 사용하는 값을 저장한다. 검수 함수는 해당 행을 직접 UPDATE하고 `review_locked=true`로 설정한다. 수정 전후 값·작업자·이유·시각은 같은 트랜잭션에서 `review_history`에 기록한다. 모든 필드를 행 단위로 보호하며, 자동 처리 SQL에서 보호된 행의 갱신을 시도하면 DB가 거부한다.

`current_persons`와 `current_facts`는 기본 테이블에서 삭제·거절 항목을 제외하는 조회 뷰다. 사실을 기록한 인물 또는 대상 인물이 제외되어도 해당 사실을 숨긴다. 부모·자녀 함수는 양쪽 인물의 현재값과 관계 상태를 확인한다.

005는 기존 수동 테이블의 값을 기본 테이블로 옮겨 이력에 남긴 뒤 `person_manual_values`와 `fact_manual_values`를 제거한다. 최초 OCR 판독 근거는 `ocr_regions` 및 실행 결과에 저장된다. `person_facts.origin`은 해당 사실의 최초 생성 경로이고, 수동 검수 여부는 `review_locked` 및 이력으로 확인한다.

```sql
-- 실제 ID로 바꾸어 호출한다.
SELECT genealogy.review_values('person', 42,
    '{"name_hanja":"景吉","review_status":"confirmed"}', '관리자', '스캔 대조');
SELECT genealogy.review_values('fact', 15,
    '{"explanation_manual":"갑진년 출생. 월일 미상."}', '관리자', '원문 검수');
SELECT genealogy.review_relation(7, 'rejected', false, '관리자', '부모 오연결');
SELECT genealogy.exclude_record('person', 42, '관리자', '비침으로 생긴 오검출');
SELECT * FROM genealogy.current_persons;
SELECT * FROM genealogy.review_history ORDER BY id;
```

패치의 JSON null은 값을 비운다. 이름을 미상으로 바꿀 때는 이름과 `name_unknown`을 함께 수정한다. 보충 월일을 실제 날짜로 수정할 때도 원문 월일·숫자·정규화 값·보충 flag가 모두 CHECK 제약을 만족해야 한다. 잘못된 수정은 트랜잭션에서 취소된다.

`person_exclusions`, `fact_exclusions`에 삭제 이유와 시각을 남긴다. 기존 인물과 관계·근거의 외래 키를 보존하며 물리 DELETE는 거부한다. 관계 검수는 `review_relation`으로 수행하며 검수한 관계를 자동 UPDATE로 덮어쓰면 오류가 발생한다.

`review_history`는 인물·출현·독음·사실·계보 및 삭제표시의 변경 전후 전체 값, 작업자, 이유, 시각을 기록한다. 이력 UPDATE/DELETE는 거부한다. SQL 작업자는 검수 함수의 인자로 제공하며 관리자 인증은 후속 웹 티켓에서 연결한다. 자동 처리 이력의 작업자는 `automatic`이다. 004 당시 수동 테이블의 기존 이력도 유지한다.

재처리 시 `ingest_person(출현ID, 판독이름)`을 사용하면 기존 인물 ID를 반환한다. 검수·제외 인물의 값과 제외 상태를 유지한다. 새 OCR 실행을 기존 출현에 매칭하는 T019 적재기는 반드시 같은 출현 ID를 재사용해야 한다. 새 출현을 잘못 생성하는 의미상 중복은 이 함수만으로 판별할 수 없으며 T019의 입력 매칭 검증 대상이다. 사실 적재도 기존 ID를 재사용하고 `WHERE NOT review_locked`로 자동 갱신 대상을 제한한다. 기존 삭제표시를 보존한다.

혼인 테이블의 이력 연결은 아래 T039에 설명한다. 현재 자동 검증에는 수동 수정 후 재처리, 제외 후 동일 출현 재적재, 삭제/거절 인물의 양방향 탐색 제외, 검수 관계 덮어쓰기 거부, 이력 변경 거부를 포함한다.

## T039 배우자·혼인

| 테이블 | 필드와 의미 |
|---|---|
| `marriages` | `person_id`는 설명 주인 A, `spouse_id`는 독립 배우자 B다. `relation_type`은 spouse/concubine이며 명시된 첩인 경우에만 concubine이다. `review_status`, `review_locked`는 검수 상태와 자동 갱신 보호다. |
| `marriage_sources` | `marriage_id`와 A의 배우자 설명인 `person_facts.id`를 연결한다. 설명 사실의 kind는 spouse_information이며 recorded_person_id와 subject_person_id는 해당 혼인의 두 인물이어야 한다. 한 혼인은 여러 설명을 근거로 가질 수 있다. |

配 등 모든 부인은 spouse, 명시된 妾만 concubine으로 저장한다. 사별·이혼 등에 따른 복수 부인도 각각 spouse로 저장할 수 있다. 배우자의 개인 이름이 없으면 persons의 이름 미상 flag를 사용하고 金氏 같은 표기는 설명 원문에 보존한다. 이름이나 성씨가 같아도 인물 ID가 다르면 별도 혼인을 저장할 수 있다.

배우자 설명과 생몰은 각각 사실 행으로 저장한다. A의 설명에 B의 사망이 기록돼 있으면 설명과 사망 사실의 recorded_person_id는 A이고 subject_person_id는 B다. 설명에서 `marriage_sources`를 따라 혼인과 B로 이동하고, B의 사실에서 생몰을 조회할 수 있다. 원래 OCR 영역은 기존 `fact_sources`로 연결한다.

`ingest_marriage(A,B,관계유형,설명사실ID)`는 혼인 ID를 반환한다. 인물 쌍에 유일성 제약이 있어 A–B와 B–A를 재적재해도 같은 ID를 반환한다. 반대 방향의 설명은 근거를 추가하고 기존 배우자 역할을 유지한다. 검수·거절한 혼인도 같은 ID를 재사용한다. 새 설명 사실을 매번 중복 생성하지 않도록 사실 ID를 매칭하는 작업은 T019 적재기에서 담당한다.

`review_marriage`는 관계유형·검수 상태를 현재 행에 갱신하고 이력을 남긴다. 검수한 행의 자동 갱신과 물리 삭제는 거부한다. 상대방을 잘못 연결했을 때는 해당 관계를 거절하고 올바른 상대방의 새 관계를 만든다. 연결된 설명의 소속을 바꿔 혼인 근거가 모순되는 수정도 거부한다.

`current_marriages`는 관계가 거절되었거나 양쪽 인물 중 하나가 삭제·거절되었으면 제외한다. 배우자 이름을 수정해도 인물 ID와 설명 근거 연결은 유지된다. 근거 설명 사실의 제외와 혼인 관계의 거절은 각각 검수할 수 있다.

```sql
-- 실제 ID로 바꾸어 호출한다.
SELECT genealogy.ingest_marriage(42, 43, 'spouse', 15);
SELECT genealogy.review_marriage(7, 'spouse', 'confirmed', '관리자', '배우자 확인');
SELECT genealogy.review_marriage(7, 'spouse', 'rejected', '관리자', '배우자 오연결');
SELECT * FROM genealogy.current_marriages WHERE person_id=42 OR spouse_id=42;
SELECT m.*, f.raw_text, f.recorded_person_id, f.subject_person_id
FROM genealogy.marriage_sources s
JOIN genealogy.marriages m ON m.id=s.marriage_id
JOIN genealogy.person_facts f ON f.id=s.fact_id
WHERE f.id=15;
```

자동 검증은 A–B/A–C, 첩·이름 미상·지위 미상, 정방향/역방향 중복 적재, 이름 수정 후 원문·생몰 소속, 검수 지위 보존, 배우자 삭제/혼인 거절 후 재적재, 모순된 근거·자기 혼인 거부, 변경 이력과 롤백·재적용을 포함한다.
