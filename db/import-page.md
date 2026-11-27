# 본문 한 페이지를 PostgreSQL에 적재하기

저장소 루트에서 OCR 가상환경과 로컬 Compose DB를 사용한다. [DB 설치 안내](README.md)에 따라 새 설치에는 001~008을, 기존 설치에는 누락된 마이그레이션만 번호순으로 적용한다.

```sh
.venv/bin/python -m pip install -r requirements-db.txt
.venv/bin/python scripts/ocr_image.py scan/genealogy/001.jpg
```

기본 명령은 원본에서 단을 찾고 PaddleOCR를 실행한 뒤 메모리에서 인물 후보를 추출하여 원시 OCR과 함께 DB에 적재한다. `import_page.py`도 동일한 적재 함수를 호출한다.

`import_page.py`에서는 다음 옵션을 사용할 수 있다. 이미 판독한 파일은 `--ocr output/t019/ocr.json`으로 재사용할 수 있다. 입력 이미지의 SHA-256과 크기가 일치해야 한다. `--deskew`를 지정하면 보정이 필요한 경우 보정본을 보관하고, OCR 좌표와 원본 인물 좌표를 변환 행렬로 연결한다. frontmatter와 누락 번호는 입력 대상에서 제외한다. 책 정렬 번호는 표지 0, 앞부분 1~66, 본문 66+파일 번호 순이다.

기본 연결은 Compose 컨테이너에 설정된 계정과 로컬 공개 포트를 사용한다. 별도 PostgreSQL을 사용할 때는 libpq의 PGSERVICE 또는 PGDATABASE와 연결 환경 변수를 설정한다.

| 명령 결과 | DB에서 확인할 내용 |
|---|---|
| `applied` | 페이지에서 처음 적재한 추출이다. 인물과 출현·독음 후보, 사실과 원문 문자 범위, 배우자 인물·혼인, 부모 자녀 후보를 함께 저장한다. |
| `replay: true` | 같은 OCR 파일과 추출을 다시 넣어 기존 적재 ID를 반환했다. |
| `equivalent` | 새 OCR 실행에서 동일한 인물 추출 결과가 나왔다. 실행과 근거 영역을 보관하고 기존 인물 출현에 연결한다. 기존 사실의 문자 근거는 최초 실행에 남는다. |
| `needs_review` | 새 추출이 기존 추출과 달라 비교가 필요하다. 새 추출 전체가 page_imports.extraction에 보존된다. 현재 자동 비교는 좌표·신뢰도와 파서 버전도 포함하므로 작은 차이도 검수 대상이 된다. DB에서 후보별 대조·채택하는 UI는 후속 검수 티켓의 작업이다. |

한 페이지의 DB 쓰기는 한 트랜잭션이다. 같은 페이지에 대한 동시 적재는 직렬 처리한다. 다른 쪽을 가리키는 표지는 원문 OCR 영역, 방향, 대상 번호와 함께 보관한다. unprocessed는 상대 인물 연결을 아직 처리하지 않은 상태, scan_missing은 그 번호의 스캔이 없는 상태다. OCR이 F를 下로 추정하면 방향 불확실 표시를 남긴다.

## 001쪽 검수

```sh
docker compose exec postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
SET search_path TO genealogy;
SELECT i.id,i.run_id,i.status FROM page_imports i JOIN pages p ON p.id=i.page_id
WHERE p.section='genealogy' AND p.page_key='001' ORDER BY i.id;

-- 之建의 배우자가 독립된 인물 ID를 갖고, 부가 정보 원문은 之建에게 기록되어 있다.
SELECT a.name_hanja AS 기록주인, m.spouse_id, m.relation_type, f.raw_text
FROM current_marriages m JOIN persons a ON a.id=m.person_id
JOIN marriage_sources s ON s.marriage_id=m.id JOIN person_facts f ON f.id=s.fact_id
JOIN person_occurrences o ON o.id=f.occurrence_id JOIN page_images im ON im.id=o.original_image_id
JOIN pages p ON p.id=im.page_id WHERE p.page_key='001' AND a.name_hanja='之建';

-- 최초 적재의 다른 쪽 표지와 방향 판독
SELECT g.raw_text, r.target_page_key, r.status, r.direction_uncertain
FROM page_reference_candidates r JOIN page_imports i ON i.id=r.import_id
JOIN pages p ON p.id=i.page_id JOIN ocr_regions g ON g.id=r.region_id
WHERE p.page_key='001' AND i.status='applied';
```

자동 검증은 임시 DB에 합성 OCR을 적재해 두 배우자의 소속, 실패 시 전체 롤백, 같은 파일 재적재, 새 실행과 검수값 보존, 누락 페이지 참조를 확인한다.

```sh
.venv/bin/python tests/verify_page_import.py
```

## 검수 화면에서 열기

`cd review-web && npm ci && npm run dev`로 검수 화면을 연다. 쪽을 선택하면 PostgreSQL의 최신 적재가 열리고, 실행 선택기에서 이전 적재와 원본·보정본을 바꿀 수 있다. 다른 쪽 참조도 저장된 결과에서 읽는다. 미적재 페이지에는 스캔과 미적재 안내가 표시된다. 서버는 기본으로 저장소 루트 .env의 POSTGRES 설정을 사용하며 PGDATABASE를 지정하면 pg 연결 환경 변수를 사용한다.

생몰·관계 등 후보 탭과 상자는 해당 실행의 OCR 근거다. 인물을 선택한 뒤 **현재 검수값**에서 DB의 인물 상태와 현재 조회되는 사실·수동 풀이를 확인한다. 미연결 재추출은 현재값을 표시할 인물이 없다. 화면 편집과 관리자 인증은 T021·T023·T024에서 구현한다.
