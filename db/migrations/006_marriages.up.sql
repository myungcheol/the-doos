CREATE TABLE genealogy.marriages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id bigint NOT NULL REFERENCES genealogy.persons,
    spouse_id bigint NOT NULL REFERENCES genealogy.persons,
    relation_type text NOT NULL CHECK (relation_type IN ('spouse','concubine')),
    -- Rank always describes spouse_id. 配 alone leaves this NULL.
    wife_rank text CHECK (wife_rank = 'principal'),
    review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','confirmed','rejected')),
    review_locked boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (person_id<>spouse_id),
    CHECK (relation_type<>'concubine' OR wife_rank IS NULL)
);
CREATE UNIQUE INDEX marriages_pair_key ON genealogy.marriages
    (LEAST(person_id,spouse_id),GREATEST(person_id,spouse_id));
CREATE INDEX marriages_person_idx ON genealogy.marriages(person_id);
CREATE INDEX marriages_spouse_idx ON genealogy.marriages(spouse_id);

-- A description can support one marriage; a marriage can have many descriptions.
-- The fact's recorded_person_id identifies the owner of the description and
-- subject_person_id identifies the independently stored spouse.
CREATE TABLE genealogy.marriage_sources (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    marriage_id bigint NOT NULL REFERENCES genealogy.marriages,
    fact_id bigint NOT NULL UNIQUE REFERENCES genealogy.person_facts
);
CREATE INDEX marriage_sources_marriage_idx ON genealogy.marriage_sources(marriage_id);

CREATE FUNCTION genealogy.check_marriage_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM genealogy.marriages m JOIN genealogy.person_facts f ON f.id=NEW.fact_id
        WHERE m.id=NEW.marriage_id AND f.kind='spouse_information'
          AND ((f.recorded_person_id=m.person_id AND f.subject_person_id=m.spouse_id)
            OR (f.recorded_person_id=m.spouse_id AND f.subject_person_id=m.person_id))
    ) THEN
        RAISE EXCEPTION 'marriage source must describe these two people' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_marriage_source BEFORE INSERT OR UPDATE ON genealogy.marriage_sources
    FOR EACH ROW EXECUTE FUNCTION genealogy.check_marriage_source();

CREATE FUNCTION genealogy.protect_marriage_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME='marriages' THEN
        IF NEW.person_id IS DISTINCT FROM OLD.person_id OR NEW.spouse_id IS DISTINCT FROM OLD.spouse_id THEN
            RAISE EXCEPTION 'marriage participants are stable; reject the edge and create a corrected edge';
        END IF;
    ELSIF EXISTS (
        SELECT FROM genealogy.marriage_sources s JOIN genealogy.marriages m ON m.id=s.marriage_id
        WHERE s.fact_id=NEW.id AND
            (NEW.kind<>'spouse_information' OR NEW.subject_person_id IS NULL OR
             NOT ((NEW.recorded_person_id=m.person_id AND NEW.subject_person_id=m.spouse_id)
                OR (NEW.recorded_person_id=m.spouse_id AND NEW.subject_person_id=m.person_id)))
    ) THEN
        RAISE EXCEPTION 'fact correction would invalidate marriage evidence' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER protect_marriage_participants BEFORE UPDATE ON genealogy.marriages
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_marriage_evidence();
CREATE TRIGGER protect_marriage_fact BEFORE UPDATE OF kind,subject_person_id,recorded_person_id ON genealogy.person_facts
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_marriage_evidence();
CREATE TRIGGER protect_reviewed_marriage BEFORE UPDATE ON genealogy.marriages
    FOR EACH ROW EXECUTE FUNCTION genealogy.protect_reviewed_value();

CREATE TRIGGER capture_change AFTER INSERT OR UPDATE OR DELETE ON genealogy.marriages
    FOR EACH ROW EXECUTE FUNCTION genealogy.capture_change();
CREATE TRIGGER capture_change AFTER INSERT OR UPDATE OR DELETE ON genealogy.marriage_sources
    FOR EACH ROW EXECUTE FUNCTION genealogy.capture_change();
CREATE TRIGGER prevent_physical_delete BEFORE DELETE ON genealogy.marriages
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();
CREATE TRIGGER prevent_physical_delete BEFORE DELETE ON genealogy.marriage_sources
    FOR EACH ROW EXECUTE FUNCTION genealogy.reject_source_change();

CREATE VIEW genealogy.current_marriages AS
SELECT m.* FROM genealogy.marriages m
JOIN genealogy.current_persons a ON a.id=m.person_id
JOIN genealogy.current_persons b ON b.id=m.spouse_id
WHERE m.review_status<>'rejected';

CREATE FUNCTION genealogy.ingest_marriage(owner bigint, spouse bigint, kind text, source_fact bigint)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE result bigint; existing genealogy.marriages;
BEGIN
    IF kind IS NULL OR kind NOT IN ('spouse','concubine') THEN
        RAISE EXCEPTION 'invalid marriage type' USING ERRCODE='23514';
    END IF;
    INSERT INTO genealogy.marriages(person_id,spouse_id,relation_type)
    VALUES(owner,spouse,kind)
    ON CONFLICT (LEAST(person_id,spouse_id),GREATEST(person_id,spouse_id)) DO NOTHING
    RETURNING id INTO result;
    IF result IS NULL THEN
        SELECT * INTO STRICT existing FROM genealogy.marriages
        WHERE LEAST(person_id,spouse_id)=LEAST(owner,spouse)
          AND GREATEST(person_id,spouse_id)=GREATEST(owner,spouse) FOR UPDATE;
        result=existing.id;
        -- A reverse mention must not change which person is designated concubine.
        IF NOT existing.review_locked AND existing.review_status<>'rejected'
           AND existing.person_id=owner AND existing.relation_type IS DISTINCT FROM kind THEN
            UPDATE genealogy.marriages SET relation_type=kind WHERE id=result;
        END IF;
    END IF;
    INSERT INTO genealogy.marriage_sources(marriage_id,fact_id) VALUES(result,source_fact)
        ON CONFLICT(fact_id) DO NOTHING;
    IF NOT EXISTS(SELECT FROM genealogy.marriage_sources WHERE fact_id=source_fact AND marriage_id=result) THEN
        RAISE EXCEPTION 'source already belongs to another marriage' USING ERRCODE='23514';
    END IF;
    RETURN result;
END $$;

CREATE FUNCTION genealogy.review_marriage(record bigint, kind text, rank text, status text, reviewer text, reason text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE previous_actor text := COALESCE(current_setting('genealogy.actor',true),'');
        previous_reason text := COALESCE(current_setting('genealogy.reason',true),'');
BEGIN
    IF reviewer IS NULL OR btrim(reviewer)='' OR reason IS NULL OR btrim(reason)='' THEN
        RAISE EXCEPTION 'reviewer and reason required';
    END IF;
    PERFORM set_config('genealogy.actor',reviewer,true);
    PERFORM set_config('genealogy.reason',reason,true);
    UPDATE genealogy.marriages SET relation_type=kind,wife_rank=rank,review_status=status,review_locked=true
        WHERE id=record;
    IF NOT FOUND THEN RAISE EXCEPTION 'marriage not found'; END IF;
    PERFORM set_config('genealogy.actor',previous_actor,true);
    PERFORM set_config('genealogy.reason',previous_reason,true);
END $$;
INSERT INTO genealogy.schema_migrations(version,description) VALUES(6,'marriages');
