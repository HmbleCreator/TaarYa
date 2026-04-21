"""Unit tests for evaluation metrics module."""

import unittest
from eval.metrics import (
    precision_at_k,
    recall_at_k,
    f1_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    evaluate_query,
    aggregate_metrics,
    format_latex_table,
)


class TestPrecisionAtK(unittest.TestCase):
    def test_perfect_precision(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        self.assertEqual(precision_at_k(retrieved, relevant, 3), 1.0)

    def test_zero_precision(self):
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b", "c"}
        self.assertEqual(precision_at_k(retrieved, relevant, 3), 0.0)

    def test_partial_precision(self):
        retrieved = ["a", "x", "b", "y"]
        relevant = {"a", "b", "c"}
        self.assertAlmostEqual(precision_at_k(retrieved, relevant, 4), 0.5)

    def test_k_larger_than_retrieved(self):
        retrieved = ["a", "b"]
        relevant = {"a", "b", "c"}
        self.assertEqual(precision_at_k(retrieved, relevant, 5), 1.0)

    def test_k_zero(self):
        self.assertEqual(precision_at_k(["a"], {"a"}, 0), 0.0)

    def test_empty_retrieved(self):
        self.assertEqual(precision_at_k([], {"a"}, 5), 0.0)


class TestRecallAtK(unittest.TestCase):
    def test_perfect_recall(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        self.assertEqual(recall_at_k(retrieved, relevant, 3), 1.0)

    def test_partial_recall(self):
        retrieved = ["a", "x", "y"]
        relevant = {"a", "b", "c"}
        self.assertAlmostEqual(recall_at_k(retrieved, relevant, 3), 1/3)

    def test_empty_relevant(self):
        self.assertEqual(recall_at_k(["a"], set(), 5), 0.0)


class TestMRR(unittest.TestCase):
    def test_first_relevant(self):
        self.assertEqual(mean_reciprocal_rank(["a", "b"], {"a"}), 1.0)

    def test_second_relevant(self):
        self.assertEqual(mean_reciprocal_rank(["x", "a"], {"a"}), 0.5)

    def test_no_relevant(self):
        self.assertEqual(mean_reciprocal_rank(["x", "y"], {"a"}), 0.0)


class TestNDCG(unittest.TestCase):
    def test_perfect_ndcg(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        self.assertAlmostEqual(ndcg_at_k(retrieved, relevant, 3), 1.0)

    def test_zero_ndcg(self):
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        self.assertAlmostEqual(ndcg_at_k(retrieved, relevant, 3), 0.0)

    def test_partial_ndcg(self):
        # Second item relevant, first not
        retrieved = ["x", "a", "y"]
        relevant = {"a"}
        result = ndcg_at_k(retrieved, relevant, 3)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)


class TestEvaluateQuery(unittest.TestCase):
    def test_returns_all_metrics(self):
        result = evaluate_query(["a", "b", "c"], ["a", "c"], k_values=[5, 10])
        self.assertIn("precision@5", result)
        self.assertIn("recall@10", result)
        self.assertIn("mrr", result)
        self.assertIn("ndcg@5", result)
        self.assertIn("f1@5", result)


class TestAggregateMetrics(unittest.TestCase):
    def test_aggregation(self):
        results = [
            {"precision@10": 0.8, "recall@10": 0.6, "mrr": 1.0},
            {"precision@10": 0.4, "recall@10": 0.2, "mrr": 0.5},
        ]
        agg = aggregate_metrics(results)
        self.assertAlmostEqual(agg["mean_precision@10"], 0.6)
        self.assertAlmostEqual(agg["mean_mrr"], 0.75)
        self.assertEqual(agg["num_queries"], 2)


class TestLatexTable(unittest.TestCase):
    def test_generates_valid_latex(self):
        config_results = {
            "Config A": {"mean_precision@10": 0.8, "mean_recall@10": 0.6, "mean_f1@10": 0.69, "mean_mrr": 0.9, "mean_ndcg@10": 0.85},
            "Config B": {"mean_precision@10": 0.5, "mean_recall@10": 0.4, "mean_f1@10": 0.44, "mean_mrr": 0.6, "mean_ndcg@10": 0.55},
        }
        latex = format_latex_table(config_results)
        self.assertIn("\\begin{table}", latex)
        self.assertIn("Config A", latex)
        self.assertIn("0.800", latex)
        self.assertIn("\\end{table}", latex)


if __name__ == "__main__":
    unittest.main()
