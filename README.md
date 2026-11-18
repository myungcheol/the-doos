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
