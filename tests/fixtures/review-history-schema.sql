DO $$
DECLARE a bigint; c bigint; d bigint; location bigint; fact bigint; relation bigint; result bigint;
BEGIN
    SELECT id,occurrence INTO a,location FROM family WHERE label='A';
    SELECT id INTO c FROM family WHERE label='C';
    SELECT id INTO d FROM family WHERE label='D';
    PERFORM genealogy.review_values('person',a,'{"name_hanja":"校正名"}','reviewer','name correction');
    result=genealogy.ingest_person(location,'再判讀');
    IF result<>a OR (SELECT name_hanja FROM genealogy.current_persons WHERE id=a)<>'校正名'
       OR (SELECT name_hanja FROM genealogy.persons WHERE id=a)<>'校正名' THEN
        RAISE EXCEPTION 'manual name lost after reprocessing';
    END IF;
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,kind,raw_text,origin)
        VALUES(a,a,'birth','甲辰生','automatic') RETURNING id INTO fact;
    PERFORM genealogy.review_values('fact',fact,'{"explanation_manual":"수동 풀이","year_text":"乙巳"}','reviewer','date correction');
    BEGIN
        UPDATE genealogy.person_facts SET explanation_automatic='new automatic',year_text='丙午' WHERE id=fact;
        RAISE EXCEPTION 'reviewed fact overwritten';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='reviewed fact overwritten' THEN RAISE; END IF;
    END;
    IF (SELECT explanation_manual FROM genealogy.current_facts WHERE id=fact)<>'수동 풀이'
       OR (SELECT year_text FROM genealogy.current_facts WHERE id=fact)<>'乙巳' THEN
        RAISE EXCEPTION 'manual fact lost';
    END IF;
    PERFORM genealogy.exclude_record('fact',fact,'reviewer','false fact');
    IF EXISTS(SELECT FROM genealogy.current_facts WHERE id=fact) THEN RAISE EXCEPTION 'excluded fact visible'; END IF;
    PERFORM genealogy.exclude_record('person',c,'reviewer','false person');
    SELECT occurrence INTO location FROM family WHERE label='C';
    result=genealogy.ingest_person(location,'新名稱');
    IF result<>c OR EXISTS(SELECT FROM genealogy.current_persons WHERE id=c)
       OR EXISTS(SELECT FROM genealogy.children_of(a) WHERE person_id=c)
       OR EXISTS(SELECT FROM genealogy.parents_of(c)) THEN
        RAISE EXCEPTION 'excluded person resurrected';
    END IF;
    PERFORM genealogy.review_values('person',d,'{"review_status":"rejected"}','reviewer','false person');
    IF EXISTS(SELECT FROM genealogy.children_of(a) WHERE person_id=d) THEN RAISE EXCEPTION 'rejected person visible'; END IF;
    SELECT id INTO relation FROM genealogy.parent_child WHERE parent_id=a AND child_id=d;
    PERFORM genealogy.review_relation(relation,'rejected',false,'reviewer','false relation');
    BEGIN
        UPDATE genealogy.parent_child SET review_status='pending' WHERE id=relation;
        RAISE EXCEPTION 'reviewed relation overwritten';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='reviewed relation overwritten' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM genealogy.review_values('person',a,'{"name_hanja":null}','reviewer','invalid');
        RAISE EXCEPTION 'invalid manual record accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    IF NOT EXISTS (SELECT FROM genealogy.review_history WHERE actor='reviewer' AND reason='name correction')
       OR NOT EXISTS (SELECT FROM genealogy.review_history WHERE table_name='persons' AND actor='automatic')
       OR NOT EXISTS (SELECT FROM genealogy.parent_child WHERE id=relation)
       OR (SELECT name_hanja FROM genealogy.current_persons WHERE id=a)<>'校正名' THEN
        RAISE EXCEPTION 'history or original references lost';
    END IF;
    IF NOT EXISTS(SELECT FROM genealogy.review_history
        WHERE table_name='persons' AND record_id=a AND actor='reviewer'
          AND before_value->>'name_hanja'='A' AND after_value->>'name_hanja'='校正名')
       OR NOT EXISTS(SELECT FROM genealogy.persons WHERE name_hanja='移行後' AND review_locked)
       OR NOT EXISTS(SELECT FROM genealogy.person_facts WHERE raw_text='__005_transition__' AND year_text='乙巳' AND review_locked)
       OR to_regclass('genealogy.person_manual_values') IS NOT NULL
       OR to_regclass('genealogy.fact_manual_values') IS NOT NULL THEN
        RAISE EXCEPTION 'single current value migration failed';
    END IF;
    PERFORM genealogy.review_values('fact',fact,'{"explanation_manual":"두 번째 검수"}','reviewer','second edit');
    IF (SELECT explanation_manual FROM genealogy.person_facts WHERE id=fact)<>'두 번째 검수' THEN
        RAISE EXCEPTION 'subsequent review failed';
    END IF;
    BEGIN
        UPDATE genealogy.review_history SET actor='changed' WHERE actor='reviewer';
        RAISE EXCEPTION 'history modified';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='history modified' THEN RAISE; END IF;
    END;
    BEGIN
        DELETE FROM genealogy.persons WHERE id=c;
        RAISE EXCEPTION 'physical delete allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='physical delete allowed' THEN RAISE; END IF;
    END;
END $$;
