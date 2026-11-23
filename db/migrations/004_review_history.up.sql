-- Full typed snapshots keep manual values independent of reprocessed values.
CREATE TABLE genealogy.person_manual_values
    (LIKE genealogy.persons INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
ALTER TABLE genealogy.person_manual_values ADD PRIMARY KEY (id);
ALTER TABLE genealogy.person_manual_values ADD FOREIGN KEY (id) REFERENCES genealogy.persons;
CREATE TABLE genealogy.fact_manual_values
    (LIKE genealogy.person_facts INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
ALTER TABLE genealogy.fact_manual_values ADD PRIMARY KEY (id);
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY (id) REFERENCES genealogy.person_facts;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY (subject_person_id) REFERENCES genealogy.persons;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY (recorded_person_id) REFERENCES genealogy.persons;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY (occurrence_id) REFERENCES genealogy.person_occurrences;

CREATE TABLE genealogy.person_exclusions (
    person_id bigint PRIMARY KEY REFERENCES genealogy.persons,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE genealogy.fact_exclusions (
    fact_id bigint PRIMARY KEY REFERENCES genealogy.person_facts,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE genealogy.review_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name text NOT NULL,
    record_id bigint NOT NULL,
    operation text NOT NULL,
    before_value jsonb,
    after_value jsonb,
    actor text NOT NULL,
    reason text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX review_history_record_idx ON genealogy.review_history (table_name, record_id, id);

CREATE FUNCTION genealogy.capture_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; next_value jsonb; key bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN previous = to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN next_value = to_jsonb(NEW); END IF;
    IF previous IS NOT DISTINCT FROM next_value THEN RETURN NULL; END IF;
    key = COALESCE(next_value->>'id', previous->>'id',
                   next_value->>'person_id', previous->>'person_id',
                   next_value->>'fact_id', previous->>'fact_id')::bigint;
    INSERT INTO genealogy.review_history
        (table_name,record_id,operation,before_value,after_value,actor,reason)
    VALUES (TG_TABLE_NAME,key,TG_OP,previous,next_value,
            COALESCE(NULLIF(current_setting('genealogy.actor',true),''),'automatic'),
            COALESCE(current_setting('genealogy.reason',true),''));
    RETURN NULL;
END $$;

DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['persons','person_facts','person_occurrences','person_readings',
            'parent_child','person_manual_values','fact_manual_values','person_exclusions','fact_exclusions']
    LOOP
        EXECUTE format('CREATE TRIGGER capture_change AFTER INSERT OR UPDATE OR DELETE ON genealogy.%I
                        FOR EACH ROW EXECUTE FUNCTION genealogy.capture_change()',target);
    END LOOP;
END $$;
CREATE TRIGGER immutable_review_history BEFORE UPDATE OR DELETE ON genealogy.review_history
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['persons','person_facts','person_occurrences','person_readings','parent_child']
    LOOP
        EXECUTE format('CREATE TRIGGER prevent_physical_delete BEFORE DELETE ON genealogy.%I
                        FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change()',target);
    END LOOP;
END $$;

CREATE VIEW genealogy.current_persons AS
SELECT (jsonb_populate_record(NULL::genealogy.persons,COALESCE(to_jsonb(m),to_jsonb(p)))).* FROM genealogy.persons p
LEFT JOIN genealogy.person_manual_values m ON m.id=p.id
WHERE NOT EXISTS (SELECT FROM genealogy.person_exclusions x WHERE x.person_id=p.id)
  AND COALESCE(m.review_status,p.review_status) <> 'rejected';

CREATE VIEW genealogy.current_facts AS
SELECT (jsonb_populate_record(NULL::genealogy.person_facts,COALESCE(to_jsonb(m),to_jsonb(f)))).* FROM genealogy.person_facts f
LEFT JOIN genealogy.fact_manual_values m ON m.id=f.id
WHERE NOT EXISTS (SELECT FROM genealogy.fact_exclusions x WHERE x.fact_id=f.id)
  AND COALESCE(m.review_status,f.review_status) <> 'rejected'
  AND EXISTS (SELECT FROM genealogy.current_persons p
              WHERE p.id=COALESCE(m.recorded_person_id,f.recorded_person_id))
  AND (CASE WHEN m.id IS NOT NULL THEN m.subject_person_id ELSE f.subject_person_id END IS NULL OR
       EXISTS (SELECT FROM genealogy.current_persons p
               WHERE p.id=CASE WHEN m.id IS NOT NULL THEN m.subject_person_id ELSE f.subject_person_id END));

-- Typed snapshot merge. NULL in a patch explicitly clears a field.
CREATE FUNCTION genealogy.review_values(entity text, record bigint, patch jsonb, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE base_table text; manual_table text; allowed text[]; field text; snapshot jsonb;
BEGIN
    IF btrim(reviewer) = '' OR reviewer IS NULL OR btrim(reason) = '' OR reason IS NULL THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    IF jsonb_typeof(patch) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'patch must be an object'; END IF;
    IF entity='person' THEN
        base_table='persons'; manual_table='person_manual_values';
        allowed=ARRAY['name_hanja','name_unknown','review_status'];
    ELSIF entity='fact' THEN
        base_table='person_facts'; manual_table='fact_manual_values';
        allowed=ARRAY['subject_person_id','recorded_person_id','occurrence_id','kind','review_status',
            'explanation_manual','year_text','month_text','day_text','year_number','month','day','calendar',
            'leap_month','gregorian_year','normalized_month','normalized_day','month_assumed','day_assumed',
            'conversion_status','date_details'];
    ELSE RAISE EXCEPTION 'unsupported review entity'; END IF;
    FOR field IN SELECT jsonb_object_keys(patch) LOOP
        IF NOT field=ANY(allowed) THEN RAISE EXCEPTION 'field not editable: %',field; END IF;
    END LOOP;
    -- Lock the stable base ID to serialize concurrent reviews of this record.
    EXECUTE format('SELECT to_jsonb(t) FROM genealogy.%I t WHERE id=$1 FOR UPDATE',base_table)
        INTO snapshot USING record;
    IF snapshot IS NULL THEN RAISE EXCEPTION 'record not found'; END IF;
    EXECUTE format('SELECT COALESCE((SELECT to_jsonb(m) FROM genealogy.%I m WHERE id=$1),$2)',manual_table)
        INTO snapshot USING record,snapshot;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    EXECUTE format('DELETE FROM genealogy.%I WHERE id=$1',manual_table) USING record;
    EXECUTE format('INSERT INTO genealogy.%I SELECT (jsonb_populate_record(NULL::genealogy.%I,$1)).*',
                   manual_table,manual_table) USING snapshot || patch;
    PERFORM set_config('genealogy.actor','',true);
    PERFORM set_config('genealogy.reason','',true);
END $$;

CREATE FUNCTION genealogy.exclude_record(entity text, record bigint, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF btrim(reviewer) = '' OR reviewer IS NULL OR btrim(reason) = '' OR reason IS NULL THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    IF entity='person' THEN
        INSERT INTO genealogy.person_exclusions(person_id,reason) VALUES(record,reason)
            ON CONFLICT(person_id) DO UPDATE SET reason=EXCLUDED.reason;
    ELSIF entity='fact' THEN
        INSERT INTO genealogy.fact_exclusions(fact_id,reason) VALUES(record,reason)
            ON CONFLICT(fact_id) DO UPDATE SET reason=EXCLUDED.reason;
    ELSE RAISE EXCEPTION 'unsupported exclusion entity'; END IF;
    PERFORM set_config('genealogy.actor','',true);
    PERFORM set_config('genealogy.reason','',true);
END $$;

CREATE OR REPLACE FUNCTION genealogy.parents_of(person bigint)
RETURNS TABLE (person_id bigint, relation_id bigint, review_status text)
LANGUAGE sql STABLE AS $$
    SELECT e.parent_id,e.id,e.review_status FROM genealogy.parent_child e
    JOIN genealogy.current_persons p ON p.id=e.parent_id
    JOIN genealogy.current_persons c ON c.id=e.child_id
    WHERE e.child_id=$1 AND e.in_lineage AND e.review_status<>'rejected' ORDER BY e.parent_id
$$;
CREATE OR REPLACE FUNCTION genealogy.children_of(person bigint)
RETURNS TABLE (person_id bigint, relation_id bigint, review_status text)
LANGUAGE sql STABLE AS $$
    SELECT e.child_id,e.id,e.review_status FROM genealogy.parent_child e
    JOIN genealogy.current_persons p ON p.id=e.parent_id
    JOIN genealogy.current_persons c ON c.id=e.child_id
    WHERE e.parent_id=$1 AND e.in_lineage AND e.review_status<>'rejected' ORDER BY e.child_id
$$;
INSERT INTO genealogy.schema_migrations(version,description) VALUES(4,'review_history');

-- Importers reuse the physical occurrence ID even when a person is excluded.
CREATE FUNCTION genealogy.ingest_person(occurrence bigint, proposed_name text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE identity bigint;
BEGIN
    PERFORM 1 FROM genealogy.person_occurrences WHERE id=occurrence FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'occurrence not found'; END IF;
    SELECT person_id INTO identity FROM genealogy.person_occurrences WHERE id=occurrence;
    IF identity IS NULL THEN
        INSERT INTO genealogy.persons(name_hanja,name_unknown)
            VALUES(proposed_name,proposed_name IS NULL) RETURNING id INTO identity;
        UPDATE genealogy.person_occurrences SET person_id=identity WHERE id=occurrence;
    ELSE
        UPDATE genealogy.persons SET name_hanja=proposed_name,name_unknown=proposed_name IS NULL
        WHERE id=identity AND review_status<>'rejected'
          AND NOT EXISTS (SELECT FROM genealogy.person_exclusions WHERE person_id=identity);
    END IF;
    RETURN identity;
END $$;

ALTER TABLE genealogy.parent_child ADD COLUMN review_locked boolean NOT NULL DEFAULT false;
CREATE FUNCTION genealogy.protect_reviewed_relation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.review_locked AND COALESCE(current_setting('genealogy.actor',true),'')='' THEN
        RAISE EXCEPTION 'reviewed relation requires an explicit review';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER protect_reviewed_relation BEFORE UPDATE ON genealogy.parent_child
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_reviewed_relation();
CREATE FUNCTION genealogy.review_relation(record bigint, status text, traverse boolean, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF btrim(reviewer)='' OR reviewer IS NULL OR btrim(reason)='' OR reason IS NULL THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    UPDATE genealogy.parent_child SET review_status=status,in_lineage=traverse,review_locked=true WHERE id=record;
    IF NOT FOUND THEN RAISE EXCEPTION 'relation not found'; END IF;
    PERFORM set_config('genealogy.actor','',true);
    PERFORM set_config('genealogy.reason','',true);
END $$;
