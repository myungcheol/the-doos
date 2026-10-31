# 杜陵杜氏世譜 (1986, 金浦派) 디지털화

1986년 간행 『杜陵杜氏世譜』(金浦派) 스캔을 **페이지 인벤토리 → AI 파싱 → 사람 검수 → 공개 데이터**로 바꾸는 프로젝트입니다.

이 문서는 프로젝트의 entry point다. 전체 흐름과 폴더 구조를 먼저 보고, 실제 실행은 [빠른 시작](#4-빠른-시작)과 [04. 작업 흐름](docs/04-workflow.ko.md)을 따른다. 현재 어디까지 했는지는 [STATUS.md](STATUS.md)에만 기록한다.

---

## 1. 무엇을 하는 프로젝트인가

족보 한 권을 스캔 이미지에서 **사람과 관계 데이터**로 옮기는 작업이다.

- 책은 두 부분으로 나뉜다.
  - **전편(frontmatter)**: 서문, 묘소 사진, 항렬표, 색인 등. 인쇄 면번호 1~93.
  - **본편(genealogy)**: 실제 세보(世譜). 인쇄 면번호 1~938.
- 본편의 가로 줄을 **단(段)** 이라고 한다. 원칙적으로 **같은 단 = 같은 세대**, 한 단 안에서는 **오른쪽 → 왼쪽**으로 읽는다.
- `上###`은 “조상 기록이 그 면에 있다”, `下###`은 “자손 기록이 그 면에 이어진다”는 페이지 참조다.
- 최종 산출물은 페이지·인물·관계·페이지 참조를 담은 DB와, 이를 검색·열람하는 공개 웹앱이다.

### 지키는 원칙

| 원칙 | 의미 |
|---|---|
| **재스캔 없음** | `scan/`의 현재 파일을 그대로 쓴다. 원본은 수정하지 않는다. |
| **없는 면은 없는 채로** | 전편 48·64·67~93면, 본편 53·934·935면은 `missing`(“미수록”)으로 기록만 한다. |
| **AI는 보조자** | AI가 읽고 구조화하지만, 최종 판단과 승인은 사람이 한다. 불확실하면 비우고 `needs_human=true`. |
| **문서가 정본** | 판독 규칙은 `docs/02`, 데이터 구조는 `docs/03`이 단일 기준이다. |

---

## 2. 전체 파이프라인

```text
[종이 족보]
    │  (재스캔 없음)
    ▼
scan/*.jpg
    │
    ├─ ① 인벤토리 ──────────────▶ data/manifests/pages.csv
    │                                │
    │                          ② 정규화 경로
    │                                ▼
    │                          data/pages/*.jpg  (symlink)
    │                                │
    │    docs/02 + schema ── ③ 프롬프트 ──┐
    │                                │    │
    │                    ④ OCR(선택) ─┘    │
    │                                ▼    ▼
    └──────────────────────────▶ ⑤ AI 파싱
                                     │
                                     ▼
                          data/parsed/*.json + *.meta.json
                                     │
                                ⑥ 자동 검증
                                     │
                                     ▼
                          admin/server.py + ⑦ 사람 검수
                                     │
                                     ▼
                          data/review/status.json
                                     │ approved만
                                     ▼
                          ⑧ JSONL 내보내기 → DB → 공개 앱
```

### 단계별 입력과 출력

| # | 단계 | 입력 | 처리 | 출력 | 도구 |
|---:|---|---|---|---|---|
| ① | 인벤토리 | `scan/**/*.jpg` | 파일명·해시·해상도·인쇄 면번호·페이지 유형을 기록. 없는 면은 `missing` 행 추가 | `data/manifests/pages.csv` (1,031행) | `scripts/build_manifest.py` |
| ② | 정규화 경로 | `pages.csv`, `scan/` | 3자리 원본을 4자리 앱 경로로 연결. 원본은 그대로 | `data/pages/<section>/<4digit>.jpg` symlink | `scripts/link_pages.py` |
| ③ | 프롬프트 | `pages.csv`, `docs/02` §2, `schema/page.schema.json` | 판독 규칙 + JSON Schema + 페이지 메타데이터를 합침 | `data/prompts/<section>/<4digit>.txt` | `scripts/prompt.py` |
| ④ | OCR (선택) | 페이지 이미지 | Tesseract로 보조 텍스트 추출. Vision 모델의 대체가 아니라 힌트 | `data/ocr/<section>/<4digit>.txt` | `scripts/ocr.py` |
| ⑤ | AI 파싱 | 이미지 + 프롬프트 (+ OCR) | Vision 모델이 단·인물·관계·`上`/`下` 참조를 JSON으로 구조화 | `data/parsed/<section>/<4digit>.json`, `.meta.json` | `scripts/parse_page.py` |
| ⑥ | 자동 검증 | 파싱 JSON | 필수 필드, `(row, column)` 중복, `page_ref`, 날짜·묘소 구조 검사 | 오류/경고 목록, `needs_human` 표시 | `scripts/validate_page.py` |
| ⑦ | 사람 검수 | 이미지 + JSON | 이미지와 파싱 결과를 나란히 보고 수정·승인 | `data/review/status.json` | `admin/server.py` |
| ⑧ | 내보내기 | `approved` 페이지 | 승인된 페이지만 JSONL로 묶어 DB 적재·공개 | `data/exports/approved.jsonl` → PostgreSQL → 웹앱 | `scripts/export_approved.py` |

> ⑤~⑧은 아직 실제 데이터로 완주하지 않았다. 현재 상태는 [STATUS.md](STATUS.md)를 본다.

---

## 3. 폴더 구조

```text
the-doos/
├─ README.md                  # 이 문서: 프로젝트 entry point
├─ STATUS.md                  # 진행 상황·다음 단계·블로커 (여기서만 관리)
│
├─ scan/                      # 원본 스캔. 수정 금지
│  ├─ frontmatter/            # 전편 001~066 (048·064·067~093 없음)
│  ├─ genealogy/              # 본편 001~938 (053·934·935 없음)
│  ├─ 앞표지.jpg
│  └─ 뒷표지.jpg
│
├─ data/
│  ├─ manifests/              # pages.csv, covers.csv (git 추적)
│  ├─ pages/                  # 4자리 정규화 경로 (생성물, git 제외)
│  ├─ ocr/                    # OCR 보조 텍스트 (생성물, git 제외)
│  ├─ prompts/                # dry-run 프롬프트 (생성물, git 제외)
│  ├─ parsed/                 # 페이지별 JSON + meta (생성물, git 제외)
│  ├─ review/                 # 검수 상태·메모 (status.json은 로컬, README만 추적)
│  └─ exports/                # 승인 데이터 (approved.jsonl만 추적)
│
├─ schema/
│  └─ page.schema.json        # AI 출력 JSON Schema
│
├─ scripts/
│  ├─ build_manifest.py       # scan/ → pages.csv
│  ├─ link_pages.py           # scan/ → data/pages symlink
│  ├─ prompt.py               # 02 §2 + schema → 프롬프트
│  ├─ ocr.py                  # 선택: Tesseract OCR
│  ├─ parse_page.py           # 한 페이지 AI 호출·검증·저장
│  ├─ run_pipeline.py         # 범위/유형/개수 지정 배치
│  ├─ validate_page.py        # 파싱 JSON 검증
│  ├─ export_approved.py      # 승인분 → data/exports/approved.jsonl
│  ├─ sync_status.py          # STATUS.md → README 진행 상황 삽입
│  └─ common.py               # manifest·경로 공통 함수
│
├─ admin/
│  ├─ server.py               # 의존성 없는 로컬 검수 서버
│  └─ static/                 # 이미지 + JSON 검수 UI
│
└─ docs/
   ├─ 01-reading-guide.ko.md  # 사람이 읽는 법
   ├─ 02-ai-parsing-guide.ko.md # AI 프롬프트·필드 정본
   ├─ 03-data-layout.ko.md    # 폴더·manifest·DB 설계
   └─ 04-workflow.ko.md       # 실제 실행 순서
```

### 원본과 생성물

| 구분 | 경로 | git | 추적/제외 이유 |
|---|---|---|---|
| 원본 | `scan/` | 추적 | 절대 수정하지 않는 스캔. provenance의 기준 |
| 고정 manifest | `data/manifests/` | 추적 | 재생성 가능하지만, 배포·검수의 기준이므로 결과를 고정 |
| 정규화 경로 | `data/pages/` | **제외** | 머신별 symlink라 clone/OS에 따라 깨짐. `pages.csv` + `link_pages.py`로 언제든 재생성 |
| OCR 보조 | `data/ocr/` | **제외** | Tesseract 버전에 따라 달라지는 파생물. 선택 사항이며 정본이 아님 |
| 프롬프트 | `data/prompts/` | **제외** | `docs/02` + schema + manifest에서 결정론적으로 생성. 문서 수정 때마다 churn만 늘어남 |
| AI 원본 | `data/parsed/` | **제외** | 모델·시행마다 달라지는 중간 산출물. 999면 전체를 커밋하면 검수 전 노이즈가 큼 |
| 검수 상태 | `data/review/status.json` | **제외(현재)** | 생성물이 아니라 **사람의 작업 기록**. 페이지별 변경이 잦고 메모에 민감 정보가 들어갈 수 있음 |
| 승인 데이터 | `data/exports/approved.jsonl` | **추적** | 사람이 승인한 페이지만 모은 배포용 데이터. `sync`가 아니라 `export_approved.py`로 생성 |
| 설계 | `docs/`, `schema/` | 추적 | 규칙과 JSON 계약 |
| 도구 | `scripts/`, `admin/` | 추적 | 파이프라인과 검수 UI |

`data/parsed/`와 `data/review/status.json`은 성격이 다르다.

- `data/parsed/`는 **AI 중간 산출물**이다. 승인 전에는 버려질 수 있으므로 git에 넣지 않는다.
- `data/review/status.json`은 **사람이 만든 검수 기록**이지만, 아직은 로컬에 둔다. 페이지별 churn과 민감 메모 때문이다. 감사·백업이 필요해지면 검수 세션 단위로 커밋하거나, 메모를 분리한 `summary.json`만 추적한다.
- 최종 데이터는 `data/exports/approved.jsonl`로 고정한다. **승인된 페이지만** 들어가며, raw `data/parsed/` 전체를 커밋하지 않는다.

---

## 4. 빠른 시작

처음이라면 **① 인벤토리 → ② 경로 → ③ 프롬프트 확인 → ⑦ 검수 도구** 순서로 감을 잡는다. AI 호출은 그다음이다.

```bash
# ① 스캔에서 페이지 인벤토리 생성 (없는 면은 missing으로 기록)
python3 scripts/build_manifest.py

# ② 앱/AI가 읽을 data/pages 경로 생성 (scan/을 가리키는 symlink)
python3 scripts/link_pages.py

# ③ API 호출 없이 프롬프트만 생성해 확인
python3 scripts/parse_page.py --section genealogy --page 25 --dry-run

# ⑦ 검수 도구 실행 (아직 파싱 결과가 없으면 빈 화면)
python3 admin/server.py --port 8765
# 브라우저: http://127.0.0.1:8765
```

실제 AI 파싱은 API 키와 모델을 지정한 뒤 실행한다.

```bash
export PAGE_AI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export PAGE_AI_API_KEY="<YOUR_KEY>"
export PAGE_AI_MODEL="gemini-2.5-flash"

python3 scripts/parse_page.py --section genealogy --page 25
python3 scripts/validate_page.py data/parsed/genealogy/0025.json --section genealogy --page 25
```

배치·OCR·검수 단축키·문제 해결은 [04. 작업 흐름](docs/04-workflow.ko.md)에 있다.

---

## 5. 현재 진행 상황

<!-- STATUS:BEGIN -->
> 이 표는 `STATUS.md`에서 자동 생성됩니다. 직접 수정하지 마세요.
>
> 마지막 갱신: **2026-10-31**, 기능 기준 커밋 `73f0a31`.

| 영역 | 상태 | 근거 |
|---|---|---|
| 스캔 정리·판독 규칙 | 완료 | `scan/frontmatter`, `scan/genealogy`, `docs/01`, `docs/02` |
| 페이지 인벤토리 | 완료 | `data/manifests/pages.csv` 1,031행 (미수록 32행) |
| 정규화 경로 | 완료 | `scripts/link_pages.py` → `data/pages/` symlink 1,001개 |
| AI 파싱 파이프라인 | 초안 완료 | `scripts/prompt.py`, `parse_page.py`, `validate_page.py`, `run_pipeline.py` |
| OCR 보조 | 초안 완료 / 미실행 | `scripts/ocr.py` (Tesseract 미설치) |
| 검수 도구 | 초안 완료 / 실사용 전 | `admin/server.py`, `admin/static/` |
| 승인 데이터 export | 완료 | `scripts/export_approved.py` → `data/exports/approved.jsonl` |
| AI 파일럿 파싱 | 대기 | API 키·모델 미지정 |
| DB 적재·공개 앱 | 대기 | DDL/import 스크립트 없음 |
<!-- STATUS:END -->

자세한 완료/진행/다음/블로커와 갱신 규칙은 **[STATUS.md](STATUS.md)** 에 있다. 위 표는 `STATUS.md`에서 `python3 scripts/sync_status.py`로 생성한다.

---

## 6. 문서

| 문서 | 내용 |
|---|---|
| [01. 족보 읽는 법](docs/01-reading-guide.ko.md) | 사람이 페이지를 읽는 기준 |
| [02. AI 파싱 가이드](docs/02-ai-parsing-guide.ko.md) | 프롬프트 정본과 JSON 필드 정의 |
| [03. 데이터 구성](docs/03-data-layout.ko.md) | 폴더·manifest·DB 페이지 모델 |
| [04. 작업 흐름](docs/04-workflow.ko.md) | 인벤토리 → 파싱 → 검수 실행법 |
| [STATUS.md](STATUS.md) | 현재 진행 상황과 다음 단계 |
