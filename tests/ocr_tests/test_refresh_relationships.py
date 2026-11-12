"""Saved-page relationship refresh must not alter evidence or review state."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ocr.refresh_relationships import refresh_page, refreshed_relationships
from ocr.storage import save_page_result
from tests.ocr_tests.test_relationship_layout import person, row


class RefreshRelationshipsTests(unittest.TestCase):
    def page(self):
        return {"source_image": "scan/003.jpg", "table_roi": {"x": 0, "width": 600},
                "rows": [row("r1", 1, [person("father", 400, 0, "甲")]),
                         row("r2", 2, [person("son", 400, 100, "子乙"), person("daughter", 300, 100, "女丙")])],
                "people_candidates": [{"person_id": "father", "source_page": "003.jpg", "person_uid": "PER_FIXED"}],
                "relationship_candidates": [{"relationship_id": "R0001", "parent_candidate_id": "wrong",
                                             "child_candidate_id": "son", "source_page": "003.jpg",
                                             "review_status": "needs_review"}]}

    def test_preview_then_apply_preserves_evidence_state_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_page_result(root, self.page())
            target = root / "003/page.json"
            before = target.read_bytes()
            state_bytes = b'{"person_uid_map": {"stable": "PER_FIXED"}, "manual_relationships": []}'
            (root / "review_state.json").write_bytes(state_bytes)
            (root / "person_registry.json").write_bytes(b'{"keep": true}')
            self.assertFalse(refresh_page(target)["applied"])
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(list(target.parent.glob("*.bak")))
            summary = refresh_page(target, apply=True)
            self.assertEqual((summary["reparented"], summary["after"]), (1, 2))
            self.assertEqual(Path(summary["backup"]).read_bytes(), before)
            after = json.loads(target.read_bytes())
            self.assertEqual({k: v for k, v in after.items() if k != "relationship_candidates"},
                             {k: v for k, v in json.loads(before).items() if k != "relationship_candidates"})
            self.assertEqual((root / "review_state.json").read_bytes(), state_bytes)
            self.assertEqual((root / "person_registry.json").read_bytes(), b'{"keep": true}')
            son = next(r for r in after["relationship_candidates"] if r["child_candidate_id"] == "son")
            self.assertEqual(son["relationship_id"], "R0001")
            self.assertEqual(son["parent_candidate_id"], "father")
            self.assertFalse(refresh_page(target, apply=True)["applied"])

    def test_reviewed_or_edited_relationships_are_preserved_verbatim(self):
        for status, updates in (("confirmed", {}), ("rejected", {}),
                                ("needs_review", {"003.jpg::R0001": {"notes": "human edit"}})):
            with self.subTest(status=status, updates=updates):
                page = self.page()
                page["relationship_candidates"][0]["review_status"] = status
                before = deepcopy(page)
                state = {"relationship_updates": updates}
                relations = refreshed_relationships(page, state)
                self.assertEqual(relations[0], page["relationship_candidates"][0])
                self.assertEqual(sum(r["child_candidate_id"] == "son" for r in relations), 1)
                self.assertEqual(page, before)

    def test_removed_relationship_id_is_not_recycled(self):
        page = self.page()
        page["relationship_candidates"][0]["child_candidate_id"] = "prose_candidate"
        relations = refreshed_relationships(page, {})
        self.assertEqual({r["relationship_id"] for r in relations}, {"R0002", "R0003"})
