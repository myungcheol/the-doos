# data/exports

`approved.jsonl`은 **사람이 승인한 페이지만** 모은 배포용 데이터다. 이 디렉터리와 `approved.jsonl`은 git에 추적한다.

```bash
python3 scripts/export_approved.py
python3 scripts/export_approved.py --check
```

- 원본: `data/parsed/` + `data/review/status.json` (둘 다 로컬, git 제외)
- 출력: `data/exports/approved.jsonl` (한 줄에 한 페이지)
- 정렬: `section`, `printed_page_no`
- 직접 수정하지 않는다. 승인 상태가 바뀌면 스크립트를 다시 실행한다.

## 레코드 형식

```json
{"section":"genealogy","printed_page_no":25,"review":{"status":"approved","note":"","updated_at":"..."},"needs_human":0,"parsed":{"page":{},"entries":[]}}
```

## 주의: masking은 아직 자동이 아니다

이 스크립트는 승인 여부만 본다. 생존자·주소·묘소 좌표 등 민감 정보를 제거하지 않는다. 공개 저장소에 커밋하기 전에 다음 중 하나를 먼저 확정한다.

1. 승인 단계에서 민감 정보가 없는 페이지/항목만 승인한다.
2. 별도의 masking 스크립트를 만들어 `approved.jsonl` 생성 전에 적용한다.

masking 정책이 정해지기 전에는 이 파일을 **내부 검수용**으로만 두는 것을 권장한다.
