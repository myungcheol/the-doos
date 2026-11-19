# 두릉두씨세보

1987년 발행 두릉두씨세보(杜陵杜氏世譜)의 스캔을 판독하고, 인물과 계보를 검수·공개하는 프로젝트.
현재는 요구사항과 판독 규칙을 정리하는 단계이며 실행 가능한 프로그램은 아직 없다.

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

세대 단과 세로 열 후보를 검수하려면 다음을 실행하고 브라우저에서 `http://127.0.0.1:8765`을 연다.

```bash
.venv/bin/python scripts/review_preprocessing.py
```

빨간 상자는 세대 단, 파란 상자는 세로 글줄 후보, 노란 상자는 본문 틀이다. 이전·다음 버튼이나 좌우 화살표로 스캔을 넘길 수 있고, 표시 항목은 체크 상자로 끌 수 있다. 이 도구는 로컬 전용이며 결과를 수정하거나 저장하지 않는다.
