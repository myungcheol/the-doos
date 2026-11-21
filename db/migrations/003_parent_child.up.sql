-- Each cited occurrence must belong to the person at that end of the edge.
ALTER TABLE genealogy.person_occurrences
    ADD CONSTRAINT occurrence_person_key UNIQUE (id, person_id);

CREATE TABLE genealogy.parent_child (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id bigint NOT NULL REFERENCES genealogy.persons,
    child_id bigint NOT NULL REFERENCES genealogy.persons,
    parent_occurrence_id bigint NOT NULL,
    child_occurrence_id bigint NOT NULL,
    relation_type text NOT NULL DEFAULT 'unspecified'
        CHECK (relation_type IN ('unspecified','birth','adoptive')),
    method text NOT NULL CHECK (btrim(method) <> ''),
    evidence jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(evidence) = 'object'),
    review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','confirmed','rejected')),
    in_lineage boolean NOT NULL DEFAULT true,
    UNIQUE (parent_id, child_id),
    CHECK (parent_id <> child_id),
    FOREIGN KEY (parent_occurrence_id, parent_id)
        REFERENCES genealogy.person_occurrences (id, person_id),
    FOREIGN KEY (child_occurrence_id, child_id)
        REFERENCES genealogy.person_occurrences (id, person_id)
);
CREATE INDEX parent_child_by_child ON genealogy.parent_child (child_id, parent_id);

-- Serialize graph edits. Updating the same row also makes competing writers
-- under REPEATABLE READ fail with a serialization error instead of using stale data.
CREATE TABLE genealogy.lineage_write_guard (
    singleton boolean PRIMARY KEY CHECK (singleton),
    token boolean NOT NULL
);
INSERT INTO genealogy.lineage_write_guard VALUES (true, false);
CREATE FUNCTION genealogy.serialize_lineage_edit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE genealogy.lineage_write_guard SET token = NOT token WHERE singleton;
    IF NOT FOUND THEN RAISE EXCEPTION 'missing lineage write guard'; END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER serialize_lineage_edit BEFORE INSERT OR UPDATE ON genealogy.parent_child
    FOR EACH STATEMENT EXECUTE FUNCTION genealogy.serialize_lineage_edit();

CREATE FUNCTION genealogy.check_lineage_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE descendants(person_id) AS (
            SELECT NEW.child_id
            UNION
            SELECT e.child_id FROM genealogy.parent_child e
            JOIN descendants d ON e.parent_id = d.person_id
            WHERE e.review_status <> 'rejected'
        )
        SELECT 1 FROM descendants WHERE person_id = NEW.parent_id
    ) THEN
        RAISE EXCEPTION 'parent-child cycle' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER check_lineage_cycle AFTER INSERT OR UPDATE ON genealogy.parent_child
    FOR EACH ROW WHEN (NEW.review_status <> 'rejected')
    EXECUTE FUNCTION genealogy.check_lineage_cycle();

CREATE FUNCTION genealogy.parents_of(person bigint)
RETURNS TABLE (person_id bigint, relation_id bigint, review_status text)
LANGUAGE sql STABLE AS $$
    SELECT parent_id, id, review_status FROM genealogy.parent_child
    WHERE child_id = $1 AND in_lineage AND review_status <> 'rejected'
    ORDER BY parent_id
$$;
CREATE FUNCTION genealogy.children_of(person bigint)
RETURNS TABLE (person_id bigint, relation_id bigint, review_status text)
LANGUAGE sql STABLE AS $$
    SELECT child_id, id, review_status FROM genealogy.parent_child
    WHERE parent_id = $1 AND in_lineage AND review_status <> 'rejected'
    ORDER BY child_id
$$;
INSERT INTO genealogy.schema_migrations (version, description) VALUES (3,'parent_child');
