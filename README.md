# 두릉두씨세보

1987년 발행 두릉두씨세보(杜陵杜氏世譜)의 스캔을 판독하고, 인물과 계보를 검수·공개하는 프로젝트.
현재는 OCR·전처리·인물 후보와 부가 정보 분류를 검수하는 로컬 프로그램을 개발 중이다.

- [합의된 요구사항](docs/requirements.md)
- [결정 기록](docs/decisions.md)
- [티켓과 작업 방식](docs/tickets.md)
- [진행 이력](docs/progress.md)
- [세로쓰기 족보 판독 규칙: 초기 조사](docs/research/reading-rules.md)
- [왕대·연호 조사와 날짜 정규화 규칙](docs/research/date-normalization.md)

프로그램은 LLM 없이 PaddleOCR, 사전, 명시적인 규칙으로 동작한다.
자동 OCR 대상은 `scan/genealogy`이며 `scan/frontmatter`는 제외한다.
개발과 조사에는 AI 코딩 도구를 사용할 수 있다.

로컬 PostgreSQL은 `compose.yaml`로 실행한다. 환경 변수 예시는 `.env.postgres.example`, 시작·중지·데이터 유지 방법은 [로컬 PostgreSQL 안내](docs/research/local-postgres.md)를 참조한다.
페이지·OCR·인물 스키마와 마이그레이션 적용·검증 방법은 [DB 데이터 사전](db/README.md)에 정리했다.
# 단일 이미지 OCR

로컬 PostgreSQL에 마이그레이션을 적용한 뒤 Python 3.12 환경에서 실행한다.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-ocr.txt -r requirements-db.txt
.venv/bin/python scripts/ocr_image.py scan/genealogy/001.jpg
```

최초 실행 시 PaddleOCR의 공식 모델 다운로드가 필요하다. 기본 설정은 CPU, `PP-OCRv5`, `chinese_cht`이다. 명령은 원본 이미지 해시와 크기, 모델과 실행 환경, 인식 문자열과 좌표, 인물과 관계 후보를 PostgreSQL에 저장한다.

## 전처리 검수

인물·본문 영역 후보와 전처리 결과를 검수하려면 다음을 실행하고 브라우저에서 `http://127.0.0.1:3000`을 연다. 먼저 로컬 DB를 실행하고 [적재 안내](db/import-page.md)에 따라 검수할 쪽을 적재한다.

```bash
cd review-web
npm install
npm run dev
```

쪽을 선택하면 PostgreSQL에 저장한 실행을 연다. 빨강은 단, 파랑은 열, 주황은 이름 후보이며 인물을 선택하면 근거 영역을 확인할 수 있다. 새 쪽은 먼저 아래 명령으로 적재한다.

```bash
.venv/bin/python scripts/ocr_image.py scan/genealogy/002.jpg
```

원본과 보정본을 모두 적재한 쪽은 실행 선택기에서 두 결과를 비교할 수 있다. 보정본은 `scripts/import_page.py <스캔> --deskew`로 적재한다.

검수 화면은 왼쪽 스캔과 오른쪽 정보 영역으로 나뉜다. 오른쪽만 스크롤되며 인물 선택은 상단에 고정된다. ‘원문 후보’, ‘생몰·일반 정보’, ‘배우자·혼인’ 탭으로 내용을 전환하고 항목을 누르면 왼쪽 스캔의 근거 영역을 강조한다. T008 샘플 검수 패널은 제거했으며 자동 테스트용 fixture는 유지한다. [규칙·한계](docs/research/information-parser.md)를 참고한다.

단일 족보 스캔을 PostgreSQL에 적재하고 원문 근거를 조회하는 방법은 [단일 페이지 적재 안내](db/import-page.md)에 있다.

## 여러 파일 처리와 재시도

마이그레이션 009까지 적용한 뒤 저장소 루트에서 실행한다. 각 페이지를 순서대로 처리하며 한 파일이 실패해도 다음 파일로 진행한다.

```bash
.venv/bin/python scripts/ocr_batch.py scan/genealogy/001.jpg scan/genealogy/002.jpg
```

전체 파일은 `scan/genealogy/*.jpg`로 지정할 수 있다. `--list paths.txt`로 UTF-8 파일 목록을 읽을 수도 있다. 목록에는 한 줄에 경로 하나를 적고 상대 경로는 목록 파일이 있는 디렉터리를 기준으로 한다. 중복 경로는 한 번 처리한다. `--deskew`를 붙이면 보정이 필요한 이미지를 보정해서 처리한다.

실행 시작 시 배치 번호를 출력한다. 아래의 `1`은 출력된 배치 번호로 바꾼다.

```bash
.venv/bin/python scripts/ocr_batch.py --status 1
.venv/bin/python scripts/ocr_batch.py --retry 1
```

진행 상황과 오류는 DB에 남는다. 재시도는 실패·대기·중단 당시 처리 중이던 항목을 실행한다. 완료된 파일은 건너뛴다. Ctrl+C로 중단해도 같은 명령으로 이어서 처리할 수 있다. DB에 같은 OCR·추출 결과가 이미 있으면 기존 ID를 반환한다. 배치 항목에는 시도 횟수와 성공 여부만 기록한다. 결과가 달라 검수가 필요한 항목도 저장에 성공하면 성공 건수에 포함된다. 실패가 남으면 명령 종료 코드는 1, 중단은 130이다.
