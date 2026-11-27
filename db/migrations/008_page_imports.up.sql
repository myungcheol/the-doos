-- The first accepted extraction owns the page's genealogy records. A changed
-- extraction remains independently inspectable until its identities are reconciled.
CREATE TABLE genealogy.page_imports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id bigint NOT NULL REFERENCES genealogy.pages,
    run_id bigint NOT NULL REFERENCES genealogy.ocr_runs,
    artifact_hash text NOT NULL,
    projection_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('applied','equivalent','needs_review')),
    extraction jsonb NOT NULL,
    UNIQUE (page_id, artifact_hash, projection_hash)
);
CREATE UNIQUE INDEX page_import_baseline ON genealogy.page_imports(page_id) WHERE status='applied';
CREATE TABLE genealogy.import_occurrences (
    import_id bigint NOT NULL REFERENCES genealogy.page_imports,
    candidate_index integer NOT NULL,
    occurrence_id bigint NOT NULL REFERENCES genealogy.person_occurrences,
    PRIMARY KEY (import_id,candidate_index)
);
CREATE TABLE genealogy.page_reference_candidates (
    import_id bigint NOT NULL REFERENCES genealogy.page_imports,
    region_id bigint NOT NULL REFERENCES genealogy.ocr_regions,
    source_occurrence_id bigint REFERENCES genealogy.person_occurrences,
    target_page_key text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('up','down')),
    status text NOT NULL CHECK (status IN ('unprocessed','scan_missing')),
    direction_uncertain boolean NOT NULL,
    PRIMARY KEY (import_id,region_id)
);
INSERT INTO genealogy.schema_migrations(version,description) VALUES (8,'page_imports');
