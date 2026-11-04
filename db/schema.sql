-- 杜陵杜氏世譜 (1986, 金浦派) PostgreSQL schema
--
-- 이 파일은 `docs/03-data-layout.ko.md`의 페이지 모델을 실제 DDL로 옮긴 것이다.
-- `scripts/import_db.py`가 만든 SQL과 함께 실행한다.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f data/exports/import.sql
--
-- PostgreSQL 13+ 기준. 재실행해도 되는 `IF NOT EXISTS` 형태다.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 1. 페이지
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sections (
  id         bigserial PRIMARY KEY,
  code       text NOT NULL UNIQUE,
  title      text NOT NULL,
  page_start integer,
  page_end   integer,
  numbering  text NOT NULL CHECK (numbering IN ('independent', 'continuous', 'none')),
  note       text
);

CREATE TABLE IF NOT EXISTS pages (
  id              bigserial PRIMARY KEY,
  section_id      bigint NOT NULL REFERENCES sections(id) ON DELETE RESTRICT,
  printed_page_no integer NOT NULL CHECK (printed_page_no >= 1),
  scan_seq        integer,
  page_type       text NOT NULL CHECK (page_type IN (
    'genealogy', 'preface', 'photo', 'index', 'generation_name_table',
    'property', 'officers', 'subscription', 'colophon', 'cover', 'missing', 'unknown'
  )),
  image_path      text,
  image_sha256    text,
  width           integer,
  height          integer,
  dpi             integer,
  quality_flags   text[] NOT NULL DEFAULT '{}',
  manifest_notes  text,
  ocr_status      text NOT NULL DEFAULT 'pending'
                  CHECK (ocr_status IN ('pending', 'queued', 'processing', 'done', 'failed', 'skipped')),
  review_status   text NOT NULL DEFAULT 'pending'
                  CHECK (review_status IN ('pending', 'in_review', 'approved', 'needs_fix', 'rejected', 'published')),
  raw             jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (section_id, printed_page_no),
  -- 미수록 면은 이미지가 없다. 나머지 면은 manifest 경로와 해시가 있어야 한다.
  CHECK (page_type = 'missing' OR (image_path IS NOT NULL AND image_sha256 IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS pages_review_status_idx ON pages (review_status);
CREATE INDEX IF NOT EXISTS pages_page_type_idx ON pages (page_type);

-- 인물 구조화 대상이 아닌 본문/캡션/주석. index_entries는 별도 테이블을 쓴다.
CREATE TABLE IF NOT EXISTS page_texts (
  id          bigserial PRIMARY KEY,
  page_id     bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  kind        text NOT NULL DEFAULT 'body'
              CHECK (kind IN ('body', 'heading', 'colophon', 'caption', 'annotation', 'other')),
  subkind     text,
  raw_text    text,
  normalized  text,
  language    text,
  bbox        jsonb,
  confidence  numeric(4, 3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS page_texts_page_idx ON page_texts (page_id);

CREATE TABLE IF NOT EXISTS page_tables (
  id       bigserial PRIMARY KEY,
  page_id  bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  title    text,
  headers  jsonb NOT NULL DEFAULT '[]',
  rows     jsonb NOT NULL DEFAULT '[]',
  bbox     jsonb
);

CREATE INDEX IF NOT EXISTS page_tables_page_idx ON page_tables (page_id);

CREATE TABLE IF NOT EXISTS unreadable_regions (
  id      bigserial PRIMARY KEY,
  page_id bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  bbox    jsonb NOT NULL,
  reason  text NOT NULL CHECK (reason IN ('blur', 'bleed_through', 'cut_off', 'unknown_char', 'other'))
);

CREATE INDEX IF NOT EXISTS unreadable_regions_page_idx ON unreadable_regions (page_id);

-- ---------------------------------------------------------------------------
-- 2. 인물
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS people (
  id                bigserial PRIMARY KEY,
  source_page_id    bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  row_no            integer NOT NULL CHECK (row_no >= 1),
  column_no         integer NOT NULL CHECK (column_no >= 1),
  is_subject        boolean NOT NULL DEFAULT false,
  as_printed        text NOT NULL,
  name_hanja        text,
  name_hangul       text,
  prefix            text,
  generation_no     integer CHECK (generation_no IS NULL OR generation_no >= 1),
  generation_char   text,
  generation_offset integer CHECK (generation_offset IS NULL OR generation_offset >= 0),
  page_relation     text NOT NULL DEFAULT 'unknown'
                    CHECK (page_relation IN (
                      'self', 'son', 'daughter', 'brother', 'sister', 'sibling',
                      'grandson', 'granddaughter', 'descendant', 'spouse',
                      'son_in_law', 'daughter_in_law', 'unknown'
                    )),
  father_id         bigint REFERENCES people(id) ON DELETE SET NULL,
  father_relation   text,
  father_raw        jsonb,
  father_source     text NOT NULL DEFAULT 'unknown'
                    CHECK (father_source IN ('printed', 'inferred', 'reviewed', 'unknown')),
  father_confidence numeric(4, 3)
                    CHECK (father_confidence IS NULL OR (father_confidence >= 0 AND father_confidence <= 1)),
  needs_human       boolean NOT NULL DEFAULT false,
  confidence        numeric(4, 3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  bbox              jsonb,
  notes             text[] NOT NULL DEFAULT '{}',
  offices           text[] NOT NULL DEFAULT '{}',
  raw               jsonb NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_page_id, row_no, column_no),
  CHECK (father_id IS NULL OR father_id <> id)
);

CREATE INDEX IF NOT EXISTS people_page_idx ON people (source_page_id);
CREATE INDEX IF NOT EXISTS people_father_idx ON people (father_id);
CREATE INDEX IF NOT EXISTS people_generation_idx ON people (generation_no);
CREATE INDEX IF NOT EXISTS people_name_hanja_idx ON people (name_hanja);

CREATE TABLE IF NOT EXISTS person_names (
  id        bigserial PRIMARY KEY,
  person_id bigint NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  kind      text NOT NULL CHECK (kind IN ('hanja', 'hangul', 'ja', 'ho', 'other')),
  value     text NOT NULL,
  ordinal   integer NOT NULL DEFAULT 0,
  UNIQUE (person_id, kind, value)
);

CREATE INDEX IF NOT EXISTS person_names_value_idx ON person_names (value);

CREATE TABLE IF NOT EXISTS person_events (
  id          bigserial PRIMARY KEY,
  person_id   bigint NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  event_type  text NOT NULL CHECK (event_type IN ('birth', 'death')),
  date_raw    text,
  king_era    text,
  ganji       text,
  date_text   text,
  certainty   text CHECK (certainty IN ('exact', 'probable', 'uncertain', 'unknown')),
  UNIQUE (person_id, event_type)
);

CREATE INDEX IF NOT EXISTS person_events_person_idx ON person_events (person_id);

CREATE TABLE IF NOT EXISTS marriages (
  id                bigserial PRIMARY KEY,
  person_id         bigint NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  ordinal           integer NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
  spouse_person_id  bigint REFERENCES people(id) ON DELETE SET NULL,
  spouse_as_printed text NOT NULL,
  spouse_name_hanja text,
  spouse_bonkwan    text,
  spouse_father     text,
  relation          text NOT NULL DEFAULT 'unknown'
                    CHECK (relation IN ('wife', 'husband', 'concubine', 'unknown')),
  birth             jsonb,
  death             jsonb,
  certainty         text CHECK (certainty IN ('exact', 'probable', 'uncertain', 'unknown')),
  source_page_id    bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  bbox              jsonb,
  raw               jsonb NOT NULL,
  UNIQUE (person_id, ordinal)
);

CREATE INDEX IF NOT EXISTS marriages_person_idx ON marriages (person_id);
CREATE INDEX IF NOT EXISTS marriages_page_idx ON marriages (source_page_id);

CREATE TABLE IF NOT EXISTS burials (
  id          bigserial PRIMARY KEY,
  person_id   bigint REFERENCES people(id) ON DELETE CASCADE,
  marriage_id bigint REFERENCES marriages(id) ON DELETE CASCADE,
  burial_raw  text,
  location    text,
  orientation text,
  note        text,
  certainty   text CHECK (certainty IN ('exact', 'probable', 'uncertain', 'unknown')),
  raw         jsonb,
  CHECK ((person_id IS NOT NULL)::int + (marriage_id IS NOT NULL)::int = 1)
);

CREATE INDEX IF NOT EXISTS burials_person_idx ON burials (person_id);
CREATE INDEX IF NOT EXISTS burials_marriage_idx ON burials (marriage_id);

-- ---------------------------------------------------------------------------
-- 3. 페이지 참조와 인물 관계
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS page_refs (
  id                bigserial PRIMARY KEY,
  source_page_id    bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  source_person_id  bigint REFERENCES people(id) ON DELETE CASCADE,
  raw_ref           text NOT NULL,
  direction         text NOT NULL CHECK (direction IN ('up', 'down')),
  target_section_id bigint NOT NULL REFERENCES sections(id),
  target_page_no    integer NOT NULL CHECK (target_page_no >= 1),
  target_page_id    bigint REFERENCES pages(id) ON DELETE SET NULL,
  confidence        numeric(4, 3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  note              text,
  bbox              jsonb
);

CREATE INDEX IF NOT EXISTS page_refs_source_page_idx ON page_refs (source_page_id);
CREATE INDEX IF NOT EXISTS page_refs_source_person_idx ON page_refs (source_person_id);
CREATE INDEX IF NOT EXISTS page_refs_target_idx ON page_refs (target_section_id, target_page_no);

-- `children[]`처럼 father_id로 표현할 수 없는 관계. 직계 부자 관계는 people.father_id만 쓴다.
CREATE TABLE IF NOT EXISTS relations (
  id             bigserial PRIMARY KEY,
  source_page_id bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  from_person_id bigint NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  to_person_id   bigint REFERENCES people(id) ON DELETE SET NULL,
  to_as_printed  text,
  relation_type  text NOT NULL CHECK (relation_type IN (
    'son', 'daughter', 'adopted_son', 'son_in_law', 'daughter_in_law', 'other', 'unknown'
  )),
  raw            jsonb NOT NULL,
  UNIQUE (from_person_id, relation_type, to_as_printed)
);

CREATE INDEX IF NOT EXISTS relations_from_idx ON relations (from_person_id);
CREATE INDEX IF NOT EXISTS relations_to_idx ON relations (to_person_id);

-- ---------------------------------------------------------------------------
-- 4. 색인, 목차, 항렬표
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS index_entries (
  id                bigserial PRIMARY KEY,
  page_id           bigint NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  name_hanja        text NOT NULL,
  name_hangul       text,
  target_section_id bigint REFERENCES sections(id),
  target_page_no    integer CHECK (target_page_no IS NULL OR target_page_no >= 1),
  target_page_id    bigint REFERENCES pages(id) ON DELETE SET NULL,
  raw_ref           text,
  bbox              jsonb
);

CREATE INDEX IF NOT EXISTS index_entries_page_idx ON index_entries (page_id);
CREATE INDEX IF NOT EXISTS index_entries_name_idx ON index_entries (name_hanja);

CREATE TABLE IF NOT EXISTS toc_entries (
  id                bigserial PRIMARY KEY,
  source_page_id    bigint REFERENCES pages(id) ON DELETE CASCADE,
  section_id        bigint NOT NULL REFERENCES sections(id),
  item_no           integer,
  title             text NOT NULL,
  target_section_id bigint NOT NULL REFERENCES sections(id),
  target_page_no    integer CHECK (target_page_no IS NULL OR target_page_no >= 1),
  target_page_id    bigint REFERENCES pages(id) ON DELETE SET NULL,
  note              text
);

CREATE INDEX IF NOT EXISTS toc_entries_source_idx ON toc_entries (source_page_id);

CREATE TABLE IF NOT EXISTS generation_chars (
  id             bigserial PRIMARY KEY,
  generation_no  integer NOT NULL CHECK (generation_no >= 1),
  branch_code    text,
  char_hanja     text NOT NULL,
  char_hangul    text,
  position       text CHECK (position IN ('first', 'middle', 'last', 'any')),
  source_page_id bigint REFERENCES pages(id) ON DELETE SET NULL,
  note           text,
  UNIQUE (generation_no, char_hanja, source_page_id)
);

CREATE INDEX IF NOT EXISTS generation_chars_generation_idx ON generation_chars (generation_no);

-- ---------------------------------------------------------------------------
-- 5. 적재 기록과 공개용 뷰
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS import_runs (
  id          bigserial PRIMARY KEY,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  source_file text NOT NULL,
  pages       integer NOT NULL DEFAULT 0,
  people      integer NOT NULL DEFAULT 0,
  warnings    jsonb NOT NULL DEFAULT '[]'
);

-- 승인된 페이지만 모은 내부 뷰. 공개 앱은 아래 public_* 뷰를 쓴다.
CREATE OR REPLACE VIEW approved_pages AS
SELECT p.*
FROM pages p
WHERE p.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW approved_people AS
SELECT pe.*
FROM people pe
JOIN pages p ON p.id = pe.source_page_id
WHERE p.review_status IN ('approved', 'published');

-- ---------------------------------------------------------------------------
-- 6. 공개 뷰 (공개 앱의 API 표면)
-- ---------------------------------------------------------------------------
--
-- 정책: 승인분은 **그대로 공개**한다. 생존자·주소·묘소 좌표도 가리지 않는다
-- (1986년 간행본과 같은 범위). 대신 검수용 내부 값은 공개하지 않는다.
--   * `raw` JSON, `confidence`, `father_confidence`, `needs_human`
--   * `ocr_status`, `quality_flags`, `manifest_notes`, `image_sha256`
--   * bigserial `id` — 재적재마다 인물 행이 새로 들어가므로 id가 바뀐다.
-- 공개 식별자는 `(section_code, printed_page_no, row_no, column_no)`를 쓴다.

CREATE OR REPLACE VIEW public_pages AS
SELECT s.code            AS section_code,
       p.printed_page_no,
       p.scan_seq,
       p.page_type,
       p.image_path,
       p.width,
       p.height
FROM pages p
JOIN sections s ON s.id = p.section_id
WHERE p.review_status IN ('approved', 'published');

-- 전체 면 인벤토리. 미수록/미공개 면을 앱에서 표시하기 위한 것으로,
-- 공개되지 않은 면의 이미지 경로나 본문은 담지 않는다.
CREATE OR REPLACE VIEW public_page_inventory AS
SELECT s.code AS section_code,
       p.printed_page_no,
       p.scan_seq,
       p.page_type,
       (p.review_status IN ('approved', 'published')) AS is_published
FROM pages p
JOIN sections s ON s.id = p.section_id;

CREATE OR REPLACE VIEW public_people AS
SELECT s.code             AS section_code,
       pg.printed_page_no,
       pe.row_no,
       pe.column_no,
       pe.is_subject,
       pe.as_printed,
       pe.name_hanja,
       pe.name_hangul,
       pe.prefix,
       pe.generation_no,
       pe.generation_char,
       pe.page_relation,
       fs.code            AS father_section_code,
       fp.printed_page_no AS father_page_no,
       f.row_no           AS father_row_no,
       f.column_no        AS father_column_no,
       f.as_printed       AS father_as_printed,
       pe.father_relation,
       pe.father_source,
       pe.notes,
       pe.offices
FROM people pe
JOIN pages pg ON pg.id = pe.source_page_id
JOIN sections s ON s.id = pg.section_id
LEFT JOIN people f ON f.id = pe.father_id
LEFT JOIN pages fp ON fp.id = f.source_page_id
LEFT JOIN sections fs ON fs.id = fp.section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_person_names AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       pe.row_no,
       pe.column_no,
       n.kind,
       n.value,
       n.ordinal
FROM person_names n
JOIN people pe ON pe.id = n.person_id
JOIN pages pg ON pg.id = pe.source_page_id
JOIN sections s ON s.id = pg.section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_person_events AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       pe.row_no,
       pe.column_no,
       e.event_type,
       e.date_raw,
       e.king_era,
       e.ganji,
       e.date_text,
       e.certainty
FROM person_events e
JOIN people pe ON pe.id = e.person_id
JOIN pages pg ON pg.id = pe.source_page_id
JOIN sections s ON s.id = pg.section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_marriages AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       pe.row_no,
       pe.column_no,
       m.ordinal,
       m.spouse_as_printed,
       m.spouse_name_hanja,
       m.spouse_bonkwan,
       m.spouse_father,
       m.relation,
       m.birth,
       m.death,
       m.certainty
FROM marriages m
JOIN people pe ON pe.id = m.person_id
JOIN pages pg ON pg.id = pe.source_page_id
JOIN sections s ON s.id = pg.section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_burials AS
SELECT s.code                          AS section_code,
       pg.printed_page_no,
       owner.row_no,
       owner.column_no,
       m.ordinal                       AS marriage_ordinal,
       b.burial_raw,
       b.location,
       b.orientation,
       b.note,
       b.certainty
FROM burials b
LEFT JOIN marriages m ON m.id = b.marriage_id
JOIN people owner ON owner.id = COALESCE(b.person_id, m.person_id)
JOIN pages pg ON pg.id = owner.source_page_id
JOIN sections s ON s.id = pg.section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_page_refs AS
SELECT s.code            AS section_code,
       pg.printed_page_no,
       pe.row_no,
       pe.column_no,
       r.raw_ref,
       r.direction,
       ts.code           AS target_section_code,
       r.target_page_no
FROM page_refs r
JOIN pages pg ON pg.id = r.source_page_id
JOIN sections s ON s.id = pg.section_id
LEFT JOIN people pe ON pe.id = r.source_person_id
JOIN sections ts ON ts.id = r.target_section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_relations AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       fp.row_no         AS from_row_no,
       fp.column_no      AS from_column_no,
       tp.row_no         AS to_row_no,
       tp.column_no      AS to_column_no,
       r.to_as_printed,
       r.relation_type
FROM relations r
JOIN pages pg ON pg.id = r.source_page_id
JOIN sections s ON s.id = pg.section_id
JOIN people fp ON fp.id = r.from_person_id
LEFT JOIN people tp ON tp.id = r.to_person_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_index_entries AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       i.name_hanja,
       i.name_hangul,
       ts.code AS target_section_code,
       i.target_page_no,
       i.raw_ref
FROM index_entries i
JOIN pages pg ON pg.id = i.page_id
JOIN sections s ON s.id = pg.section_id
LEFT JOIN sections ts ON ts.id = i.target_section_id
WHERE pg.review_status IN ('approved', 'published');

CREATE OR REPLACE VIEW public_page_texts AS
SELECT s.code AS section_code,
       pg.printed_page_no,
       t.kind,
       t.subkind,
       t.raw_text
FROM page_texts t
JOIN pages pg ON pg.id = t.page_id
JOIN sections s ON s.id = pg.section_id
WHERE pg.review_status IN ('approved', 'published');

INSERT INTO schema_migrations (version)
VALUES ('002_public_views')
ON CONFLICT (version) DO NOTHING;

COMMIT;
