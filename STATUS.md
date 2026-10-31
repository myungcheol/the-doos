# 진행 상황

> 이 파일이 프로젝트 진행 상황의 **단일 기록**이다. 설계 문서(`docs/01`~`04`)에는 “현재 어디까지 했는지”를 쓰지 않는다.
> 마지막 갱신: **2026-10-31**, 기능 기준 커밋 `73f0a31`.

---

## 1. 요약

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

---

## 3. 진행 중

- **파일럿 준비**: 18면 프롬프트 생성 완료.
  - 본편 1~6, 62~63, 217, 932~933, 936~938
  - 전편 47, 63, 65~66
- **다음 파일럿 대상**: 25면(5단), 217면(世 비침), 62~63면(외손), 932~938면(표/부록).
- 실제 API 호출은 아직 하지 않았다. `PAGE_AI_API_KEY`, `PAGE_AI_MODEL`이 필요하다.

---

## 4. 다음 단계

1. **AI 파일럿 20~30면 실행**
   - 25면, 62~63면, 217면, 1~6면, 932~938면, 전편 47·63·65~66면.
   - 결과 JSON을 `validate_page.py`로 검사하고 `needs_human` 목록을 확인한다.
2. **검수 도구로 파일럿 검수**
   - 이미지와 JSON을 나란히 보고 25면·62~63면·217면의 단/세대 해석이 맞는지 확인.
   - 잘못된 예시는 `docs/01`·`docs/02`에 즉시 반영한다.
   - 승인분은 `python3 scripts/export_approved.py`로 `data/exports/approved.jsonl`에 고정한다.
3. **모델·프롬프트 확정**
   - 페이지 유형별로 프롬프트가 충분한지 확인.
   - 필요하면 `schema/page.schema.json`과 `docs/02` §4를 함께 수정한다.
4. **DB 적재**
   - `sections`, `pages`, `toc_entries`, `page_refs` DDL.
   - `data/parsed/*.json` → PostgreSQL import 스크립트.
5. **항렬표 구조화**
   - `scan/frontmatter/063.jpg` → `generation_chars`.
6. **공개 웹앱**
   - `approved` 데이터만 노출.
   - 생존자·주소·묘소 좌표 등 민감 정보 masking 정책 확정 후 공개.

---

## 5. 블로커 / 확인 필요

| 항목 | 상태 | 필요한 결정 |
|---|---|---|
| AI 제공자·API 키 | 미정 | 무료 이미지 모델과 한도 확인 |
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
