DROP VIEW genealogy.current_facts;
DROP VIEW genealogy.current_persons;
ALTER TABLE genealogy.persons ADD COLUMN review_locked boolean NOT NULL DEFAULT false;
ALTER TABLE genealogy.person_facts ADD COLUMN review_locked boolean NOT NULL DEFAULT false;

-- Transfer previously reviewed snapshots before removing the overlay tables.
-- The existing audit triggers retain the values being replaced.
DO $$
DECLARE target text; source text; assignments text;
BEGIN
    PERFORM set_config('genealogy.actor','migration-005',true);
    PERFORM set_config('genealogy.reason','consolidate current values',true);
    FOR target,source IN VALUES ('persons','person_manual_values'),('person_facts','fact_manual_values') LOOP
        SELECT string_agg(format('%I=m.%I',column_name,column_name),',')
        INTO assignments FROM information_schema.columns
        WHERE table_schema='genealogy' AND table_name=source AND column_name<>'id';
        EXECUTE format('UPDATE genealogy.%I t SET %s, review_locked=true FROM genealogy.%I m WHERE t.id=m.id',
                       target,assignments,source);
    END LOOP;
    PERFORM set_config('genealogy.actor','',true);
    PERFORM set_config('genealogy.reason','',true);
END $$;
DROP TABLE genealogy.person_manual_values, genealogy.fact_manual_values;

CREATE VIEW genealogy.current_persons AS
SELECT p.* FROM genealogy.persons p
WHERE p.review_status<>'rejected'
  AND NOT EXISTS(SELECT FROM genealogy.person_exclusions x WHERE x.person_id=p.id);
CREATE VIEW genealogy.current_facts AS
SELECT f.* FROM genealogy.person_facts f
WHERE f.review_status<>'rejected'
  AND NOT EXISTS(SELECT FROM genealogy.fact_exclusions x WHERE x.fact_id=f.id)
  AND EXISTS(SELECT FROM genealogy.current_persons p WHERE p.id=f.recorded_person_id)
  AND (f.subject_person_id IS NULL OR EXISTS(SELECT FROM genealogy.current_persons p WHERE p.id=f.subject_person_id));

CREATE FUNCTION genealogy.protect_reviewed_value() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (OLD.review_locked OR NEW.review_locked)
       AND COALESCE(current_setting('genealogy.actor',true),'')='' THEN
        RAISE EXCEPTION 'reviewed value requires an explicit review';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER protect_reviewed_value BEFORE UPDATE ON genealogy.persons
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_reviewed_value();
CREATE TRIGGER protect_reviewed_value BEFORE UPDATE ON genealogy.person_facts
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_reviewed_value();

CREATE OR REPLACE FUNCTION genealogy.review_values(entity text, record bigint, patch jsonb, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE target text; allowed text[]; field text; assignments text;
        previous_actor text := COALESCE(current_setting('genealogy.actor',true),'');
        previous_reason text := COALESCE(current_setting('genealogy.reason',true),'');
        affected bigint;
BEGIN
    IF reviewer IS NULL OR btrim(reviewer)='' OR reason IS NULL OR btrim(reason)='' THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    IF jsonb_typeof(patch) IS DISTINCT FROM 'object' OR patch='{}'::jsonb THEN
        RAISE EXCEPTION 'patch must be a nonempty object';
    END IF;
    IF entity='person' THEN
        target='persons';
        allowed=ARRAY['name_hanja','name_unknown','review_status'];
    ELSIF entity='fact' THEN
        target='person_facts';
        allowed=ARRAY['subject_person_id','recorded_person_id','occurrence_id','kind','review_status',
            'explanation_manual','year_text','month_text','day_text','year_number','month','day','calendar',
            'leap_month','gregorian_year','normalized_month','normalized_day','month_assumed','day_assumed',
            'conversion_status','date_details'];
    ELSE RAISE EXCEPTION 'unsupported review entity'; END IF;
    FOR field IN SELECT jsonb_object_keys(patch) LOOP
        IF NOT field=ANY(allowed) THEN RAISE EXCEPTION 'field not editable: %',field; END IF;
    END LOOP;
    SELECT string_agg(format('%I=(jsonb_populate_record(NULL::genealogy.%I,$1)).%I',key,target,key),',')
        INTO assignments FROM jsonb_object_keys(patch) key;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    EXECUTE format('UPDATE genealogy.%I SET %s, review_locked=true WHERE id=$2',target,assignments)
        USING patch,record;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected=0 THEN RAISE EXCEPTION 'record not found'; END IF;
    PERFORM set_config('genealogy.actor',previous_actor,true);
    PERFORM set_config('genealogy.reason',previous_reason,true);
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
        WHERE id=identity AND NOT review_locked AND review_status<>'rejected'
          AND NOT EXISTS(SELECT FROM genealogy.person_exclusions WHERE person_id=identity);
    END IF;
    RETURN identity;
END $$;
INSERT INTO genealogy.schema_migrations(version,description) VALUES(5,'current_values');
