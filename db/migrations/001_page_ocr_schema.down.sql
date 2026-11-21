-- Deliberately no CASCADE: later migrations must be rolled back first.
DROP TABLE genealogy.ocr_regions;
DROP FUNCTION genealogy.check_region();
DROP TABLE genealogy.ocr_runs;
DROP TABLE genealogy.page_images;
DROP FUNCTION genealogy.reject_source_change();
DROP FUNCTION genealogy.check_image();
DROP TABLE genealogy.pages;
DROP TABLE genealogy.schema_migrations;
DROP SCHEMA genealogy;
