"""Information Retrieval metrics for TaarYa evaluation.

Provides precision@k, recall@k, MRR, nDCG, and F1 computations
against ground-truth labels for both spatial and semantic queries.

These metrics are the standard measures expected by ADASS / A&C reviewers.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set


def precision_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """Fraction of top-k retrieved items that are relevant.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of ground-truth relevant item IDs.
        k: Cutoff rank.

    Returns:
        Precision@k in [0, 1].
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(top_k)


def recall_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """Fraction of relevant items found in the top-k.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of ground-truth relevant item IDs.
        k: Cutoff rank.

    Returns:
        Recall@k in [0, 1].
    """
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(relevant)


def f1_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """Harmonic mean of precision@k and recall@k."""
    p = precision_at_k(retrieved, relevant, k)
    r = recall_at_k(retrieved, relevant, k)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def hit_rate_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """Whether at least one relevant item appears in the top-k."""
    if k <= 0 or not relevant:
        return 0.0
    return 1.0 if any(item in relevant for item in retrieved[:k]) else 0.0


def mean_reciprocal_rank(retrieved: List[str], relevant: Set[str]) -> float:
    """Reciprocal of the rank of the first relevant item.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of ground-truth relevant item IDs.

    Returns:
        MRR in [0, 1].
    """
    for i, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at rank k.

    Uses binary relevance (1 if in relevant set, 0 otherwise).
    """
    if not relevant or k <= 0:
        return 0.0

    top_k = retrieved[:k]

    # DCG
    dcg = 0.0
    for i, item in enumerate(top_k, start=1):
        rel = 1.0 if item in relevant else 0.0
        dcg += rel / math.log2(i + 1)

    # Ideal DCG (all relevant items first)
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_count + 1))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def average_precision(retrieved: List[str], relevant: Set[str], k: int = None) -> float:
    """Average Precision (AP) for a single query.

    Computes the mean of precision values at each rank where a relevant
    item is retrieved.  When *k* is given the computation is truncated
    at rank *k*.

    Returns:
        AP in [0, 1].
    """
    if not relevant:
        return 0.0
    items = retrieved[:k] if k else retrieved
    hits = 0
    sum_prec = 0.0
    for i, item in enumerate(items, start=1):
        if item in relevant:
            hits += 1
            sum_prec += hits / i
    return sum_prec / len(relevant)


def mean_average_precision(
    queries: List[tuple],  # list of (retrieved_ids, relevant_set)
    k: int = None,
) -> float:
    """Mean Average Precision across multiple queries."""
    if not queries:
        return 0.0
    aps = [average_precision(r, rel, k) for r, rel in queries]
    return sum(aps) / len(aps)


def bootstrap_confidence_interval(
    values: List[float],
    n_boot: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> Dict[str, float]:
    """Non-parametric bootstrap CI for a list of per-query metric values.

    Returns dict with 'mean', 'lower', 'upper', 'std'.
    """
    import random

    if not values:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "std": 0.0}

    n = len(values)
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1 - ci) / 2
    lo = means[int(alpha * n_boot)]
    hi = means[int((1 - alpha) * n_boot)]
    overall_mean = sum(values) / n

    std = (sum((v - overall_mean) ** 2 for v in values) / n) ** 0.5
    return {
        "mean": round(overall_mean, 4),
        "lower": round(lo, 4),
        "upper": round(hi, 4),
        "std": round(std, 4),
    }


def evaluate_query(
    retrieved_ids: List[str],
    relevant_ids: List[str],
    k_values: List[int] = None,
) -> Dict[str, Any]:
    """Compute all metrics for a single query.

    Args:
        retrieved_ids: Ordered list of retrieved item IDs.
        relevant_ids: List of ground-truth relevant item IDs.
        k_values: List of k cutoffs to evaluate (default: [5, 10, 20]).

    Returns:
        Dictionary with all metric values.
    """
    if k_values is None:
        k_values = [5, 10, 20]

    relevant_set = set(relevant_ids)
    results: Dict[str, Any] = {
        "mrr": round(mean_reciprocal_rank(retrieved_ids, relevant_set), 4),
        "total_retrieved": len(retrieved_ids),
        "total_relevant": len(relevant_set),
    }

    for k in k_values:
        results[f"precision@{k}"] = round(precision_at_k(retrieved_ids, relevant_set, k), 4)
        results[f"recall@{k}"] = round(recall_at_k(retrieved_ids, relevant_set, k), 4)
        results[f"f1@{k}"] = round(f1_at_k(retrieved_ids, relevant_set, k), 4)
        results[f"hit@{k}"] = round(hit_rate_at_k(retrieved_ids, relevant_set, k), 4)
        results[f"ndcg@{k}"] = round(ndcg_at_k(retrieved_ids, relevant_set, k), 4)
        results[f"ap@{k}"] = round(average_precision(retrieved_ids, relevant_set, k), 4)

    return results


def aggregate_metrics(per_query_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute mean metrics across multiple queries.

    Args:
        per_query_results: List of per-query metric dicts from evaluate_query.

    Returns:
        Aggregated mean metrics.
    """
    if not per_query_results:
        return {}

    keys = [k for k in per_query_results[0] if isinstance(per_query_results[0][k], (int, float))]
    agg = {}
    for key in keys:
        values = [r[key] for r in per_query_results if key in r]
        if values:
            agg[f"mean_{key}"] = round(sum(values) / len(values), 4)

    agg["num_queries"] = len(per_query_results)
    return agg


def format_latex_table(
    config_results: Dict[str, Dict[str, Any]],
    metric_keys: List[str] = None,
) -> str:
    """Format ablation results as a LaTeX table for paper inclusion.

    Args:
        config_results: {config_name: aggregated_metrics_dict}
        metric_keys: Which metrics to include as columns.

    Returns:
        LaTeX tabular string.
    """
    if metric_keys is None:
        metric_keys = ["mean_precision@10", "mean_recall@10", "mean_f1@10", "mean_mrr", "mean_ndcg@10"]

    # Header
    col_headers = " & ".join(["Configuration"] + [k.replace("mean_", "").replace("@", "\\text{@}") for k in metric_keys])
    lines = [
        "\\begin{table}[ht]",
        "\\centering",
        "\\caption{TaarYa retrieval ablation: per-configuration mean metrics.}",
        "\\label{tab:ablation}",
        "\\begin{tabular}{l" + "c" * len(metric_keys) + "}",
        "\\toprule",
        col_headers + " \\\\",
        "\\midrule",
    ]

    for config_name, metrics in config_results.items():
        values = [f"{metrics.get(k, 0.0):.3f}" for k in metric_keys]
        lines.append(config_name + " & " + " & ".join(values) + " \\\\")

    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
    ]
    return "\n".join(lines)
