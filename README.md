# 杜陵杜氏世譜 (1986, 金浦派) 디지털화

1986년 간행 『杜陵杜氏世譜』(金浦派) 스캔을 페이지 인벤토리 → AI 파싱 → 사람 검수 → 공개 데이터로 만드는 프로젝트입니다.

- 스캔 원본은 `scan/`에 그대로 보존합니다. **재스캔하지 않습니다.**
- 없는 면은 지우거나 추적하지 않고 `missing`(“미수록”)으로 기록합니다.
- 판독 규칙은 [`docs/02-ai-parsing-guide.ko.md`](docs/02-ai-parsing-guide.ko.md)가 단일 정본입니다.

## 빠른 시작

```bash
# 1) 인벤토리 생성
python3 scripts/build_manifest.py

# 2) 앱/AI용 경로 생성 (scan/을 가리키는 symlink)
python3 scripts/link_pages.py

# 3) 프롬프트만 확인 (API 호출 없음)
python3 scripts/parse_page.py --section genealogy --page 25 --dry-run

# 4) 검수 도구
python3 admin/server.py --port 8765
# http://127.0.0.1:8765
```

AI 호출 설정과 배치 실행은 [`docs/04-workflow.ko.md`](docs/04-workflow.ko.md)를 참고하세요.

## 문서

| 문서 | 내용 |
|---|---|
| [01. 족보 읽는 법](docs/01-reading-guide.ko.md) | 사람이 페이지를 읽는 기준 |
| [02. AI 파싱 가이드](docs/02-ai-parsing-guide.ko.md) | 프롬프트 정본과 JSON 필드 정의 |
| [03. 데이터 구성](docs/03-data-layout.ko.md) | 폴더·manifest·DB 페이지 모델 |
| [04. 작업 흐름](docs/04-workflow.ko.md) | 인벤토리 → 파싱 → 검수 실행법 |

## 주요 경로

| 경로 | 설명 |
|---|---|
| `scan/frontmatter/`, `scan/genealogy/` | 원본 스캔 (전편/본편) |
| `data/manifests/pages.csv` | 1,031행 페이지 인벤토리 (미수록 32행 포함) |
| `data/pages/` | 정규화 경로 (생성물, git 제외) |
| `data/parsed/` | 페이지별 JSON (생성물, git 제외) |
| `schema/page.schema.json` | AI 출력 JSON Schema |
| `admin/` | 이미지+JSON 검수 도구 |
| `scripts/` | manifest·OCR·프롬프트·파싱·검증·배치 |
