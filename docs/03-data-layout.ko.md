# 데이터 구성: 폴더와 DB 페이지 모델

> 이 문서는 전편(서문/사진/부록)과 본편(세보)의 페이지 번호가 중복되는 문제를 해결하기 위한 결정안이다.  
> 핵심 원칙: **페이지 번호 하나로 unique를 걸지 않는다. `(구분, 인쇄 면번호)` 복합 키를 쓴다.**

---

## 1. 결정 요약

1. 스캔을 **전편(frontmatter)** 과 **본편(genealogy)** 으로 분리한다.
2. 페이지 키는 `(section, printed_page_no)` 복합 키다. `page_no` 단일 unique는 금지한다.
3. 원본은 `scan/`에 그대로 두고, 앱이 읽는 정규화 경로를 `data/pages/`에 만든다. 원본 파일명·해시는 manifest에 보존한다.
4. `上###`는 인물 텍스트가 아니라 **페이지 참조**이므로 `page_refs` 테이블로 분리한다.
5. 전편은 `page_texts`/`toc_entries`/`captions` 중심, 본편은 `people`/`relations` 중심으로 저장한다.
6. 전편 63면 항렬표(`scan/frontmatter/063.jpg`)는 `generation_chars` 테이블로 저장한다.
7. 원본 `scan/`은 3자리 zero-pad(`frontmatter/047.jpg`), 앱 정규화 경로 `data/pages/`는 4자리(`frontmatter/0047.jpg`)를 쓴다.
8. 폴더 이름은 `frontmatter`(전편) / `genealogy`(본편)로 확정한다. 표지는 `scan/` 루트에 둔다.

---

## 2. 폴더 구조

### 2.1 원본 (내용 수정 금지)

현재 `scan/`은 원본으로 보존한다. 2026-10-28 기준 `.jpeg` 파일은 `.jpg`로, 숫자 파일명은 3자리 zero-pad로 정리했고, 전편/본편을 폴더로 분리했다.

```text
scan/
  frontmatter/            # 전편 (구분 A)
    001.jpg ~ 047.jpg     # 서문·추고·구보 서문 번역·목차
    049.jpg ~ 063.jpg     # 049~062 묘소·제각·정려 사진, 063 항렬표
    065.jpg ~ 066.jpg     # 조견색인
  genealogy/              # 본편 (구분 B)
    001.jpg ~ 938.jpg     # 세보 001~935, 임원록 936, 수단 937, 간기 938
  앞표지.jpg
  뒷표지.jpg
```

- `frontmatter/`에는 현재 001~047, 049~063, 065~066이 있다. 즉 048, 064, 067~093은 없다.
- `genealogy/`에는 현재 001~052, 054~933, 936~938이 있다. 즉 053, 934, 935는 없다.
- **없는 면은 그대로 둔다.** 공백이 원래 의도된 것이거나 업로드 누락일 수 있으므로, 재스캔·추적 없이 manifest와 앱에서 “미수록”으로 표시만 한다.
- `genealogy/052.jpg`는 원래 `053.jpg`였던 파일이 52면으로 정정된 것이다. 그래서 지금 053이 비어 있다.

### 2.2 앱용 정규화 경로

원본을 복사하거나 symlink로 연결해 앱이 안정적으로 참조할 경로를 만든다.

```text
data/
  pages/
    frontmatter/
      0001.jpg
      0004.jpg
      ...
      0047.jpg
      0049.jpg
      ...
      0066.jpg
    genealogy/
      0001.jpg
      0002.jpg
      ...
      0938.jpg
    covers/
      front.jpg
      back.jpg
  manifests/
    pages.csv
```

- `frontmatter`는 전편 1~93면을 대상으로 한다. 현재 스캔은 1~47, 49~63, 65~66면이 있고, 48·64·67~93면은 `missing`으로 기록한다.
- `genealogy`는 본편 1~938면을 대상으로 한다. 현재 053, 934, 935가 없다.
- `data/pages`는 원본의 symlink여도 되고, 복사본이어도 된다. 원본은 절대 수정하지 않는다.
- 원본이 3자리(`scan/genealogy/025.jpg`)이고 정규화 경로가 4자리(`data/pages/genealogy/0025.jpg`)이므로, manifest가 둘을 연결한다.

### 2.3 `pages.csv` manifest

```csv
section,printed_page_no,scan_seq,source_path,normalized_path,sha256,width,height,dpi,page_type,quality_flags,notes
genealogy,1,1,scan/genealogy/001.jpg,data/pages/genealogy/0001.jpg,...,688,948,96,genealogy,,1~6세 표
genealogy,2,2,scan/genealogy/002.jpg,data/pages/genealogy/0002.jpg,...,700,948,96,genealogy,,
...
frontmatter,46,46,scan/frontmatter/046.jpg,data/pages/frontmatter/0046.jpg,...,705,956,96,preface,,
frontmatter,47,47,scan/frontmatter/047.jpg,data/pages/frontmatter/0047.jpg,...,720,955,99,index,,목차
frontmatter,52,52,scan/frontmatter/052.jpg,data/pages/frontmatter/0052.jpg,...,703,948,96,photo,,묘소 사진
frontmatter,63,63,scan/frontmatter/063.jpg,data/pages/frontmatter/0063.jpg,...,704,940,96,generation_name_table,,항렬표
frontmatter,48,48,,,,MISSING,,,,,,전편 48면 없음
genealogy,53,53,,,,MISSING,,,,,,본편 53면 없음
```

- `scan_seq`: 폴더 안에서의 스캔 순서.
- `printed_page_no`: 책에 인쇄된 면번호. OCR/육안으로 확인해 채운다.
- `page_type`: `preface`, `photo`, `generation_table`, `genealogy`, `index`, `generation_name_table`, `property`, `officers`, `subscription`, `colophon`, `cover`, `unknown`.
- `quality_flags`: `blur`, `bleed_through`, `rotated`, `cut_off` 등.

---

## 3. 현재 파일 매핑 예시

| 원본 | section | printed_page_no | 비고 |
|---|---|---|---|
| `scan/frontmatter/001.jpg` | frontmatter | 1 | 世譜序 |
| `scan/frontmatter/002.jpg` | frontmatter | 2 | 서문 |
| `scan/frontmatter/003.jpg` | frontmatter | 3 | 서문 |
| `scan/frontmatter/004.jpg` | frontmatter | 4 | 杜陵序 追考 |
| `scan/frontmatter/046.jpg` | frontmatter | 46 | 서문 |
| `scan/frontmatter/047.jpg` | frontmatter | 47 | 목차 |
| `scan/frontmatter/049.jpg`~`scan/frontmatter/062.jpg` | frontmatter | 49~62 | 묘소·제각·정려 사진 |
| `scan/frontmatter/063.jpg` | frontmatter | 63 | **항렬표(行列名字例)** |
| `scan/frontmatter/065.jpg` | frontmatter | 65 | 조견색인(早見索引) |
| `scan/frontmatter/066.jpg` | frontmatter | 66 | 조견색인(早見索引) |
| `scan/frontmatter/048.jpg`, `064.jpg` | frontmatter | 48, 64 | **없음** |
| `scan/genealogy/025.jpg` | genealogy | 25 | 본편 25면 |
| `scan/genealogy/217.jpg` | genealogy | 217 | 본편 217면 |
| `scan/genealogy/936.jpg` | genealogy | 936 | 임원록 |
| `scan/genealogy/937.jpg` | genealogy | 937 | 수단 |
| `scan/genealogy/938.jpg` | genealogy | 938 | 간기 |
| `scan/genealogy/934.jpg` | genealogy | 934 | **없음** |
| `scan/genealogy/935.jpg` | genealogy | 935 | **없음** |


---

## 4. DB 페이지 모델

### 4.1 `sections`

```sql
CREATE TABLE sections (
  id           bigserial PRIMARY KEY,
  code         text UNIQUE NOT NULL,   -- 'frontmatter', 'genealogy', 'covers'
  title        text NOT NULL,
  page_start   integer,
  page_end     integer,
  numbering    text NOT NULL,          -- 'independent', 'continuous'
  note         text
);
```

예:

| code | title | page_start | page_end | numbering |
|---|---|---:|---:|---|
| frontmatter | 전편(서문·사진·부록) | 1 | 93 | independent |
| genealogy | 본편(세보) | 1 | 938 | independent |
| covers | 표지 | null | null | none |

### 4.2 `pages`

```sql
CREATE TABLE pages (
  id               bigserial PRIMARY KEY,
  section_id       bigint NOT NULL REFERENCES sections(id),
  printed_page_no  integer NOT NULL,
  scan_seq         integer,
  page_type        text NOT NULL,
  image_path       text NOT NULL,
  image_sha256     text NOT NULL,
  width            integer,
  height           integer,
  dpi              integer,
  quality_flags    text[] DEFAULT '{}',
  ocr_status       text NOT NULL DEFAULT 'pending',
  review_status    text NOT NULL DEFAULT 'pending',
  UNIQUE (section_id, printed_page_no)
);
```

- `printed_page_no`는 **섹션 안에서만** unique하다.
- `page_type`은 3.2의 enum을 사용한다.
- `image_path`는 `data/pages/...` 정규화 경로.
- `image_sha256`으로 중복/변경을 감지한다.
- `ocr_status`: `pending`, `queued`, `processing`, `done`, `failed`, `skipped`.
- `review_status`: `pending`, `in_review`, `approved`, `rejected`, `published`.

### 4.3 `page_texts`

전편/서문/사진 캡션/색인 등 인물 구조화 대상이 아닌 페이지의 OCR 원문.

```sql
CREATE TABLE page_texts (
  id          bigserial PRIMARY KEY,
  page_id     bigint NOT NULL REFERENCES pages(id),
  raw_text    text,
  normalized  text,
  language    text,          -- 'hanja', 'ko', 'mixed'
  ocr_run_id  bigint,
  bbox        jsonb,
  confidence  numeric,
  created_at  timestamptz DEFAULT now()
);
```

### 4.4 `page_refs` — `上###`

```sql
CREATE TABLE page_refs (
  id                 bigserial PRIMARY KEY,
  source_page_id     bigint NOT NULL REFERENCES pages(id),
  source_person_id   bigint,          -- nullable; 인물에 붙은 참조
  raw_ref            text NOT NULL,   -- '上159'
  target_section_id  bigint NOT NULL REFERENCES sections(id),
  target_page_no     integer NOT NULL,
  target_page_id     bigint REFERENCES pages(id), -- import 후 resolve
  confidence         numeric,
  note               text
);
```

- `上159`는 기본적으로 `target_section = genealogy`, `target_page_no = 159`.
- 전편을 가리키는 참조가 있으면 `target_section = frontmatter`.
- `target_page_id`는 페이지 import 후 채운다.
- `raw_ref`는 원문 그대로 보존한다.

### 4.5 `toc_entries`

목차는 전편/본편 번호가 섞여 있으므로 `target_section`을 명시한다.

```sql
CREATE TABLE toc_entries (
  id                 bigserial PRIMARY KEY,
  section_id         bigint NOT NULL REFERENCES sections(id), -- 목차가 실린 섹션
  item_no            integer,
  title              text NOT NULL,
  target_section_id  bigint NOT NULL REFERENCES sections(id),
  target_page_no     integer,
  note               text
);
```

예:

| item_no | title | target_section | target_page_no |
|---:|---|---|---:|
| 1 | 杜陵杜氏世譜序 | frontmatter | 1 |
| 2 | 杜陵序 追考 | frontmatter | 4 |
| 3 | 杜陵序(舊譜序 翻譯) | frontmatter | 7 |
| 4 | 墓所 및 祭閣·旌閭閣·積善碑 및 善德碑 | frontmatter | 49 |
| 5 | 行列名字例 | frontmatter | 63 |
| 6 | 早見索引 | frontmatter | 65 |
| 7 | 昭穆錄 | frontmatter | 65 |
| 8 | 宗中財產目錄 | frontmatter | 93 |
| 9 | 刊行委員 및 任員錄 | genealogy | 936 |
| 10 | 收單有司名錄 | genealogy | 937 |

### 4.6 `generation_chars` — 항렬표

전편 63면 `行列名字例`(`scan/frontmatter/063.jpg`)를 구조화한다. 세대별로 3개의 항렬자 후보와 이름에서의 위치를 표로 정리한 것으로 보인다. 정확한 적용 규칙은 문중 확인이 필요하다.

```sql
CREATE TABLE generation_chars (
  id             bigserial PRIMARY KEY,
  generation_no  integer NOT NULL,
  branch_code    text,             -- 'geumpo' 등
  char_hanja     text NOT NULL,
  char_hangul    text,
  position       text,             -- 'first', 'middle', 'last', 'any'
  source_page_id bigint REFERENCES pages(id),
  note           text
);
```

### 4.7 인물/관계 테이블

`people`, `person_names`, `person_events`, `burials`, `relations`, `marriages`는 별도 스키마 문서에서 다룬다. 페이지와의 연결은 다음 필드로 한다.

- `people.source_page_id` → `pages.id`
- `people.row_no`, `people.bbox`
- `relations.source_page_id`, `relations.bbox`
- `marriages.source_page_id`, `marriages.bbox`

---

## 5. 전편/본편 저장 정책

| 데이터 | 전편 | 본편 |
|---|---|---|
| 페이지 메타데이터 | `pages` | `pages` |
| OCR 원문 | `page_texts` | `page_texts` + `ocr_regions` |
| 인물 | 원칙적으로 생성하지 않음 | `people` |
| 예외 인물 | `generation_table`(본편 1면), 색인/임원록 | — |
| 관계 | 생성하지 않음 | `relations`/`marriages` |
| 사진 캡션 | `captions`(page_texts 확장) | — |
| 목차 | `toc_entries` | — |
| 항렬표 | `generation_chars` | — |

전편의 사진/서문은 인물 DB에 넣지 않는다. 다만 **본편 1면**은 `page_type = generation_table`로 두고 인물을 생성한다.

---

## 6. 마이그레이션 순서

1. **인벤토리**: 현재 `scan/` 전체 파일의 hash/크기/해상도를 계산하고, 누락(전편 48·64·67~93, 본편 053·934·935)을 `MISSING`으로 표시한다.
2. **매핑**: `pages.csv` 초안을 만들고, 인쇄 면번호를 OCR/육안으로 확인한다. 최소 20장을 샘플 검증한다.
3. **정규화 경로**: `data/pages/frontmatter`, `data/pages/genealogy`에 symlink 또는 복사본을 만든다.
4. **DB 입력**: `sections`, `pages`, `toc_entries`를 먼저 넣는다.
5. **페이지 분류**: `page_type`을 채운다. 전편은 `page_texts`, 본편은 `genealogy`/`generation_table`.
6. **OCR/파싱**: 본편부터 `people`/`page_refs`를 만든다. 전편은 서문/사진/색인/항렬표를 별도 처리한다.
7. **검증**: 모든 `page_refs.target_page_id`가 존재하는지, `(section, printed_page_no)` 중복이 없는지 확인한다.
8. **검수/발행**: `review_status`가 `approved`인 데이터만 공개한다.

---

## 7. 현재 확인된 누락/불일치

| 항목 | 상태 | 처리 |
|---|---|---|
| 본편 053면 | 없음 | `missing`으로 표시. 재스캔하지 않으므로 “미수록” 안내 |
| 본편 934면 | 없음 | `missing`으로 표시 |
| 본편 935면 | 없음 | `missing`으로 표시 |
| 전편 48면 | 없음 | `missing`으로 표시 |
| 전편 64면 | 없음 | `missing`으로 표시 |

---

## 8. 다음 단계

1. 누락 면(전편 48·64, 본편 053·934·935)은 그대로 두고 `MISSING`으로 기록한다. (재스캔·추적 없음)
2. `pages.csv` 초안을 실제 파일에서 생성한다.
3. `sections`/`pages` DDL과 import 스크립트를 만든다.
4. `scan/frontmatter/063.jpg` 항렬표를 `generation_chars`로 구조화한다.
5. 20~30장 파일럿으로 페이지 분류/OCR/`上###` 파싱을 검증한다.
