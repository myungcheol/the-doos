-- Application-owned schema. Version 1; migrations must be explicit.
CREATE SCHEMA IF NOT EXISTS jokbo;
CREATE TABLE IF NOT EXISTS jokbo.schema_version (
    version integer PRIMARY KEY CHECK (version = 1)
);
INSERT INTO jokbo.schema_version VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS jokbo.editions (
    id text PRIMARY KEY,
    meta jsonb NOT NULL,
    import_digest text,
    revision bigint NOT NULL DEFAULT 0,
    state jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS jokbo.assets (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    path text NOT NULL UNIQUE,
    size bigint NOT NULL CHECK (size >= 0)
);
CREATE TABLE IF NOT EXISTS jokbo.pages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    edition_id text NOT NULL REFERENCES jokbo.editions,
    name text NOT NULL,
    UNIQUE (edition_id, name)
);
CREATE TABLE IF NOT EXISTS jokbo.ocr_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id bigint NOT NULL REFERENCES jokbo.pages,
    digest text NOT NULL,
    raw jsonb NOT NULL,
    scan_id text REFERENCES jokbo.assets,
    roi_id text REFERENCES jokbo.assets,
    active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (page_id, digest)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON jokbo.ocr_runs(page_id) WHERE active;
CREATE TABLE IF NOT EXISTS jokbo.persons (
    id text PRIMARY KEY CHECK (id ~ '^PER_[0-9A-Fa-f]{32}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jokbo.occurrences (
    id text PRIMARY KEY,
    edition_id text NOT NULL REFERENCES jokbo.editions,
    page_id bigint NOT NULL REFERENCES jokbo.pages,
    run_id bigint NOT NULL REFERENCES jokbo.ocr_runs,
    person_id text NOT NULL REFERENCES jokbo.persons,
    local_id text NOT NULL,
    name text,
    status text NOT NULL CHECK (status IN ('needs_review', 'confirmed', 'rejected')),
    source jsonb NOT NULL,
    raw jsonb NOT NULL,
    reviewed jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS occurrence_person ON jokbo.occurrences(person_id);
CREATE INDEX IF NOT EXISTS occurrence_name ON jokbo.occurrences(name);
CREATE INDEX IF NOT EXISTS occurrence_edition ON jokbo.occurrences(edition_id);
CREATE TABLE IF NOT EXISTS jokbo.parent_child (
    edition_id text NOT NULL REFERENCES jokbo.editions,
    id text NOT NULL,
    parent_id text NOT NULL REFERENCES jokbo.persons,
    child_id text NOT NULL REFERENCES jokbo.persons,
    kind text NOT NULL DEFAULT 'unspecified' CHECK (kind IN ('unspecified', 'biological', 'adoptive')),
    status text NOT NULL CHECK (status IN ('needs_review', 'confirmed', 'rejected')),
    evidence jsonb NOT NULL,
    PRIMARY KEY (edition_id, id),
    UNIQUE (edition_id, parent_id, child_id, kind),
    CHECK (parent_id <> child_id)
);
CREATE INDEX IF NOT EXISTS lineage_parent ON jokbo.parent_child(parent_id, kind, child_id) WHERE status = 'confirmed';
CREATE INDEX IF NOT EXISTS lineage_child ON jokbo.parent_child(child_id, kind, parent_id) WHERE status = 'confirmed';
CREATE TABLE IF NOT EXISTS jokbo.partners (
    edition_id text NOT NULL REFERENCES jokbo.editions,
    id text NOT NULL,
    person_id text NOT NULL REFERENCES jokbo.persons,
    partner_id text REFERENCES jokbo.persons,
    kind text NOT NULL CHECK (kind IN ('wife', 'concubine', 'husband', 'other')),
    status text NOT NULL CHECK (status IN ('needs_review', 'confirmed', 'rejected')),
    record jsonb NOT NULL,
    PRIMARY KEY (edition_id, id),
    CHECK (person_id <> partner_id)
);
CREATE INDEX IF NOT EXISTS partner_person ON jokbo.partners(person_id);
CREATE INDEX IF NOT EXISTS partner_target ON jokbo.partners(partner_id);
CREATE UNIQUE INDEX IF NOT EXISTS partner_pair ON jokbo.partners
    (edition_id, LEAST(person_id, partner_id), GREATEST(person_id, partner_id), kind)
    WHERE partner_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS jokbo.reviews (
    edition_id text NOT NULL REFERENCES jokbo.editions,
    revision bigint NOT NULL,
    state jsonb NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (edition_id, revision)
);

-- The application takes this same lock before replacing an edition's edges.
CREATE OR REPLACE FUNCTION jokbo.check_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(1987, 1);
    IF NEW.status = 'confirmed' AND EXISTS (
        WITH RECURSIVE descendants(id) AS (
            SELECT NEW.child_id
            UNION
            SELECT e.child_id FROM jokbo.parent_child e JOIN descendants d ON e.parent_id = d.id
            WHERE e.status = 'confirmed'
              AND (e.edition_id, e.id) <> (NEW.edition_id, NEW.id)
        ) SELECT 1 FROM descendants WHERE id = NEW.parent_id
    ) THEN
        RAISE EXCEPTION 'confirmed lineage cycle' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS lineage_cycle ON jokbo.parent_child;
CREATE TRIGGER lineage_cycle BEFORE INSERT OR UPDATE ON jokbo.parent_child
    FOR EACH ROW EXECUTE FUNCTION jokbo.check_lineage();
