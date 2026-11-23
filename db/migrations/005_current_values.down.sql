DROP VIEW genealogy.current_facts, genealogy.current_persons;
DROP TRIGGER protect_reviewed_value ON genealogy.persons;
DROP TRIGGER protect_reviewed_value ON genealogy.person_facts;
DROP FUNCTION genealogy.protect_reviewed_value();

-- Preserve current reviewed values when reverting to the 004 representation.
DO $$
DECLARE target text; destination text;
BEGIN
    FOR target,destination IN VALUES ('persons','person_manual_values'),('person_facts','fact_manual_values') LOOP
        EXECUTE format('CREATE TABLE genealogy.%I (LIKE genealogy.%I INCLUDING DEFAULTS INCLUDING CONSTRAINTS)',destination,target);
        EXECUTE format('ALTER TABLE genealogy.%I DROP COLUMN review_locked',destination);
        EXECUTE format('ALTER TABLE genealogy.%I ADD PRIMARY KEY(id)',destination);
        EXECUTE format('ALTER TABLE genealogy.%I ADD FOREIGN KEY(id) REFERENCES genealogy.%I',destination,target);
        EXECUTE format('INSERT INTO genealogy.%I SELECT (jsonb_populate_record(NULL::genealogy.%I,to_jsonb(t))).* FROM genealogy.%I t WHERE review_locked',destination,destination,target);
        EXECUTE format('CREATE TRIGGER capture_change AFTER INSERT OR UPDATE OR DELETE ON genealogy.%I FOR EACH ROW EXECUTE FUNCTION genealogy.capture_change()',destination);
    END LOOP;
END $$;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY(subject_person_id) REFERENCES genealogy.persons;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY(recorded_person_id) REFERENCES genealogy.persons;
ALTER TABLE genealogy.fact_manual_values ADD FOREIGN KEY(occurrence_id) REFERENCES genealogy.person_occurrences;
ALTER TABLE genealogy.persons DROP COLUMN review_locked;
ALTER TABLE genealogy.person_facts DROP COLUMN review_locked;
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


CREATE OR REPLACE FUNCTION genealogy.review_values(entity text, record bigint, patch jsonb, reviewer text, reason text)
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


CREATE OR REPLACE FUNCTION genealogy.ingest_person(occurrence bigint, proposed_name text)
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


DELETE FROM genealogy.schema_migrations WHERE version=5;
