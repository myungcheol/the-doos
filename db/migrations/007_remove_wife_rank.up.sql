DROP FUNCTION genealogy.review_marriage(bigint,text,text,text,text,text);
DROP VIEW genealogy.current_marriages;
ALTER TABLE genealogy.marriages DROP COLUMN wife_rank;
CREATE VIEW genealogy.current_marriages AS
SELECT m.* FROM genealogy.marriages m
JOIN genealogy.current_persons a ON a.id=m.person_id
JOIN genealogy.current_persons b ON b.id=m.spouse_id
WHERE m.review_status<>'rejected';

CREATE FUNCTION genealogy.review_marriage(record bigint, kind text, status text, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE previous_actor text := COALESCE(current_setting('genealogy.actor',true),'');
        previous_reason text := COALESCE(current_setting('genealogy.reason',true),'');
BEGIN
    IF reviewer IS NULL OR btrim(reviewer)='' OR reason IS NULL OR btrim(reason)='' THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    UPDATE genealogy.marriages SET relation_type=kind,review_status=status,review_locked=true
        WHERE id=record;
    IF NOT FOUND THEN RAISE EXCEPTION 'marriage not found'; END IF;
    PERFORM set_config('genealogy.actor',previous_actor,true);
    PERFORM set_config('genealogy.reason',previous_reason,true);
END $$;
INSERT INTO genealogy.schema_migrations(version,description) VALUES(7,'remove redundant wife rank');
