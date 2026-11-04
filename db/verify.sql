-- 적재 후 확인 쿼리
--
--   psql "$DATABASE_URL" -X -f db/verify.sql
--
-- 읽기 전용이다. 값을 고치지 않는다.

\echo '== 1. 적재 요약 =='
SELECT (SELECT count(*) FROM pages)                                    AS pages,
       (SELECT count(*) FROM approved_pages)                           AS approved_pages,
       (SELECT count(*) FROM people)                                   AS people,
       (SELECT count(*) FROM person_names)                             AS names,
       (SELECT count(*) FROM person_events)                            AS events,
       (SELECT count(*) FROM marriages)                                AS marriages,
       (SELECT count(*) FROM burials)                                  AS burials,
       (SELECT count(*) FROM page_refs)                                 AS page_refs,
       (SELECT count(*) FROM relations)                                AS relations,
       (SELECT count(*) FROM index_entries)                            AS index_entries,
       (SELECT count(*) FROM generation_chars)                         AS generation_chars;

\echo '== 2. 섹션별 페이지 상태 =='
SELECT s.code, p.review_status, count(*) AS pages
FROM pages p
JOIN sections s ON s.id = p.section_id
GROUP BY s.code, p.review_status
ORDER BY s.code, p.review_status;

\echo '== 3. 승인됐지만 인물이 없는 페이지 =='
SELECT s.code AS section, p.printed_page_no, p.page_type
FROM approved_pages p
JOIN sections s ON s.id = p.section_id
WHERE p.page_type <> 'missing'
  AND NOT EXISTS (SELECT 1 FROM people pe WHERE pe.source_page_id = p.id)
ORDER BY s.code, p.printed_page_no;

\echo '== 4. 아버지 연결 미해결 =='
SELECT count(*) AS unresolved_fathers
FROM people
WHERE father_raw IS NOT NULL AND father_id IS NULL;

SELECT s.code AS section, p.printed_page_no, pe.row_no, pe.column_no, pe.as_printed,
       pe.father_source, pe.father_raw
FROM people pe
JOIN pages p ON p.id = pe.source_page_id
JOIN sections s ON s.id = p.section_id
WHERE pe.father_raw IS NOT NULL AND pe.father_id IS NULL
ORDER BY s.code, p.printed_page_no, pe.row_no, pe.column_no
LIMIT 50;

\echo '== 5. 아버지 연결 근거 분포 =='
SELECT father_source, count(*) AS people
FROM people
WHERE father_raw IS NOT NULL
GROUP BY father_source
ORDER BY father_source;

\echo '== 6. 페이지 참조 미해결 (대상 면이 미수록이면 정상) =='
SELECT count(*) AS unresolved_refs FROM page_refs WHERE target_page_id IS NULL;

SELECT s.code AS section, p.printed_page_no, r.raw_ref, r.direction,
       ts.code AS target_section, r.target_page_no
FROM page_refs r
JOIN pages p ON p.id = r.source_page_id
JOIN sections s ON s.id = p.section_id
JOIN sections ts ON ts.id = r.target_section_id
WHERE r.target_page_id IS NULL
ORDER BY s.code, p.printed_page_no
LIMIT 50;

\echo '== 7. 아버지 순환 (0이어야 정상) =='
WITH RECURSIVE walk AS (
  SELECT id, father_id, ARRAY[id] AS path, false AS cycle
  FROM people
  WHERE father_id IS NOT NULL
  UNION ALL
  SELECT w.id, p.father_id, w.path || p.id, p.id = ANY(w.path)
  FROM walk w
  JOIN people p ON p.id = w.father_id
  WHERE NOT w.cycle
)
SELECT count(*) AS father_cycles FROM walk WHERE cycle;

\echo '== 8. 세대 번호 없는 승인 인물 (검수 시 스캔의 世 표기로 채운다) =='
SELECT count(*) AS people_without_generation
FROM approved_people
WHERE generation_no IS NULL;

\echo '== 9. 마지막 적재 기록 =='
SELECT id, finished_at, source_file, pages, people, jsonb_array_length(warnings) AS warnings
FROM import_runs
ORDER BY id DESC
LIMIT 5;
