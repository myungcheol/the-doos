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
# 단일 이미지 OCR

Python 3.12 환경에서 CPU 기준 실행:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-ocr.txt
.venv/bin/python scripts/ocr_image.py scan/genealogy/001.jpg --output /tmp/ocr-001.json
```

최초 실행 시 PaddleOCR의 공식 모델 다운로드가 필요하다. 기본 설정은 CPU, `PP-OCRv5`, `chinese_cht`이다. 출력 파일이 이미 있으면 덮어쓰지 않는다. 결과는 원본 이미지 해시·크기, 모델과 실행 환경, 인식 문자열·신뢰도·원본 좌표를 담는다. 이 단계는 페이지 전체의 원시 인식이며 인물이나 관계를 확정하지 않는다. 실행 결과와 한계는 [기준선 기록](docs/research/ocr-baseline.md)을 참조한다.

## 전처리 검수

인물·본문 영역 후보와 전처리 결과를 검수하려면 다음을 실행하고 브라우저에서 `http://127.0.0.1:3000`을 연다. Python 3.12 환경과 OCR 의존성 설치가 먼저 필요하다.

```bash
cd review-web
npm install
npm run dev
```

쪽을 선택하고 분석 버튼을 누르면 검출한 단별로 실제 CPU OCR을 실행한다. 빨강은 단, 파랑은 열 후보, 주황은 이름 후보이며 인물을 선택하면 왼쪽 설명 후보를 확인할 수 있다. 최초 실행은 모델 다운로드가 필요하며 시간이 걸린다. 단 검출이 틀리면 OCR 결과도 영향을 받는다. 전처리와 인물 후보는 초안이고 수정·저장 기능은 아직 없다. 실행 중인 서버의 메모리에 분석 결과를 임시 보관하고, 중간 JSON은 시스템 임시 디렉터리에 남는다.

기울기 보정이 필요한 쪽은 원본을 보존하고 `data/ocr/deskew/`에 보정 PNG를 저장한다. 화면의 원본 분석·보정본 분석 버튼으로 각각 OCR 결과를 비교한다. 화면에서 선택한 분석본은 현재 화면에만 적용되며 영구 저장되지 않는다. 검출한 기울기가 불확실하거나 0.15도 미만이면 회전하지 않는다. 회전 행렬과 역행렬은 전처리 JSON에 포함된다.

T008 생몰·일반 부가 정보 분류는 인물을 선택하면 표시된다. 항목을 누르면 원문 근거 영역을 강조한다. 화면 상단의 ‘T008 규칙 샘플 검수’를 펼치면 OCR 없이 분류 예시를 볼 수 있다. [규칙·한계·검수 안내](docs/research/information-parser.md)를 참고한다.
