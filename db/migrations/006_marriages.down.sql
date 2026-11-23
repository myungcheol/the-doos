DROP FUNCTION genealogy.review_marriage(bigint,text,text,text,text,text);
DROP FUNCTION genealogy.ingest_marriage(bigint,bigint,text,bigint);
DROP VIEW genealogy.current_marriages;
DROP TRIGGER protect_marriage_fact ON genealogy.person_facts;
DROP TABLE genealogy.marriage_sources;
DROP FUNCTION genealogy.check_marriage_source();
DROP TABLE genealogy.marriages;
DROP FUNCTION genealogy.protect_marriage_evidence();
DELETE FROM genealogy.schema_migrations WHERE version=6;
