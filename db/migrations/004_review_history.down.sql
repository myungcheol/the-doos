DROP FUNCTION genealogy.review_relation(bigint,text,boolean,text,text);
DROP TRIGGER protect_reviewed_relation ON genealogy.parent_child;
DROP FUNCTION genealogy.protect_reviewed_relation();
ALTER TABLE genealogy.parent_child DROP COLUMN review_locked;
DROP FUNCTION genealogy.ingest_person(bigint,text);
DROP FUNCTION genealogy.exclude_record(text,bigint,text,text);
DROP FUNCTION genealogy.review_values(text,bigint,jsonb,text,text);
-- Restore 003 query behavior before dropping the views it references.
CREATE OR REPLACE FUNCTION genealogy.parents_of(person bigint)
RETURNS TABLE(person_id bigint,relation_id bigint,review_status text)
LANGUAGE sql STABLE AS $$
    SELECT parent_id,id,review_status FROM genealogy.parent_child
    WHERE child_id=$1 AND in_lineage AND review_status<>'rejected' ORDER BY parent_id
$$;
CREATE OR REPLACE FUNCTION genealogy.children_of(person bigint)
RETURNS TABLE(person_id bigint,relation_id bigint,review_status text)
LANGUAGE sql STABLE AS $$
    SELECT child_id,id,review_status FROM genealogy.parent_child
    WHERE parent_id=$1 AND in_lineage AND review_status<>'rejected' ORDER BY child_id
$$;
DROP VIEW genealogy.current_facts, genealogy.current_persons;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['persons','person_facts','person_occurrences','person_readings',
            'parent_child','person_manual_values','fact_manual_values','person_exclusions','fact_exclusions']
    LOOP
        EXECUTE format('DROP TRIGGER capture_change ON genealogy.%I',target);
    END LOOP;
END $$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['persons','person_facts','person_occurrences','person_readings','parent_child']
    LOOP
        EXECUTE format('DROP TRIGGER prevent_physical_delete ON genealogy.%I',target);
    END LOOP;
END $$;
DROP TABLE genealogy.person_manual_values, genealogy.fact_manual_values,
    genealogy.person_exclusions, genealogy.fact_exclusions, genealogy.review_history;
DROP FUNCTION genealogy.capture_change();
DELETE FROM genealogy.schema_migrations WHERE version=4;
