# 작업 흐름: 인벤토리 → 파싱 → 검수

> 이 문서는 실제로 손을 움직이는 순서를 정리한다. 판독 규칙은 [02](02-ai-parsing-guide.ko.md), 데이터 구조는 [03](03-data-layout.ko.md)이 정본이다.

---

## 0. 지금부터 할 일

§1 준비는 **이미 끝났다**. `data/manifests/pages.csv`와 `data/pages/`가 이미 있으므로 다시 만들지 않는다. 스캔을 추가·교체했을 때만 §1을 다시 실행한다.

현재 단계에서 사람이 직접 하는 일은 **검수**, **규칙 수정**, **진행 기록** 세 가지다. 나머지는 스크립트가 한다.

| 순서 | 할 일 | 누가 | 결과가 남는 곳 |
|---:|---|---|---|
| 1 | 무료 API 키 설정 (§2) | 사람 | 셸 환경변수 (파일 아님) |
| 2 | 25면 dry-run → 실제 파싱 (§3) | 스크립트 | `data/prompts/`, `data/parsed/` (로컬) |
| 3 | 파일럿 20~30면 파싱 (§4) | 스크립트 | `data/parsed/` (로컬) |
| 4 | 이미지와 JSON 대조 검수 (§5) | **사람** | `data/review/status.json` (로컬) |
| 5 | 잘못된 판독 규칙 수정 | **사람** | `docs/01`, `docs/02` (커밋) |
| 6 | 승인분 export (§5) | 스크립트 | `data/exports/approved.jsonl` (커밋) |
| 7 | 진행 상황 갱신 | **사람** | `STATUS.md` → README 자동 반영 |

**검수 루프**는 이렇게 돈다.

1. `admin/server.py`를 열고 25면·62~63면·217면처럼 구조가 다른 면부터 본다.
2. 이미지와 JSON이 맞으면 `3`(승인), 틀리면 `4`(수정 필요)로 표시하거나 JSON을 직접 고치고 `S`(저장)한다.
3. 규칙 자체가 틀렸다면 `docs/01`·`docs/02`를 고친 뒤 `--force`로 다시 파싱한다.
4. 승인분이 쌓이면 `python3 scripts/export_approved.py`를 실행한다.

---

## 1. 준비

> **이미 완료된 단계다.** 스캔 파일을 추가·교체했을 때만 다시 실행한다.

필수는 **Python 3.10+** 뿐이다. 외부 패키지를 설치하지 않는다. OCR을 보조 자료로 쓰고 싶을 때만 Tesseract를 설치한다.

```bash
# 선택: 로컬 OCR 보조 자료
sudo apt install tesseract-ocr tesseract-ocr-kor tesseract-ocr-chi-tra
```

```bash
cd /path/to/the-doos

# 1) 스캔 폴더에서 pages.csv 생성 (없는 면은 missing으로 기록)
python3 scripts/build_manifest.py

# 2) 앱/AI가 읽을 data/pages 경로 생성 (기본은 scan/을 가리키는 상대 symlink)
python3 scripts/link_pages.py
```

생성물:

| 경로 | 내용 |
|---|---|
| `data/manifests/pages.csv` | 1,031행. 전편 1~93 + 본편 1~938, 미수록 32행 포함 |
| `data/manifests/covers.csv` | 앞/뒷표지 |
| `data/pages/...` | `scan/` 원본을 가리키는 symlink (또는 `--copy`) |
| `schema/page.schema.json` | AI 출력 JSON Schema |
| `data/parsed/<section>/<4digit>.json` | 페이지별 파싱 결과 |
| `data/ocr/<section>/<4digit>.txt` | OCR 보조 텍스트 (선택) |
| `data/prompts/<section>/<4digit>.txt` | dry-run 프롬프트 |
| `data/review/status.json` | 검수 상태와 메모 |

`scan/`은 절대 수정하지 않는다. 파이프라인은 `data/`에만 쓴다.

---

## 2. AI 연결

`scripts/parse_page.py`는 **OpenAI 호환 `/chat/completions`**와 `image_url` 데이터 URL을 지원하는 제공자를 쓴다. 무료 티어가 있는 이미지 모델이면 된다.

| 환경변수 | 설명 |
|---|---|
| `PAGE_AI_BASE_URL` | 제공자 주소. 기본값은 Google AI Studio의 OpenAI 호환 엔드포인트 |
| `PAGE_AI_API_KEY` | API 키. 로컬 서버면 더미 값 가능 |
| `PAGE_AI_MODEL` | 모델 ID. **필수** |
| `PAGE_AI_TIMEOUT` | 초 단위, 기본 180 |
| `PAGE_AI_JSON_MODE` | `1`이면 `response_format=json_object` 요청 |

예시 (Google AI Studio, 무료 티어):

```bash
export PAGE_AI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export PAGE_AI_API_KEY="<YOUR_KEY>"
export PAGE_AI_MODEL="gemini-2.5-flash"
```

예시 (OpenRouter):

```bash
export PAGE_AI_BASE_URL="https://openrouter.ai/api/v1"
export PAGE_AI_API_KEY="<YOUR_KEY>"
export PAGE_AI_MODEL="<무료 이미지 모델 ID>"
```

모델 ID와 무료 정책은 자주 바뀐다. 실행 전에 제공자 콘솔에서 이미지 입력 지원 여부와 무료 한도를 확인한다.

> OCR은 AI의 일이 아니다. Vision 모델이 이미지를 직접 읽고, OCR은 필요할 때만 힌트로 붙인다.

---

## 3. 한 페이지 파싱

```bash
# 프롬프트만 생성 (API 호출 없음, 비용 0)
python3 scripts/parse_page.py --section genealogy --page 25 --dry-run

# 실제 호출
python3 scripts/parse_page.py --section genealogy --page 25

# OCR 힌트를 함께 넣기
python3 scripts/ocr.py --section genealogy --page 25
python3 scripts/parse_page.py --section genealogy --page 25 --ocr

# 결과 검증
python3 scripts/validate_page.py data/parsed/genealogy/0025.json --section genealogy --page 25
```

결과는 `data/parsed/genealogy/0025.json`, 호출 정보는 `0025.meta.json`에 저장된다.

---

## 4. 파일럿 배치

처음부터 999면을 돌리지 않는다. 구조가 다른 페이지만 20~30장 먼저 검증한다.

```bash
# 1~6면: 1면 세대표 + 초기 세보
python3 scripts/run_pipeline.py --section genealogy --from 1 --to 6

# 25면, 62~63면: 5단/6단, 외손 예외
python3 scripts/run_pipeline.py --section genealogy --from 62 --to 63

# 217면: 世 표기 비침 주의
python3 scripts/parse_page.py --section genealogy --page 217

# 말미: 재산목록·임원록·수단·간기
python3 scripts/run_pipeline.py --section genealogy --from 932 --to 938

# 전편: 목차·항렬표·색인
python3 scripts/run_pipeline.py --section frontmatter --from 47 --to 47
python3 scripts/run_pipeline.py --section frontmatter --from 63 --to 63
python3 scripts/run_pipeline.py --section frontmatter --from 65 --to 66
```

배치 옵션:

```bash
--from / --to       인쇄 면번호 범위
--limit N           앞에서 N면만
--type genealogy    특정 page_type만
--force             이미 파싱된 페이지도 다시 호출
--dry-run           프롬프트만 생성
--ocr               OCR sidecar 포함
--fail-fast         첫 실패에서 중단
--report            진행률만 출력
```

진행률:

```bash
python3 scripts/run_pipeline.py --report
```

---

## 5. 검수 도구

```bash
python3 admin/server.py --port 8765
# 브라우저: http://127.0.0.1:8765
```

화면 구성:

- 왼쪽: 페이지 목록. 구분/상태/파싱 여부/검색으로 필터.
- 가운데: 스캔 이미지. 휠·버튼 확대, 드래그 이동, 더블클릭 초기화.
- 오른쪽: JSON 편집기, OCR 텍스트, 검수 메모.
- 아래: `대기 / 검수 중 / 승인 / 수정 필요` 상태.

단축키:

| 키 | 동작 |
|---|---|
| `J` / `↓` | 다음 페이지 |
| `K` / `↑` | 이전 페이지 |
| `S` / `Ctrl+S` | JSON 저장 |
| `1`~`4` | 대기 / 검수 중 / 승인 / 수정 필요 |

저장 시 서버가 `scripts/validate_page.py`와 같은 규칙으로 검증한다. 오류가 있으면 저장을 거부하고, 경고만 있으면 저장하되 화면에 표시한다. 기존 파일은 `.json.bak`으로 한 번 백업한다.

승인 데이터 내보내기:

```bash
python3 scripts/export_approved.py
# data/exports/approved.jsonl 생성 (git 추적)
python3 scripts/export_approved.py --check
```

`approved` 상태이면서 `data/parsed/`에 JSON이 있는 페이지만 들어간다. 검증 오류가 있는 승인 페이지가 있으면 export를 중단한다. **masking은 아직 자동이 아니므로**, 공개 커밋 전에 `data/exports/README.md`의 주의사항을 확인한다.

검수 서버에서 바로 받고 싶으면 다음도 쓸 수 있다.

```bash
curl -o approved.jsonl 'http://127.0.0.1:8765/api/export?status=approved'
```

---

## 6. 검수 상태

| 상태 | 의미 |
|---|---|
| `pending` | 아직 보지 않음 |
| `in_review` | 보고 있는 중 |
| `approved` | 사람이 확인해 공개 가능 |
| `needs_fix` | 판독/구조 수정 필요 |

`needs_human=true`는 “AI가 확신하지 못함”이고, 검수 상태와 별개다. 검수 화면에서 `needs_human` 개수를 배지로 보여준다.

---

## 7. 문제가 생기면

- **이미지가 안 보임**: `python3 scripts/link_pages.py`를 실행했는지 확인한다. 서버는 `data/pages`가 없으면 `scan/` 원본으로 fallback한다.
- **`PAGE_AI_MODEL` 오류**: 모델 ID가 제공자에서 이미지 입력을 지원하는지 확인한다.
- **JSON 검증 실패**: `data/parsed/.../0025.meta.json`의 `validation_errors`와 `data/prompts/...`를 확인한다. 필요하면 `--force`로 한 번 더 호출한다.
- **미수록 페이지**: `pages.csv`에서 `page_type=missing`이다. 검수 도구에서 상태를 바꿀 수 없고, 이미지도 없다.

---

## 8. 무엇을 어디에 기록하나

| 기록 | 어디에 | 커밋? | 언제 |
|---|---|---|---|
| 페이지별 검수 상태·메모 | `data/review/status.json` (검수 UI에서 자동) | 아니오 | 페이지를 볼 때마다 |
| AI 원본 JSON | `data/parsed/` | 아니오 | 파싱할 때마다 |
| 판독 규칙 수정 | `docs/01`, `docs/02` | 예 | 규칙 오류를 발견했을 때 |
| 단계 진행 상황 | `STATUS.md` | 예 | 파일럿·검수·DB 단계가 끝났을 때 |
| 승인 데이터 | `data/exports/approved.jsonl` | 예 | 승인분을 export할 때 |

- `README.md`의 진행 상황 블록은 직접 고치지 않는다. `STATUS.md`를 고친 뒤 `python3 scripts/sync_status.py`를 실행한다.
- `data/review/status.json`과 `data/parsed/`는 **작업 상태**다. 직접 편집하지 말고 검수 UI/스크립트로만 바꾼다.
- `data/exports/approved.jsonl`도 직접 고치지 않는다. 항상 `export_approved.py`로 다시 만든다.

### `data/review`와 `data/exports`의 차이

| 디렉터리 | 답하는 질문 | 성격 | git |
|---|---|---|---|
| `data/review/` | “이 페이지를 봤나? 승인했나?” | 사람의 **작업 상태**. 페이지마다 자주 바뀌고 메모에 민감 내용이 들어갈 수 있음 | 제외 (`status.json`) |
| `data/exports/` | “공개해도 되는 최종 데이터가 무엇인가?” | 승인된 결과만 모은 **배포 데이터** | 추적 (`approved.jsonl`) |

즉 `review`는 검수 과정의 장부, `exports`는 그 결과의 출고품이다. `review`가 없으면 export할 수 없고, `review`만으로는 DB에 넣지 않는다.
