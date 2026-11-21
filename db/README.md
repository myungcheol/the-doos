# 페이지·OCR·인물 저장 구조 (T015·T016)

PostgreSQL 17 기준. 기존 `jokbo` 스키마와 독립된 `genealogy` 스키마를 사용한다. 이미지 파일은 파일시스템에 두고 DB에는 상대 경로·해시·크기를 저장한다. 실제 OCR 결과 적재는 T019, 수정 이력·현재 채택값 조회는 T018이다.

## 마이그레이션

저장소 루트에서 실행한다. 각 파일은 하나의 트랜잭션으로 적용한다. `schema_migrations`가 적용된 번호를 기록한다. 이미 적용한 파일을 재실행하면 오류가 발생하므로, 이후 변경은 새 번호 파일로 추가한다.

```bash
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/001_page_ocr_schema.up.sql
docker compose exec -T postgres sh -c 'psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/002_person_schema.up.sql
docker compose exec -T postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "TABLE genealogy.schema_migrations;"'
```

`down.sql`은 해당 테이블과 데이터를 제거한다. 롤백은 격리된 검증 DB에서 `002` → `001` 순서로만 실행한다. `CASCADE`를 사용하지 않으므로 후속 테이블이 참조하고 있으면 실수로 함께 삭제하지 않고 실패한다.

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

현재값 선택과 수정 이력은 T018에서 구현한다. 이번에는 자동·수동 값과 검수 상태를 저장할 수 있는 기반만 만든다. 부모/자녀는 T017, 혼인은 T039, 실제 OCR 적재는 T019이다.

## 사용자 검수

1. 위 `schema_migrations` 조회 명령에서 1·2가 보이는지 확인한다. 이미 적용되어 있으면 up 파일을 다시 실행하지 않는다.
2. 검증 명령을 실행해 `PASS: apply, storage/evidence constraints, rollback, reapply`가 나오는지 확인한다. 이 명령은 기존 DB 데이터를 사용하지 않는다.
3. 데이터 사전에서 `person_occurrences` 한 행에 여러 OCR 근거를 연결하는 방식, `subject_person_id`/`recorded_person_id`의 구분, 날짜 원문과 보충 flag가 합의와 맞는지 검토한다.

검증 fixture의 간지→서기 예시는 테스트용이며 역사적 환산 결과를 주장하지 않는다. 조회와 편집을 위한 Web UI는 이 티켓의 범위에 포함되지 않는다.
