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
- PostgreSQL 적재는 `python3 scripts/import_db.py`가 만든 SQL로 한다. `import.sql`은 생성물이라 git에 올리지 않는다.

## 레코드 형식

```json
{"section":"genealogy","printed_page_no":25,"review":{"status":"approved","updated_at":"..."},"needs_human":0,"parsed":{"page":{},"entries":[]}}
```

검수 메모(`review.note`)는 내부 기록이므로 export에 넣지 않는다. `data/review/status.json`에만 남는다.

## 공개 정책: 승인분은 그대로 공개

생존자·주소·묘소 좌표를 가리지 않는다. 1986년 간행본과 같은 범위로 공개하는 것이 확정된 정책이다. 따라서 승인은 곧 공개다.

- `approved.jsonl`은 공개 저장소에 그대로 올라간다.
- 공개 앱은 `public_*` 뷰를 쓴다(`db/schema.sql` §6). `raw` JSON·`confidence`·`needs_human`·검수 플래그는 공개하지 않는다.
- 검수 메모와 `data/parsed/` 원문은 공개하지 않는다.
- 정책을 바꿀 때는 `public_*` 뷰만 고치면 된다. 원본 테이블은 그대로 둔다.
