CREATE TABLE genealogy.ocr_batches (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    deskew boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE genealogy.ocr_batch_items (
    batch_id bigint NOT NULL REFERENCES genealogy.ocr_batches,
    position integer NOT NULL,
    scan_path text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','succeeded','failed')),
    attempts integer NOT NULL DEFAULT 0,
    started_at timestamptz,
    finished_at timestamptz,
    import_id bigint REFERENCES genealogy.page_imports,
    replay boolean,
    error text,
    PRIMARY KEY (batch_id,position),
    UNIQUE (batch_id,scan_path)
);
INSERT INTO genealogy.schema_migrations(version,description) VALUES (9,'ocr_batches');
