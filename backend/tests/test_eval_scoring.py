import unittest

from eval.dataset import load_cases
from eval.scoring import (
    compare_result_sets,
    field_recall,
    mrr,
    table_hit_rate,
)

DATASET_PATH = "eval/dataset.json"


class ScoringTest(unittest.TestCase):
    def test_field_recall_counts_expected_doc_ids_in_hits(self) -> None:
        hits = [{"doc_id": "a.b.x"}, {"doc_id": "a.b.y"}, {"doc_id": "a.b.z"}]

        self.assertEqual(field_recall(["a.b.x", "a.b.y"], hits), 1.0)
        self.assertEqual(field_recall(["a.b.x", "a.b.missing"], hits), 0.5)
        self.assertEqual(field_recall(["a.b.missing"], hits), 0.0)
        self.assertEqual(field_recall([], hits), 1.0)

    def test_table_hit_rate_uses_hit_table_ids(self) -> None:
        hits = [{"table_id": "db.t1"}, {"table_id": "db.t2"}]

        self.assertEqual(table_hit_rate(["db.t1"], hits), 1.0)
        self.assertEqual(table_hit_rate(["db.t1", "db.t3"], hits), 0.5)

    def test_mrr_uses_rank_of_first_expected_hit(self) -> None:
        hits = [{"doc_id": "a"}, {"doc_id": "b"}, {"doc_id": "c"}]

        self.assertEqual(mrr(["b"], hits), 0.5)
        self.assertEqual(mrr(["c", "a"], hits), 1.0)
        self.assertEqual(mrr(["z"], hits), 0.0)


class CompareResultSetsTest(unittest.TestCase):
    def test_equal_despite_column_and_row_order(self) -> None:
        expected = {
            "columns": ["name", "total"],
            "rows": [{"name": "甲", "total": 1}, {"name": "乙", "total": 2}],
        }
        actual = {
            "columns": ["total", "name"],
            "rows": [{"name": "乙", "total": 2.0}, {"name": "甲", "total": 1.0}],
        }

        ok, reason = compare_result_sets(expected, actual)

        self.assertTrue(ok, reason)

    def test_numeric_tolerance(self) -> None:
        expected = {"columns": ["v"], "rows": [{"v": 1.0000001}]}
        actual = {"columns": ["v"], "rows": [{"v": 1.0000002}]}

        ok, _ = compare_result_sets(expected, actual)
        self.assertTrue(ok)

        ok, reason = compare_result_sets(expected, {"columns": ["v"], "rows": [{"v": 1.5}]})
        self.assertFalse(ok)
        self.assertIn("数值不一致", reason)

    def test_column_mismatch_and_row_count_mismatch(self) -> None:
        expected = {"columns": ["a"], "rows": [{"a": 1}]}

        ok, reason = compare_result_sets(expected, {"columns": ["b"], "rows": [{"b": 1}]})
        self.assertFalse(ok)
        self.assertIn("列不一致", reason)

        ok, reason = compare_result_sets(expected, {"columns": ["a"], "rows": []})
        self.assertFalse(ok)
        self.assertIn("行数不一致", reason)


class DatasetTest(unittest.TestCase):
    def test_seed_dataset_is_valid(self) -> None:
        cases = load_cases(DATASET_PATH)

        self.assertGreaterEqual(len(cases), 13)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))

    def test_unknown_category_is_rejected(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        payload = {"cases": [{
            "id": "x1", "category": "unknown", "query": "q", "expected_route": "data_qa",
        }]}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未知评测类别"):
                load_cases(path)

    def test_query_case_requires_retrieval_terms_and_fields(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        payload = {"cases": [{
            "id": "x2", "category": "simple_query", "query": "q",
            "expected_route": "database_query",
        }]}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "retrieval_terms"):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
