DROP TABLE genealogy.fact_sources;
DROP TABLE genealogy.person_facts;
DROP TABLE genealogy.person_readings;
DROP TABLE genealogy.occurrence_sources;
DROP TABLE genealogy.person_occurrences;
DROP FUNCTION genealogy.check_person_source();
DROP TABLE genealogy.persons;
DELETE FROM genealogy.schema_migrations WHERE version = 2;
