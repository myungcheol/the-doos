-- Synthetic data only; never load this into the application database.
DO $$
DECLARE p1 bigint; p2 bigint; missing bigint; img1 bigint; img2 bigint; rotated bigint;
        r1 bigint; r2 bigint; r3 bigint; g1 bigint; g2 bigint; g3 bigint;
        a bigint; homonym bigint; spouse bigint; occ bigint; fact bigint; extra bigint;
        v float8; vy float8; recovered_y float8; n integer;
BEGIN
    INSERT INTO genealogy.pages (section,page_key,sort_order,scan_status)
        VALUES ('genealogy','001',1,'available') RETURNING id INTO p1;
    INSERT INTO genealogy.pages (section,page_key,sort_order,scan_status)
        VALUES ('genealogy','002',2,'available') RETURNING id INTO p2;
    INSERT INTO genealogy.pages (section,page_key,sort_order,scan_status)
        VALUES ('genealogy','053',53,'missing') RETURNING id INTO missing;
    INSERT INTO genealogy.page_images (page_id,variant,storage_path,sha256,width,height)
        VALUES (p1,'original','scan/genealogy/001.jpg',repeat('a',64),688,948) RETURNING id INTO img1;
    INSERT INTO genealogy.page_images (page_id,variant,storage_path,sha256,width,height)
        VALUES (p2,'original','scan/genealogy/002.jpg',repeat('b',64),700,948) RETURNING id INTO img2;
    -- Synthetic rotation plus translation; map both axes back without rounding.
    INSERT INTO genealogy.page_images (page_id,variant,original_image_id,storage_path,sha256,width,height,
                                      forward_matrix,inverse_matrix,rotation_degrees)
        VALUES (p1,'deskewed',img1,'data/ocr/deskew/fixture.png',repeat('c',64),700,960,
                ARRAY[0.8,-0.6,4,0.6,0.8,6],ARRAY[0.8,0.6,-6.8,-0.6,0.8,-2.4],36.86989765) RETURNING id INTO rotated;
    SELECT forward_matrix[1]*20.25+forward_matrix[2]*30.5+forward_matrix[3] INTO v
        FROM genealogy.page_images WHERE id=rotated;
    SELECT forward_matrix[4]*20.25+forward_matrix[5]*30.5+forward_matrix[6] INTO vy
        FROM genealogy.page_images WHERE id=rotated;
    SELECT inverse_matrix[4]*v+inverse_matrix[5]*vy+inverse_matrix[6] INTO recovered_y
        FROM genealogy.page_images WHERE id=rotated;
    SELECT inverse_matrix[1]*v+inverse_matrix[2]*vy+inverse_matrix[3] INTO v
        FROM genealogy.page_images WHERE id=rotated;
    IF abs(v-20.25)>0.000001 OR abs(recovered_y-30.5)>0.000001 THEN
        RAISE EXCEPTION 'coordinate round trip failed';
    END IF;
    INSERT INTO genealogy.ocr_runs (image_id,status,engine_version,model_version,language,device,code_version)
        VALUES (img1,'running','3','PP-OCRv5','chinese_cht','cpu','fixture') RETURNING id INTO r1;
    INSERT INTO genealogy.ocr_runs (image_id,status,engine_version,model_version,language,device,code_version)
        VALUES (rotated,'running','3','PP-OCRv5','chinese_cht','cpu','fixture') RETURNING id INTO r2;
    INSERT INTO genealogy.ocr_runs (image_id,status,engine_version,model_version,language,device,code_version)
        VALUES (img2,'running','3','PP-OCRv5','chinese_cht','cpu','fixture') RETURNING id INTO r3;
    INSERT INTO genealogy.ocr_regions (run_id,kind,reading_order,left_px,top_px,right_px,bottom_px,raw_text,polygon)
        VALUES (r1,'text',0,10,20,40,100,'甲辰二月生','[[10,20],[40,20],[40,100],[10,100]]') RETURNING id INTO g1;
    INSERT INTO genealogy.ocr_regions (run_id,kind,reading_order,left_px,top_px,right_px,bottom_px,raw_text)
        VALUES (r2,'text',0,14,26,44,106,'甲辰二月生') RETURNING id INTO g2;
    INSERT INTO genealogy.ocr_regions (run_id,kind,reading_order,left_px,top_px,right_px,bottom_px,raw_text)
        VALUES (r3,'text',0,10,20,40,100,'景吉') RETURNING id INTO g3;
    INSERT INTO genealogy.persons (name_hanja) VALUES ('景吉') RETURNING id INTO a;
    INSERT INTO genealogy.persons (name_hanja) VALUES ('景吉') RETURNING id INTO homonym;
    INSERT INTO genealogy.persons (name_unknown) VALUES (true) RETURNING id INTO spouse;
    INSERT INTO genealogy.person_occurrences (person_id,original_image_id,left_px,top_px,right_px,bottom_px)
        VALUES (a,img1,10,20,40,100) RETURNING id INTO occ;
    INSERT INTO genealogy.occurrence_sources VALUES (occ,g1),(occ,g2);
    INSERT INTO genealogy.person_occurrences (person_id,original_image_id,left_px,top_px,right_px,bottom_px)
        VALUES (a,img2,10,20,40,100);
    INSERT INTO genealogy.person_readings (person_id,name_hanja_snapshot,reading,status,origin,source,source_version)
        VALUES (a,'景吉','경길','candidate','automatic','local_table','fixture'),
               (a,'景吉','경길','confirmed','manual','reviewer','fixture');
    INSERT INTO genealogy.person_facts (subject_person_id,recorded_person_id,occurrence_id,kind,raw_text,origin,
        year_text,month_text,month,gregorian_year,normalized_month,normalized_day,day_assumed,
        explanation_automatic,explanation_manual)
        VALUES (a,a,occ,'birth','甲辰二月生','automatic','甲辰','二月',2,1964,2,1,true,
                '甲辰 2월 (일 미상) 태어남.','검수자 풀이') RETURNING id INTO fact;
    INSERT INTO genealogy.fact_sources VALUES (fact,g1,0,2,0),(fact,g1,2,5,1);
    SELECT count(*) INTO n FROM genealogy.fact_sources WHERE fact_id=fact;
    IF n <> 2 THEN RAISE EXCEPTION 'source ranges not preserved'; END IF;
    INSERT INTO genealogy.ocr_regions (run_id,kind,reading_order,left_px,top_px,right_px,bottom_px,raw_text)
        VALUES (r1,'text',1,50,20,65,100,'一般記事') RETURNING id INTO extra;
    INSERT INTO genealogy.fact_sources VALUES (fact,extra,0,4,2);
    IF (SELECT count(DISTINCT region_id) FROM genealogy.fact_sources WHERE fact_id=fact) <> 2 THEN
        RAISE EXCEPTION 'multiple source regions not preserved';
    END IF;
    -- A's description contains B's own death fact, without copying B's identity.
    INSERT INTO genealogy.person_facts (subject_person_id,recorded_person_id,kind,raw_text,origin)
        VALUES (spouse,a,'death','丙午卒','automatic');
    -- Actual Jan 1, assumed Jan 1, lunar Feb 30, and unresolved year.
    INSERT INTO genealogy.person_facts (recorded_person_id,kind,raw_text,origin,year_text,month_text,day_text,
        month,day,calendar,gregorian_year,normalized_month,normalized_day,month_assumed,day_assumed)
        VALUES (a,'birth','一九六五年一月一日生','automatic','一九六五年','一月','一日',1,1,'solar',1965,1,1,false,false),
               (a,'birth','一九六五年生','automatic','一九六五年',NULL,NULL,NULL,NULL,'unknown',1965,1,1,true,true),
               (a,'death','甲辰二月三十日卒','automatic','甲辰','二月','三十日',2,30,'lunar',NULL,NULL,NULL,false,false);
    SELECT count(*) INTO n FROM genealogy.person_occurrences WHERE person_id=a;
    IF n <> 2 OR a=homonym THEN RAISE EXCEPTION 'person identity/occurrence failure'; END IF;
    IF (SELECT explanation_manual FROM genealogy.person_facts WHERE id=fact) <> '검수자 풀이' THEN
        RAISE EXCEPTION 'manual explanation lost';
    END IF;
    -- Invalid inserts must fail rather than silently corrupt evidence.
    BEGIN
        INSERT INTO genealogy.fact_sources VALUES (fact,g1,0,99,2);
        RAISE EXCEPTION 'accepted invalid source range';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'accepted invalid source range' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO genealogy.occurrence_sources VALUES (occ,g3);
        RAISE EXCEPTION 'accepted cross-page source';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'accepted cross-page source' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO genealogy.ocr_regions (run_id,parent_region_id,kind,reading_order,left_px,top_px,right_px,bottom_px)
            VALUES (r2,g1,'column',2,0,0,20,20);
        RAISE EXCEPTION 'accepted cross-run parent';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'accepted cross-run parent' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO genealogy.person_facts (recorded_person_id,kind,raw_text,origin,month_assumed)
            VALUES (a,'birth','fixture','automatic',true);
        RAISE EXCEPTION 'accepted missing assumed value';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO genealogy.ocr_regions (run_id,kind,reading_order,left_px,top_px,right_px,bottom_px)
            VALUES (r1,'band',3,0,0,9999,20);
        RAISE EXCEPTION 'accepted out of bounds';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'accepted out of bounds' THEN RAISE; END IF;
    END;
    BEGIN
        UPDATE genealogy.ocr_regions SET raw_text='changed' WHERE id=g1;
        RAISE EXCEPTION 'accepted source overwrite';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'accepted source overwrite' THEN RAISE; END IF;
    END;
END $$;
