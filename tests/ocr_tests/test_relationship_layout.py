"""Relationship geometry tests."""
import unittest

import ocr.pipeline as module


def person(pid, x, y, name):
    return {
        "person_id": pid,
        "name_hanja_candidate": name,
        "bbox": {"x": x - 10, "y": y, "width": 20, "height": 70},
    }


def row(row_id, number, people):
    return {"row_id": row_id, "row_number": number, "person_candidates": people}


class RelationshipLayoutTests(unittest.TestCase):
    def test_user_position_rule_sons_and_daughter(self):
        rows = [
            row("r1", 1, [person("father", 300, 0, "父")]),
            row("r2", 2, [
                person("first_son", 300, 100, "長子"),
                person("second_son", 250, 100, "次子"),
                person("daughter", 350, 100, "女"),
            ]),
        ]
        relations = module.parse_relationships(rows, page_width=600, table_x=0)
        by_child = {item["child_candidate_id"]: item for item in relations}
        self.assertEqual(by_child["first_son"]["placement_role"], "first_son_aligned_under_father")
        self.assertEqual(by_child["second_son"]["placement_role"], "additional_son_left_of_first_2")
        self.assertEqual(by_child["daughter"]["inferred_child_sex"], "female_candidate")
        self.assertTrue(by_child["daughter"]["placement_role"].startswith("daughter_right_of_sons_"))
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

    def test_two_parent_branches_are_separated_by_midpoint(self):
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


if __name__ == "__main__":
    unittest.main()
