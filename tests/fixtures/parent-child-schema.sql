-- Runs after page-person-schema.sql in the disposable verification DB.
CREATE TEMP TABLE family AS
WITH people AS (
    INSERT INTO genealogy.persons (name_hanja)
    SELECT unnest(ARRAY['A','C','D','E','F','G']) RETURNING id, name_hanja
), locations AS (
    INSERT INTO genealogy.person_occurrences
        (person_id, original_image_id, left_px, top_px, right_px, bottom_px, female_entry_status)
    SELECT p.id, i.id, 5, 5, 50, 100,
           CASE WHEN p.name_hanja='D' THEN 'daughter' ELSE 'not_applicable' END
    FROM people p CROSS JOIN genealogy.page_images i WHERE i.storage_path='scan/genealogy/001.jpg'
    RETURNING id, person_id
)
SELECT p.name_hanja AS label, p.id, o.id AS occurrence FROM people p JOIN locations o ON o.person_id=p.id;

INSERT INTO genealogy.parent_child
    (parent_id,child_id,parent_occurrence_id,child_occurrence_id,method,relation_type,in_lineage,review_status)
SELECT p.id,c.id,p.occurrence,c.occurrence,'fixture',v.kind,v.traverse,v.status
FROM (VALUES ('A','C','unspecified',true,'confirmed'), ('A','D','unspecified',true,'pending'),
             ('D','E','adoptive',true,'confirmed'), ('F','E','birth',false,'confirmed'),
             ('C','G','unspecified',true,'rejected')) v(parent,child,kind,traverse,status)
JOIN family p ON p.label=v.parent JOIN family c ON c.label=v.child;

DO $$
DECLARE a family; c family; d family; e family; g family;
BEGIN
    SELECT * INTO STRICT a FROM family WHERE label='A';
    SELECT * INTO STRICT c FROM family WHERE label='C';
    SELECT * INTO STRICT d FROM family WHERE label='D';
    SELECT * INTO STRICT e FROM family WHERE label='E';
    SELECT * INTO STRICT g FROM family WHERE label='G';
    IF (SELECT array_agg(f.label ORDER BY f.label) FROM genealogy.children_of(a.id) edge
        JOIN family f ON f.id=edge.person_id) IS DISTINCT FROM ARRAY['C','D']
       OR (SELECT array_agg(person_id) FROM genealogy.children_of(d.id)) IS DISTINCT FROM ARRAY[e.id]
       OR (SELECT array_agg(person_id) FROM genealogy.parents_of(e.id)) IS DISTINCT FROM ARRAY[d.id]
       OR (SELECT review_status FROM genealogy.parents_of(d.id)) IS DISTINCT FROM 'pending'
       OR EXISTS (SELECT FROM genealogy.parents_of(g.id))
       OR EXISTS (SELECT FROM genealogy.parents_of(a.id)) THEN
        RAISE EXCEPTION 'incorrect one-step lookup';
    END IF;
    BEGIN
        INSERT INTO genealogy.parent_child(parent_id,child_id,parent_occurrence_id,child_occurrence_id,method)
        VALUES (a.id,a.id,a.occurrence,a.occurrence,'self');
        RAISE EXCEPTION 'accepted self-parent';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO genealogy.parent_child(parent_id,child_id,parent_occurrence_id,child_occurrence_id,method)
        VALUES (e.id,a.id,e.occurrence,a.occurrence,'cycle');
        RAISE EXCEPTION 'accepted A-D-E-A cycle';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE genealogy.parent_child SET parent_id=e.id,parent_occurrence_id=e.occurrence,
            child_id=a.id,child_occurrence_id=a.occurrence,review_status='confirmed'
            WHERE child_id=g.id;
        RAISE EXCEPTION 'accepted cycle on review';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE genealogy.parent_child SET parent_occurrence_id=c.occurrence WHERE parent_id=a.id;
        RAISE EXCEPTION 'accepted mismatched occurrence';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;
