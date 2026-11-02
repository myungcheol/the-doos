# 진행 상황

> 이 파일이 프로젝트 진행 상황의 **단일 기록**이다. 설계 문서(`docs/01`~`04`)에는 “현재 어디까지 했는지”를 쓰지 않는다.
> 마지막 갱신: **2026-11-02**, 기능 기준 커밋 `ad89c97`.

---

## 1. 요약

| 영역 | 상태 | 근거 |
|---|---|---|
| 스캔 정리·판독 규칙 | 완료 | `scan/frontmatter`, `scan/genealogy`, `docs/01`, `docs/02` |
| 페이지 인벤토리 | 완료 | `data/manifests/pages.csv` 1,031행 (미수록 32행) |
| 정규화 경로 | 완료 | `scripts/link_pages.py` → `data/pages/` symlink 1,001개 |
| AI 파싱 파이프라인 | 초안 완료 | `scripts/prompt.py`, `parse_page.py`, `validate_page.py`, `run_pipeline.py` |
| OCR 보조 | 초안 완료 / 미실행 | `scripts/ocr.py` (Tesseract 미설치) |
| 검수 도구 | 초안 완료 / 25면 검수 대기 | `admin/server.py`, `admin/static/` |
| 승인 데이터 export | 완료 | `scripts/export_approved.py` → `data/exports/approved.jsonl` |
| AI 파일럿 파싱 | 진행 중 / 25면 1차 결과 | `data/parsed/genealogy/0025.json` (로컬) |
| DB 적재·공개 앱 | 대기 | DDL/import 스크립트 없음 |

---

## 2. 완료

- 2026-10-28: `.jpeg` → `.jpg`, 3자리 zero-pad 정리, `scan/`을 전편/본편으로 분리.
- 2026-10-28: 판독 규칙 정리. 같은 단=같은 세대, 오른쪽→왼쪽, `上`/`下` 페이지 참조, 외손 예외.
- 2026-10-31: `docs/02` JSON 구조 정리. `aliases`, `birth.king_era`, `burial.orientation/note`, 인라인 `page_ref`.
- 2026-10-31: `schema/page.schema.json`, `docs/03` 데이터 모델, `docs/04` 실행 문서.
- 2026-10-31: `pages.csv` 생성. 전편 1~93 + 본편 1~938, 미수록 32행.
- 2026-10-31: manifest → symlink → 프롬프트 → AI 호출 → 검증 → 저장 파이프라인 초안.
- 2026-10-31: 이미지+JSON 검수 도구 초안. 상태 저장, JSON 편집, 승인 JSONL 내보내기.
- 2026-10-31: 추적 정책 확정. raw `data/parsed/`·`data/review/`는 로컬, 승인분 `data/exports/approved.jsonl`만 추적. `scripts/export_approved.py` 추가.
- 2026-10-31: `docs/04`에 사람/스크립트 역할, 기록 위치, `data/review`·`data/exports` 차이 정리.
- 2026-10-31: 필드명 `raw_name` → `as_printed`로 변경. 마이그레이션 스크립트 `scripts/migrate_raw_name.py` 추가.
- 2026-11-02: 판독 규칙 반영. `女` + 성씨+이름은 사위(배우자 `husband`)로 처리, `配`는 성별에 따라 wife/husband/concubine, 기준 인물은 `subjects[]`에만 기록하고 `entries[]` 중복을 검증 경고로 표시.
- 2026-11-02: `docs/01`·`docs/02`와 `schema/page.schema.json` 대조. `subjects[]`를 최상위 필드로 정리, `entries[].relation_to_subject`에서 `self` 제거, spouse `birth`/`death` 스키마 추가, `person.notes`·`children[].relation` 문서화, `validate_page.py`를 스키마 수준으로 강화.
- 2026-11-02: 25면 AI 1차 호출. OmniRoute `free-image-combo`(gemini-3-flash-preview, gemini-3.1-flash-lite) 결과를 `data/parsed/genealogy/0025.json`에 보관. reasoning 토큰이 출력 한도를 잠식해 첫 호출은 JSON이 잘렸고, 이후 flash-lite로 JSON을 확보했다. 현재 결과에는 기준 인물 중복(`self`)과 `F###` 표기 오류가 남아 있다.
- 2026-11-02: `PAGE_AI_MAX_TOKENS` 기본값을 32768로 상향. 구조 탭에서 기준 인물·인물 항목 삭제와 `page_ref`의 방향·구분·면 편집 지원.
- 2026-10-31: OmniRoute combo 대응. `PAGE_AI_MAX_TOKENS`·`PAGE_AI_EXTRA_HEADERS` 추가, 실제 응답 모델과 라우팅 헤더를 `*.meta.json`에 기록.
- 2026-10-31: 루트 `.env` 파일 자동 로드 지원. `.env.example` 제공, `.env`는 git 제외.

---

## 3. 진행 중

- **25면 검수 대기**: `data/parsed/genealogy/0025.json`은 AI 1차 결과다. 관리자 도구의 「구조」 탭에서 스캔과 대조한다.
  - 알려진 오류: 기준 인물 `子仁居`가 `subjects[]`와 `entries[]`에 중복, `page_ref.raw`가 `F159`·`F168`·`F170`·`F183`·`F187`·`F188`로 남음, `女姜海擧`·`女崔欽祖`를 사위(배우자)로 분리하지 않음.
- **파일럿 프롬프트 준비 완료**: 본편 1~6, 25, 62~63, 217, 932~933, 936~938 / 전편 47, 63, 65~66.
- **다음 파일럿 대상**: 62~63면(외손), 217면(世 비침), 932~938면(표/부록). 25면 검수에서 규칙을 확정한 뒤 진행한다.
- **API 키**: 저장소에 `.env`가 없다. 재호출은 사용자가 `.env` 또는 셸 환경변수로 키를 넣은 뒤 실행한다.

---

## 4. 다음 단계

1. **25면 검수·수정**
   - 관리자 도구에서 기준 인물 중복을 지우고, `F###`를 `下###`로 고치고, `女` 항목의 사위를 `spouses[]`로 옮긴다.
   - 규칙이 틀렸으면 `docs/01`·`docs/02`를 먼저 고친 뒤 `--force`로 다시 파싱한다.
2. **AI 파일럿 나머지 20~30면 실행**
   - 62~63면, 217면, 1~6면, 932~938면, 전편 47·63·65~66면.
   - 결과 JSON을 `validate_page.py`로 검사하고 `needs_human` 목록을 확인한다.
3. **검수 도구로 파일럿 검수**
   - 이미지와 JSON을 나란히 보고 62~63면·217면의 단/세대 해석이 맞는지 확인.
   - 잘못된 예시는 `docs/01`·`docs/02`에 즉시 반영한다.
   - 승인분은 `python3 scripts/export_approved.py`로 `data/exports/approved.jsonl`에 고정한다.
4. **모델·프롬프트 확정**
   - 페이지 유형별로 프롬프트가 충분한지 확인.
   - 필요하면 `schema/page.schema.json`과 `docs/02` §4를 함께 수정한다.
5. **DB 적재**
   - `sections`, `pages`, `toc_entries`, `page_refs` DDL.
   - `data/parsed/*.json` → PostgreSQL import 스크립트.
6. **항렬표 구조화**
   - `scan/frontmatter/063.jpg` → `generation_chars`.
7. **공개 웹앱**
   - `approved` 데이터만 노출.
   - 생존자·주소·묘소 좌표 등 민감 정보 masking 정책 확정 후 공개.

---

## 5. 블로커 / 확인 필요

| 항목 | 상태 | 필요한 결정 |
|---|---|---|
| AI 제공자·API 키 | OmniRoute 키 발급 완료 | 25면 첫 호출로 무료 이미지 모델과 한도 확인 |
| OmniRoute combo | 확인 필요 | vision 모델만으로 구성, 압축 off, 25면 결과 확인 |
| Tesseract | 미설치 | OCR 보조가 필요한지, vision 전용으로 갈지 |
| 검수 범위 | 미정 | 전수 검수 vs 표본 검수 |
| 민감 정보 공개 | 미정 | 생존자·주소·묘소 좌표 masking 여부 |
| 본편 1면 해석 | 확인됨 | 일반 `genealogy` 페이지로 처리 |

---

## 6. 갱신 규칙

- 진행 상황은 이 파일에만 쓴다. `docs/03`의 “다음 단계” 같은 섹션은 만들지 않는다.
- 상태 변화가 있으면 **날짜 + 커밋 해시**를 함께 적는다.
- 완료 항목은 `## 2. 완료`로 옮기고, 다음 단계는 `## 4. 다음 단계`에서 제거한다.
- 블로커가 풀리면 `## 5`에서 지우고, 결정 내용은 해당 설계 문서(`docs/01`~`04`)에 반영한다.
- 이 파일을 수정한 뒤 `python3 scripts/sync_status.py`를 실행해 README의 요약 표를 갱신한다. `--check`로 불일치를 검사할 수 있다.
