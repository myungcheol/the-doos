-- Synthetic records exercise the DB contract used by the T019 importer.
DO $$
DECLARE a bigint; b bigint; c bigint; d bigint; first_fact bigint; second_fact bigint;
        reverse_fact bigint; other_fact bigint; marriage bigint; concubine bigint; location bigint;
        region bigint; run bigint; same_id bigint; old_edges bigint;
BEGIN
    INSERT INTO genealogy.persons(name_hanja) VALUES('婚姻檢證') RETURNING id INTO a;
    INSERT INTO genealogy.persons(name_unknown) VALUES(true) RETURNING id INTO b;
    INSERT INTO genealogy.persons(name_unknown) VALUES(true) RETURNING id INTO c;
    INSERT INTO genealogy.persons(name_hanja) VALUES('別人') RETURNING id INTO d;
    INSERT INTO genealogy.person_occurrences(person_id,original_image_id,left_px,top_px,right_px,bottom_px)
        SELECT a,id,100,100,140,180 FROM genealogy.page_images WHERE storage_path='scan/genealogy/001.jpg'
        RETURNING id INTO location;
    SELECT r.id INTO STRICT run FROM genealogy.ocr_runs r JOIN genealogy.page_images i ON i.id=r.image_id
        WHERE i.storage_path='scan/genealogy/001.jpg';
    INSERT INTO genealogy.ocr_regions(run_id,kind,reading_order,left_px,top_px,right_px,bottom_px,raw_text)
        VALUES(run,'text',20,60,100,90,300,'配金氏丙午卒妾李氏甲辰生') RETURNING id INTO region;
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,occurrence_id,kind,raw_text,origin)
        VALUES(b,a,location,'spouse_information','配金氏丙午卒','automatic') RETURNING id INTO first_fact;
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,occurrence_id,kind,raw_text,origin)
        VALUES(c,a,location,'spouse_information','妾李氏甲辰生','automatic') RETURNING id INTO second_fact;
    INSERT INTO genealogy.fact_sources(fact_id,region_id,char_start,char_end,source_order)
        VALUES(first_fact,region,0,6,0),(second_fact,region,6,12,0);
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,kind,raw_text,origin,year_text)
        VALUES(b,a,'death','丙午卒','automatic','丙午'),(c,a,'birth','甲辰生','automatic','甲辰');
    SELECT count(*) INTO old_edges FROM genealogy.parent_child;
    marriage=genealogy.ingest_marriage(a,b,'spouse',first_fact);
    concubine=genealogy.ingest_marriage(a,c,'concubine',second_fact);
    same_id=genealogy.ingest_marriage(a,b,'spouse',first_fact);
    IF same_id IS DISTINCT FROM marriage
       OR (SELECT count(*) FROM genealogy.marriages WHERE person_id=a)<>2
       OR EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='genealogy' AND table_name='marriages' AND column_name='wife_rank')
       OR (SELECT relation_type FROM genealogy.marriages WHERE id=concubine) IS DISTINCT FROM 'concubine'
       OR (SELECT count(*) FROM genealogy.parent_child)<>old_edges THEN
        RAISE EXCEPTION 'multiple/unknown spouses or idempotent import failed';
    END IF;
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,kind,raw_text,origin)
        VALUES(a,b,'spouse_information','配婚姻檢證','automatic') RETURNING id INTO reverse_fact;
    same_id=genealogy.ingest_marriage(b,a,'spouse',reverse_fact);
    IF same_id IS DISTINCT FROM marriage OR (SELECT count(*) FROM genealogy.marriage_sources WHERE marriage_id=marriage)<>2 THEN
        RAISE EXCEPTION 'reverse mention duplicated marriage';
    END IF;
    PERFORM genealogy.review_values('person',b,'{"name_unknown":false,"name_hanja":"校正配偶"}','reviewer','spouse name');
    IF NOT EXISTS (
        SELECT FROM genealogy.marriage_sources s
        JOIN genealogy.person_facts f ON f.id=s.fact_id
        JOIN genealogy.persons p ON p.id=f.subject_person_id
        WHERE s.marriage_id=marriage AND f.recorded_person_id=a AND f.raw_text='配金氏丙午卒' AND p.name_hanja='校正配偶'
    ) OR NOT EXISTS(SELECT FROM genealogy.person_facts WHERE subject_person_id=b AND kind='death' AND year_text='丙午') THEN
        RAISE EXCEPTION 'spouse edit lost description or life facts';
    END IF;
    PERFORM genealogy.review_marriage(marriage,'spouse','confirmed','reviewer','verified spouse');
    same_id=genealogy.ingest_marriage(a,b,'concubine',first_fact);
    IF (SELECT relation_type FROM genealogy.marriages WHERE id=marriage) IS DISTINCT FROM 'spouse' THEN
        RAISE EXCEPTION 'import overwrote reviewed marriage';
    END IF;
    BEGIN
        UPDATE genealogy.marriages SET relation_type='concubine' WHERE id=marriage;
        RAISE EXCEPTION 'unreviewed write accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='unreviewed write accepted' THEN RAISE; END IF;
    END;
    PERFORM genealogy.review_marriage(concubine,'concubine','rejected','reviewer','wrong spouse');
    same_id=genealogy.ingest_marriage(a,c,'spouse',second_fact);
    IF EXISTS(SELECT FROM genealogy.current_marriages WHERE id=concubine) THEN RAISE EXCEPTION 'rejected marriage resurrected'; END IF;
    PERFORM genealogy.exclude_record('person',b,'reviewer','false spouse detection');
    same_id=genealogy.ingest_marriage(a,b,'spouse',first_fact);
    IF EXISTS(SELECT FROM genealogy.current_marriages WHERE id=marriage) THEN RAISE EXCEPTION 'deleted spouse visible'; END IF;
    IF NOT EXISTS(SELECT FROM genealogy.marriage_sources WHERE marriage_id=marriage AND fact_id=first_fact)
       OR NOT EXISTS(SELECT FROM genealogy.review_history WHERE table_name='marriages' AND actor='reviewer' AND reason='verified spouse') THEN
        RAISE EXCEPTION 'evidence or audit lost';
    END IF;
    BEGIN
        UPDATE genealogy.person_facts SET subject_person_id=d WHERE id=first_fact;
        RAISE EXCEPTION 'linked source reassigned';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    INSERT INTO genealogy.person_facts(subject_person_id,recorded_person_id,kind,raw_text,origin)
        VALUES(d,a,'spouse_information','別人配偶','automatic') RETURNING id INTO other_fact;
    BEGIN
        PERFORM genealogy.ingest_marriage(a,b,'spouse',other_fact);
        RAISE EXCEPTION 'mismatched evidence accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM genealogy.ingest_marriage(a,a,'spouse',other_fact);
        RAISE EXCEPTION 'self marriage accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;
