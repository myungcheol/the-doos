DROP FUNCTION genealogy.children_of(bigint), genealogy.parents_of(bigint);
DROP TABLE genealogy.parent_child;
DROP FUNCTION genealogy.check_lineage_cycle(), genealogy.serialize_lineage_edit();
DROP TABLE genealogy.lineage_write_guard;
ALTER TABLE genealogy.person_occurrences DROP CONSTRAINT occurrence_person_key;
DELETE FROM genealogy.schema_migrations WHERE version = 3;
