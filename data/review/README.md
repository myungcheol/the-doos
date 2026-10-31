# data/review

검수 상태와 메모를 두는 로컬 디렉터리다.

- `status.json`: 페이지별 `status`, `note`, `updated_at`. **git 제외**.
- `*.bak`: JSON 저장 시 남는 백업. **git 제외**.

## 왜 제외하나

`status.json`은 생성물이 아니라 사람의 작업 기록이다. 다만 페이지를 볼 때마다 바뀌고, 메모에 민감한 내용이 들어갈 수 있어 기본적으로 로컬에 둔다.

검수 이력의 백업·감사가 필요해지면 다음 중 하나를 선택한다.

1. 검수 세션 단위로 `status.json`을 커밋한다. (`.gitignore`에서 제외 해제)
2. 메모를 분리하고, 상태와 페이지만 담은 `summary.json`을 별도로 추적한다.
3. 승인된 결과만 `data/exports/approved.jsonl`로 고정한다. (현재 권장)

## 형식

```json
{
  "genealogy:25": {
    "status": "approved",
    "note": "25면 5단 확인",
    "updated_at": "2026-10-31T06:00:00+00:00"
  }
}
```

상태 값: `pending`, `in_review`, `approved`, `needs_fix`.
