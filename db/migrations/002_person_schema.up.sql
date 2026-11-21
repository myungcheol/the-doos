CREATE TABLE genealogy.persons (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_hanja text,
    name_unknown boolean NOT NULL DEFAULT false,
    review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'confirmed', 'rejected')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((name_unknown AND name_hanja IS NULL) OR
           (NOT name_unknown AND name_hanja IS NOT NULL AND length(btrim(name_hanja)) > 0))
);
CREATE INDEX persons_name_idx ON genealogy.persons (name_hanja);

-- One physical occurrence on the ORIGINAL image, independent of OCR runs.
CREATE TABLE genealogy.person_occurrences (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id bigint REFERENCES genealogy.persons,
    original_image_id bigint NOT NULL,
    image_variant text NOT NULL DEFAULT 'original' CHECK (image_variant = 'original'),
    FOREIGN KEY (original_image_id, image_variant) REFERENCES genealogy.page_images (id, variant),
    left_px double precision NOT NULL,
    top_px double precision NOT NULL,
    right_px double precision NOT NULL,
    bottom_px double precision NOT NULL,
    marker_raw text,
    female_entry_status text NOT NULL DEFAULT 'not_applicable'
        CHECK (female_entry_status IN ('not_applicable', 'unresolved', 'daughter', 'son_in_law')),
    review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'confirmed', 'rejected')),
    CHECK (left_px >= 0 AND top_px >= 0 AND right_px > left_px AND bottom_px > top_px)
);
CREATE INDEX occurrences_person_idx ON genealogy.person_occurrences (person_id);
CREATE INDEX occurrences_image_idx ON genealogy.person_occurrences (original_image_id);

-- Several runs can support the same physical occurrence; never dedupe by name.
CREATE TABLE genealogy.occurrence_sources (
    occurrence_id bigint NOT NULL REFERENCES genealogy.person_occurrences,
    region_id bigint NOT NULL REFERENCES genealogy.ocr_regions,
    PRIMARY KEY (occurrence_id, region_id)
);
CREATE INDEX occurrence_sources_region_idx ON genealogy.occurrence_sources (region_id);

CREATE TABLE genealogy.person_readings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id bigint NOT NULL REFERENCES genealogy.persons,
    name_hanja_snapshot text NOT NULL,
    reading text NOT NULL CHECK (length(btrim(reading)) > 0),
    status text NOT NULL CHECK (status IN ('candidate', 'confirmed', 'rejected')),
    origin text NOT NULL CHECK (origin IN ('automatic', 'manual')),
    source text NOT NULL,
    source_version text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX readings_person_idx ON genealogy.person_readings (person_id);
CREATE UNIQUE INDEX one_confirmed_reading ON genealogy.person_readings (person_id) WHERE status = 'confirmed';

CREATE TABLE genealogy.person_facts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_person_id bigint REFERENCES genealogy.persons,
    recorded_person_id bigint NOT NULL REFERENCES genealogy.persons,
    occurrence_id bigint REFERENCES genealogy.person_occurrences,
    kind text NOT NULL CHECK (kind IN ('birth', 'death', 'burial_date', 'burial_note',
        'office', 'education', 'spouse_information', 'general_information', 'unclassified',
        'ambiguous_event', 'date_unspecified')),
    raw_text text NOT NULL,
    origin text NOT NULL CHECK (origin IN ('automatic', 'manual')),
    review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'confirmed', 'rejected')),
    explanation_automatic text,
    explanation_manual text,
    parser_version text,
    -- Components as actually read; NULL means unknown, not a default of 1.
    year_text text,
    month_text text,
    day_text text,
    year_number integer,
    month integer CHECK (month BETWEEN 1 AND 12),
    day integer CHECK (day BETWEEN 1 AND 31 AND (calendar <> 'lunar' OR day <= 30)),
    calendar text NOT NULL DEFAULT 'unknown' CHECK (calendar IN ('unknown', 'lunar', 'solar')),
    leap_month boolean,
    gregorian_year integer CHECK (gregorian_year BETWEEN 1 AND 9999),
    normalized_month integer CHECK (normalized_month BETWEEN 1 AND 12),
    normalized_day integer CHECK (normalized_day BETWEEN 1 AND 31),
    month_assumed boolean NOT NULL DEFAULT false,
    day_assumed boolean NOT NULL DEFAULT false,
    conversion_status text NOT NULL DEFAULT 'not_attempted'
        CHECK (conversion_status IN ('not_attempted', 'resolved', 'ambiguous', 'unresolved', 'conflict')),
    date_details jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT month_assumed OR (month IS NULL AND month_text IS NULL AND normalized_month IS NOT NULL AND normalized_month = 1)),
    CHECK (NOT day_assumed OR (day IS NULL AND day_text IS NULL AND normalized_day IS NOT NULL AND normalized_day = 1)),
    CHECK (normalized_month IS NULL OR (month IS NOT NULL AND normalized_month = month) OR month_assumed),
    CHECK (normalized_day IS NULL OR (day IS NOT NULL AND normalized_day = day) OR day_assumed)
);
CREATE INDEX facts_subject_idx ON genealogy.person_facts (subject_person_id, kind);
CREATE INDEX facts_recorded_idx ON genealogy.person_facts (recorded_person_id);
CREATE INDEX facts_occurrence_idx ON genealogy.person_facts (occurrence_id);

-- Character ranges are zero-based Unicode code points [start,end).
CREATE TABLE genealogy.fact_sources (
    fact_id bigint NOT NULL REFERENCES genealogy.person_facts,
    region_id bigint NOT NULL REFERENCES genealogy.ocr_regions,
    char_start integer NOT NULL CHECK (char_start >= 0),
    char_end integer NOT NULL CHECK (char_end > char_start),
    source_order integer NOT NULL CHECK (source_order >= 0),
    PRIMARY KEY (fact_id, region_id, char_start, char_end),
    UNIQUE (fact_id, source_order)
);
CREATE INDEX fact_sources_region_idx ON genealogy.fact_sources (region_id);

CREATE FUNCTION genealogy.check_person_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE img genealogy.page_images; occurrence_image bigint; source_page bigint;
BEGIN
    IF TG_TABLE_NAME = 'person_occurrences' THEN
        SELECT * INTO STRICT img FROM genealogy.page_images WHERE id = NEW.original_image_id;
        IF NEW.right_px > img.width OR NEW.bottom_px > img.height THEN
            RAISE EXCEPTION 'occurrence exceeds original image bounds';
        END IF;
    ELSE
        IF TG_TABLE_NAME = 'fact_sources' THEN
            IF NOT EXISTS (SELECT 1 FROM genealogy.ocr_regions WHERE id = NEW.region_id
                           AND raw_text IS NOT NULL AND NEW.char_end <= char_length(raw_text)) THEN
                RAISE EXCEPTION 'fact source range exceeds OCR text';
            END IF;
            SELECT o.original_image_id INTO occurrence_image FROM genealogy.person_facts f
                JOIN genealogy.person_occurrences o ON o.id = f.occurrence_id WHERE f.id = NEW.fact_id;
        ELSE
            SELECT original_image_id INTO occurrence_image FROM genealogy.person_occurrences WHERE id = NEW.occurrence_id;
        END IF;
        SELECT i.page_id INTO source_page FROM genealogy.ocr_regions g
            JOIN genealogy.ocr_runs r ON r.id = g.run_id
            JOIN genealogy.page_images i ON i.id = r.image_id WHERE g.id = NEW.region_id;
        IF occurrence_image IS NOT NULL AND source_page IS DISTINCT FROM
            (SELECT page_id FROM genealogy.page_images WHERE id = occurrence_image) THEN
            RAISE EXCEPTION 'source and occurrence must belong to the same page';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_occurrence BEFORE INSERT OR UPDATE ON genealogy.person_occurrences
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_person_source();
CREATE TRIGGER check_occurrence_source BEFORE INSERT OR UPDATE ON genealogy.occurrence_sources
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_person_source();
CREATE TRIGGER check_fact_source BEFORE INSERT OR UPDATE ON genealogy.fact_sources
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_person_source();
INSERT INTO genealogy.schema_migrations (version, description) VALUES (2, 'person_schema');
