"""Relationship geometry tests."""
import unittest
from copy import deepcopy

import ocr.jokbo_ocr as module


def person(pid, x, y, name):
    return {
        "person_id": pid,
        "name_hanja_candidate": name,
        "bbox": {"x": x - 10, "y": y, "width": 20, "height": 70},
    }


def row(row_id, number, people):
    return {"row_id": row_id, "row_number": number, "person_candidates": people}


class RelationshipLayoutTests(unittest.TestCase):
    def test_sons_before_daughters_is_printed_order_not_birth_order(self):
        rows = [
            row("r1", 1, [person("father", 300, 0, "父")]),
            row("r2", 2, [
                person("M2", 300, 100, "子甲"),
                person("M3", 250, 100, "子乙"),
                person("F1", 200, 100, "女丙"),
                person("F4", 150, 100, "女丁"),
            ]),
        ]
        relations = module.parse_relationships(rows, page_width=600, table_x=0)
        by_child = {item["child_candidate_id"]: item for item in relations}
        self.assertEqual(by_child["M2"]["placement_role"], "first_son_aligned_under_father")
        self.assertEqual([r["child_candidate_id"] for r in relations], ["M2", "M3", "F1", "F4"])
        self.assertEqual([r["record_order"] for r in relations], [1, 2, 3, 4])
        self.assertEqual([r["child_order"] for r in relations], [1, 2, 1, 2])
        self.assertTrue(all(r["birth_order"] is None for r in relations))
        self.assertEqual(by_child["F1"]["inferred_child_sex"], "female_candidate")
        self.assertTrue(by_child["F1"]["placement_role"].startswith("daughter_after_sons_"))
        self.assertTrue(all(item["parent_candidate_id"] == "father" for item in relations))

    def test_relationship_does_not_depend_on_generation_labels(self):
        rows = [
            row("r1", 1, [person("father", 400, 0, "父")]),
            row("r2", 2, [person("son", 402, 100, "子")]),
        ]
        rows[0]["generation_number"] = None
        rows[1]["generation_number"] = None
        relations = module.parse_relationships(rows, page_width=600, table_x=0)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["parent_candidate_id"], "father")
        self.assertEqual(relations[0]["child_candidate_id"], "son")

    def test_two_parent_anchors(self):
        rows = [
            row("r1", 1, [
                person("right_parent", 450, 0, "父甲"),
                person("left_parent", 150, 0, "父乙"),
            ]),
            row("r2", 2, [
                person("right_child", 450, 100, "子甲"),
                person("left_child", 150, 100, "子乙"),
            ]),
        ]
        relations = module.parse_relationships(rows, page_width=600, table_x=0)
        mapping = {r["child_candidate_id"]: r["parent_candidate_id"] for r in relations}
        self.assertEqual(mapping, {"right_child": "right_parent", "left_child": "left_parent"})

    def test_wide_sibling_group_crosses_old_midpoint(self):
        rows = [row("r1", 1, [person("right", 619, 0, "子甲"), person("left", 209, 0, "子乙")]),
                row("r2", 2, [person("a", 617, 100, "子丙"), person("b", 454, 100, "子丁"),
                              person("c", 290, 100, "子戊"), person("d", 248, 100, "子己"),
                              person("e", 207, 100, "子庚"), person("f", 84, 100, "子辛")])]
        relations = module.parse_relationships(rows, 587, table_x=59)
        self.assertEqual({r["child_candidate_id"]: r["parent_candidate_id"] for r in relations},
                         {"a": "right", "b": "right", "c": "right", "d": "right", "e": "left", "f": "left"})
        self.assertTrue(all(r["inferred_child_sex"] == "male_candidate" for r in relations))

    def test_detached_daughter_marker_and_roi_coordinates(self):
        for offset in (0, 59):
            with self.subTest(offset=offset):
                rows = [row("r1", 1, [person("right", offset+395, 0, "子甲"),
                                      person("left", offset+231, 0, "子乙")]),
                        row("r2", 2, [person("son", offset+395, 100, "子丙"),
                                      person("daughter", offset+272, 125, "金丁")])]
                token_box = {"x": offset+257, "y": 95, "width": 30, "height": 23}
                rows[1]["columns"] = [{"column_id": "marker", "text": "女", "bbox": token_box}]
                before = deepcopy(rows)
                relations = module.parse_relationships(rows, 587, table_x=offset)
                daughter = next(r for r in relations if r["child_candidate_id"] == "daughter")
                self.assertEqual(daughter["parent_candidate_id"], "right")
                self.assertEqual(daughter["sex_marker"], "女")
                self.assertEqual(daughter["sex_marker_evidence"][0]["bbox"], token_box)
                self.assertEqual(rows, before)

    def test_adjacent_biography_marker_is_not_name_evidence(self):
        rows = [row("r1", 1, [person("father", 400, 0, "甲")]),
                row("r2", 2, [person("child", 400, 100, "乙")])]
        rows[1]["columns"] = [{"text": "女", "bbox": {"x": 365, "y": 100, "width": 20, "height": 20}}]
        relation = module.parse_relationships(rows, 600)[0]
        self.assertEqual(relation["inferred_child_sex"], "unknown")
        self.assertIsNone(relation["child_order"])

    def test_prose_candidates_do_not_become_parents_or_children(self):
        rows = [row("r1", 1, [person("father", 600, 0, "甲"), person("prose", 90, 0, "所未詳")]),
                row("r2", 2, [person("a", 600, 100, "子乙"), person("b", 210, 100, "子丙"),
                              person("office", 565, 100, "行兵馬節度使墓萬頃縣主山有")]),
                row("r3", 3, [person("c", 450, 200, "子丁")])]
        before = deepcopy(rows)
        relations = module.parse_relationships(rows, 700)
        self.assertEqual([(r["parent_candidate_id"], r["child_candidate_id"]) for r in relations],
                         [("father", "a"), ("father", "b"), ("a", "c")])
        self.assertEqual(rows, before)

    def test_position_does_not_invent_sex_or_rightward_daughter(self):
        rows = [row("r1", 1, [person("father", 300, 0, "甲")]),
                row("r2", 2, [person("outside", 400, 100, "子乙"), person("unknown", 200, 100, "丙")])]
        by_child = {r["child_candidate_id"]: r for r in module.parse_relationships(rows, 600)}
        self.assertIsNone(by_child["outside"]["parent_candidate_id"])
        self.assertEqual(by_child["unknown"]["inferred_child_sex"], "unknown")

    def test_conflicting_sons_after_daughters_is_flagged_without_reordering(self):
        rows = [row("r1", 1, [person("father", 400, 0, "甲")]),
                row("r2", 2, [person("a", 400, 100, "子乙"), person("b", 300, 100, "女丙"),
                              person("c", 200, 100, "子丁")])]
        relations = module.parse_relationships(rows, 600)
        self.assertEqual([r["child_candidate_id"] for r in relations], ["a", "b", "c"])
        self.assertTrue(all(r["ordering_conflict"] and r["review_status"] == "needs_review" for r in relations))

    def test_competing_aligned_parents_are_unresolved(self):
        rows = [row("r1", 1, [person("a", 300, 0, "甲"), person("b", 330, 0, "乙")]),
                row("r2", 2, [person("child", 315, 100, "子丙")])]
        relation = module.parse_relationships(rows, 600)[0]
        self.assertIsNone(relation["parent_candidate_id"])
        self.assertEqual(set(relation["candidate_parent_ids"]), {"a", "b"})

    def test_daughters_only_and_empty_rows_remain_review_pending(self):
        rows = [row("r1", 1, [person("father", 400, 0, "甲")]),
                row("r2", 2, [person("daughter", 400, 100, "女乙")]),
                row("r3", 3, []), row("r4", 4, [person("orphan", 400, 300, "子丙")])]
        relations = module.parse_relationships(rows, 600)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["inferred_child_sex"], "female_candidate")
        self.assertIn("No aligned son", relations[0]["warning"])


if __name__ == "__main__":
    unittest.main()
