-- Run through psql with ON_ERROR_STOP and --single-transaction.
CREATE SCHEMA genealogy;
CREATE TABLE genealogy.schema_migrations (
    version integer PRIMARY KEY,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO genealogy.schema_migrations VALUES (1, 'page_ocr_schema', now());

CREATE TABLE genealogy.pages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section text NOT NULL CHECK (section IN ('cover', 'frontmatter', 'genealogy')),
    page_key text NOT NULL,
    sort_order integer NOT NULL UNIQUE CHECK (sort_order >= 0),
    scan_status text NOT NULL CHECK (scan_status IN ('available', 'missing')),
    UNIQUE (section, page_key)
);

CREATE TABLE genealogy.page_images (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id bigint NOT NULL REFERENCES genealogy.pages,
    variant text NOT NULL CHECK (variant IN ('original', 'deskewed')),
    original_image_id bigint,
    storage_path text NOT NULL UNIQUE,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    rotation_degrees double precision,
    -- Row-major 2x3 affine matrices, original -> image and image -> original.
    forward_matrix double precision[] NOT NULL DEFAULT ARRAY[1,0,0,0,1,0]::double precision[],
    inverse_matrix double precision[] NOT NULL DEFAULT ARRAY[1,0,0,0,1,0]::double precision[],
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, page_id),
    UNIQUE (id, variant),
    CHECK (array_ndims(forward_matrix) = 1 AND cardinality(forward_matrix) = 6),
    CHECK (array_ndims(inverse_matrix) = 1 AND cardinality(inverse_matrix) = 6),
    CHECK ((variant = 'original' AND original_image_id IS NULL) OR
           (variant = 'deskewed' AND original_image_id IS NOT NULL AND original_image_id <> id)),
    FOREIGN KEY (original_image_id, page_id) REFERENCES genealogy.page_images (id, page_id)
);
CREATE UNIQUE INDEX one_original_per_page ON genealogy.page_images (page_id) WHERE variant = 'original';

CREATE FUNCTION genealogy.check_image() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT scan_status FROM genealogy.pages WHERE id = NEW.page_id) <> 'available' THEN
        RAISE EXCEPTION 'missing scan cannot have an image';
    END IF;
    IF NEW.variant = 'deskewed' AND NOT EXISTS (
        SELECT 1 FROM genealogy.page_images WHERE id = NEW.original_image_id AND variant = 'original'
    ) THEN
        RAISE EXCEPTION 'deskewed image must reference the original';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_image BEFORE INSERT OR UPDATE ON genealogy.page_images
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_image();

CREATE TABLE genealogy.ocr_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    image_id bigint NOT NULL REFERENCES genealogy.page_images,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    engine text NOT NULL DEFAULT 'PaddleOCR',
    engine_version text NOT NULL,
    model_version text NOT NULL,
    language text NOT NULL,
    device text NOT NULL,
    code_version text NOT NULL,
    configuration jsonb NOT NULL DEFAULT '{}',
    environment jsonb NOT NULL DEFAULT '{}',
    raw_result jsonb,
    error_message text,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((status = 'running' AND finished_at IS NULL) OR
           (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL))
);
CREATE INDEX ocr_runs_image_idx ON genealogy.ocr_runs (image_id);

CREATE TABLE genealogy.ocr_regions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES genealogy.ocr_runs,
    parent_region_id bigint,
    kind text NOT NULL CHECK (kind IN ('band', 'column', 'text')),
    reading_order integer NOT NULL CHECK (reading_order >= 0),
    left_px double precision NOT NULL,
    top_px double precision NOT NULL,
    right_px double precision NOT NULL,
    bottom_px double precision NOT NULL,
    polygon jsonb,
    raw_text text,
    confidence double precision CHECK (confidence BETWEEN 0 AND 1),
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE (id, run_id),
    CHECK (parent_region_id IS NULL OR parent_region_id <> id),
    FOREIGN KEY (parent_region_id, run_id) REFERENCES genealogy.ocr_regions (id, run_id),
    CHECK (left_px >= 0 AND top_px >= 0 AND right_px > left_px AND bottom_px > top_px),
    CHECK (kind <> 'text' OR raw_text IS NOT NULL)
);
CREATE INDEX ocr_regions_run_idx ON genealogy.ocr_regions (run_id, reading_order);
CREATE INDEX ocr_regions_parent_idx ON genealogy.ocr_regions (parent_region_id);

CREATE FUNCTION genealogy.check_region() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE img genealogy.page_images; point jsonb;
BEGIN
    SELECT i.* INTO STRICT img FROM genealogy.page_images i
        JOIN genealogy.ocr_runs r ON r.image_id = i.id WHERE r.id = NEW.run_id;
    IF NEW.right_px > img.width OR NEW.bottom_px > img.height THEN
        RAISE EXCEPTION 'region exceeds image bounds';
    END IF;
    IF NEW.parent_region_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM genealogy.ocr_regions p WHERE p.id = NEW.parent_region_id
          AND p.run_id = NEW.run_id
          AND ((NEW.kind = 'column' AND p.kind = 'band') OR
               (NEW.kind = 'text' AND p.kind IN ('band', 'column')))
    ) THEN
        RAISE EXCEPTION 'invalid region hierarchy or cross-run parent';
    END IF;
    IF NEW.polygon IS NOT NULL THEN
        IF jsonb_typeof(NEW.polygon) <> 'array' OR jsonb_array_length(NEW.polygon) <> 4 THEN
            RAISE EXCEPTION 'polygon must contain four points';
        END IF;
        FOR point IN SELECT value FROM jsonb_array_elements(NEW.polygon) LOOP
            IF jsonb_typeof(point) <> 'array' OR jsonb_array_length(point) <> 2 OR
               jsonb_typeof(point->0) <> 'number' OR jsonb_typeof(point->1) <> 'number' THEN
                RAISE EXCEPTION 'invalid polygon point';
            END IF;
            IF (point->>0)::float8 < NEW.left_px OR (point->>0)::float8 > NEW.right_px OR
               (point->>1)::float8 < NEW.top_px OR (point->>1)::float8 > NEW.bottom_px THEN
                RAISE EXCEPTION 'polygon point exceeds bounding box';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_region BEFORE INSERT OR UPDATE ON genealogy.ocr_regions
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_region();

-- Preserve immutable source images and OCR output; manual edits live elsewhere.
CREATE FUNCTION genealogy.reject_source_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'source evidence is immutable; create a new record';
END $$;
CREATE TRIGGER immutable_image BEFORE UPDATE OR DELETE ON genealogy.page_images
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();
CREATE TRIGGER immutable_region BEFORE UPDATE OR DELETE ON genealogy.ocr_regions
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();
CREATE TRIGGER immutable_run_image BEFORE UPDATE OF image_id ON genealogy.ocr_runs
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();
