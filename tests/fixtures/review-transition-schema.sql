-- Applied under 004 to verify that 005 preserves existing manual values.
DO $$
DECLARE person bigint; fact bigint;
BEGIN
    INSERT INTO genealogy.persons(name_hanja) VALUES('移行前') RETURNING id INTO person;
    INSERT INTO genealogy.person_facts(recorded_person_id,subject_person_id,kind,raw_text,origin,year_text)
        VALUES(person,person,'birth','__005_transition__','automatic','甲辰') RETURNING id INTO fact;
    PERFORM genealogy.review_values('person',person,'{"name_hanja":"移行後"}','reviewer','transition name');
    PERFORM genealogy.review_values('fact',fact,'{"year_text":"乙巳"}','reviewer','transition fact');
END $$;
