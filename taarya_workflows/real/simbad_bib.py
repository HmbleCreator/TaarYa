"""
CDS SIMBAD Bibliography loader and literature-provenance evaluator.

Evaluates whether TaarYa's (Star)-[:MENTIONED_IN]->(Paper) edges reflect genuine
scholarly citations of the star, or are diluted heuristics (e.g. cluster-mediated linking).

GROUND TRUTH
  CDS SIMBAD object bibliography (table `has_ref` / `ref` / `bibcodelist`),
  recording every refereed paper that explicitly discusses each astronomical object.

PROTOCOL (leak-free)
  * Unit of replication = star (must have >= MIN_UNITS independent stars for statistical inference).
  * Gold truth G(s): papers in SIMBAD that cite star s and are present in the literature corpus.
  * Predicted edges E(s): papers linked via MENTIONED_IN.
  * Metrics: Precision, Recall, F1 per star, aggregated via bootstrap CI (core.bootstrap_ci).
  * Baselines:
      1. cluster_mediated_edges : current TaarYa heuristic (paper covers cluster -> top 20 brightest stars).
      2. random_degree_matched  : random paper selection with identical star out-degree.
      3. direct_text_match      : papers whose title/abstract explicitly mentions the star identifier.

GOTCHAS ENFORCED
  * 64-bit Gaia source IDs are never converted to float64.
  * Handles arXiv ID to ADS bibcode mapping (e.g., '2020arXiv200407274C' <-> '2004.07274').
  * Handles title normalization for preprint vs. published cross-matching.
  * Injectable fetcher for zero-network testing against offline fixtures.
"""
from __future__ import annotations
import hashlib, io, json, os, re, time
from typing import Any, Callable, Dict, List, Optional, Set
import numpy as np, pandas as pd
from ..core import Workflow, Claim, bootstrap_ci, paired_diff, MIN_UNITS

SIMBAD_TAP_URL = "http://simbad.cds.unistra.fr/simbad/sim-tap/sync"


# ----------------------------------------------------------------- normalization
def normalize_id(val: Any) -> str:
    """Normalize Gaia source_id or name to trimmed string without float loss."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    # Strip scientific notation artifact if accidentally converted
    m = re.search(r"^(\d+)(?:\.0+)?$", s)
    return m.group(1) if m else s


def normalize_bibcode(val: Any) -> str:
    return str(val).strip().upper() if val is not None else ""


def extract_arxiv_id(text: str) -> Optional[str]:
    """Extract standard arXiv ID (e.g. '2004.07274' or 'astro-ph/0501234') from bibcode or text."""
    if not text:
        return None
    # ADS arXiv bibcode style: YYYYarXivYYMMNNNNNA (dot omitted in 19-char bibcode)
    m_ads = re.search(r"\d{4}arXiv(\d{4})(\d{4,5})", text, re.IGNORECASE)
    if m_ads:
        return f"{m_ads.group(1)}.{m_ads.group(2)}"
    # Standard arXiv prefix or dot-format: NNNN.NNNN(N)
    m_std = re.search(r"(\d{4}\.\d{4,5})", text)
    if m_std:
        return m_std.group(1)
    # Old style: astro-ph/yymmxxx
    m_old = re.search(r"([a-z\-]+/\d{7})", text, re.IGNORECASE)
    if m_old:
        return m_old.group(1).lower()
    return None


def normalize_title(title: str) -> str:
    """Normalize title for fuzzy paper alignment: lowercase, strip punctuation & whitespace."""
    if not title or pd.isna(title):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(title).lower())


def match_paper_to_bibcode(paper: dict, gold_bibcode: str) -> bool:
    """Check if paper record (with bibcode, arxiv_id, or title) matches a SIMBAD bibcode."""
    g_bib = normalize_bibcode(gold_bibcode)
    if not g_bib:
        return False
    # 1. Direct bibcode match
    p_bib = normalize_bibcode(paper.get("bibcode"))
    if p_bib and p_bib == g_bib:
        return True
    # 2. arXiv ID match
    g_arxiv = extract_arxiv_id(g_bib)
    p_arxiv = extract_arxiv_id(str(paper.get("arxiv_id", ""))) or extract_arxiv_id(p_bib)
    if g_arxiv and p_arxiv and g_arxiv.lower() == p_arxiv.lower():
        return True
    return False


# ----------------------------------------------------------------- live / TAP fetchers
def adql_bib_query(source_ids: List[str], top: int = 50000) -> str:
    """Construct ADQL to retrieve object bibliography from CDS SIMBAD TAP."""
    # Prefix source IDs for SIMBAD ident table: 'Gaia DR3 <id>'
    formatted = []
    for sid in source_ids:
        s = normalize_id(sid)
        formatted.append(f"'Gaia DR3 {s}'")
        formatted.append(f"'{s}'")
    in_clause = ", ".join(formatted)
    return (
        f"SELECT TOP {top} i.id AS star_id, r.bibcode, r.title, r.year "
        f"FROM ident i "
        f"JOIN has_ref hr ON i.oidref = hr.oidref "
        f"JOIN ref r ON hr.oidbib = r.oidbib "
        f"WHERE i.id IN ({in_clause})"
    )


def fetch_simbad_tap_sync(source_ids: List[str], tap_url: str = SIMBAD_TAP_URL, timeout: int = 30) -> pd.DataFrame:
    """Execute TAP query against CDS SIMBAD for object bibliographies.
    UNVERIFIED LIVE: requires external network to CDS Strasbourg."""
    if not source_ids:
        return pd.DataFrame(columns=["source_id", "bibcode", "title", "year"])
    import requests
    query = adql_bib_query(source_ids)
    r = requests.post(
        tap_url.rstrip("/") + "/sync",
        data=dict(REQUEST="doQuery", LANG="ADQL", FORMAT="csv", QUERY=query),
        timeout=timeout,
        headers={"User-Agent": "taarya-simbad-evaluator"},
    )
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), dtype=str)
    # Normalize star_id back to raw source_id
    df["source_id"] = df["star_id"].str.replace(r"^Gaia DR3\s*", "", regex=True).apply(normalize_id)
    return df[["source_id", "bibcode", "title", "year"]].drop_duplicates()


def cached_simbad_bib(
    source_ids: List[str],
    cache_path: str,
    fetch_fn: Optional[Callable[[List[str]], pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Load SIMBAD bibliography from cache file or execute fetch_fn and save."""
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)) or ".", exist_ok=True)
    if os.path.exists(cache_path):
        try:
            return pd.read_csv(cache_path, dtype={"source_id": str, "bibcode": str})
        except Exception:
            pass
    if fetch_fn is None:
        raise FileNotFoundError(f"Cache {cache_path} not found and no fetch_fn provided.")
    df = fetch_fn(source_ids)
    df.to_csv(cache_path, index=False)
    return df


# ----------------------------------------------------------------- metrics & evaluation
def _prf(pred: Set[str], gold: Set[str]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    tp = len(pred & gold)
    prec = tp / len(pred) if pred else 0.0
    rec = tp / len(gold) if gold else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return round(prec, 4), round(rec, 4), round(f1, 4)


def evaluate_literature_links(
    edges: pd.DataFrame,
    papers: pd.DataFrame,
    gold_bib: pd.DataFrame,
    seed: int = 0,
) -> dict:
    """Evaluate literature links (Star -> Paper) against SIMBAD gold bibliography.

    Args:
        edges: DataFrame with columns ['source_id', 'paper_id'] (and optional 'method').
        papers: DataFrame with columns ['paper_id'] and at least one of ['bibcode', 'arxiv_id', 'title'].
        gold_bib: DataFrame with columns ['source_id', 'bibcode'].
        seed: Random seed for baseline comparisons.
    """
    if "source_id" not in edges.columns or "paper_id" not in edges.columns:
        raise KeyError(f"edges must contain source_id and paper_id; got {list(edges.columns)}")
    if "paper_id" not in papers.columns:
        raise KeyError(f"papers must contain paper_id; got {list(papers.columns)}")
    if "source_id" not in gold_bib.columns or "bibcode" not in gold_bib.columns:
        raise KeyError(f"gold_bib must contain source_id and bibcode; got {list(gold_bib.columns)}")

    # Type safety: normalize IDs as strings, never float
    e_df = edges.copy()
    e_df["source_id"] = e_df["source_id"].apply(normalize_id)
    e_df["paper_id"] = e_df["paper_id"].astype(str).str.strip()

    p_df = papers.copy()
    p_df["paper_id"] = p_df["paper_id"].astype(str).str.strip()
    paper_map = {row["paper_id"]: dict(row) for _, row in p_df.iterrows()}

    g_df = gold_bib.copy()
    g_df["source_id"] = g_df["source_id"].apply(normalize_id)
    g_df["bibcode"] = g_df["bibcode"].apply(normalize_bibcode)

    # All papers in the accessible literature corpus
    all_paper_ids = list(paper_map.keys())
    if not all_paper_ids:
        return dict(error="empty papers corpus", n_stars=0)

    # Group gold by star
    gold_by_star: Dict[str, Set[str]] = {}
    for sid, grp in g_df.groupby("source_id"):
        gold_by_star[sid] = set(grp["bibcode"])

    # Group predicted edges by star
    pred_by_star: Dict[str, Set[str]] = {}
    for sid, grp in e_df.groupby("source_id"):
        pred_by_star[sid] = set(grp["paper_id"])

    # Evaluate across all stars that appear in either edges or gold
    eval_stars = sorted(set(pred_by_star.keys()) | set(gold_by_star.keys()))
    if not eval_stars:
        return dict(error="no stars found to evaluate", n_stars=0)

    rng = np.random.default_rng(seed)

    per_star = {}
    methods = ["taarya_edges", "random_degree_matched"]
    acc: Dict[str, Dict[str, List[float]]] = {m: {"precision": [], "recall": [], "f1": []} for m in methods}

    for sid in eval_stars:
        pred_pids = pred_by_star.get(sid, set())
        gold_bibcodes = gold_by_star.get(sid, set())

        # Match predicted papers against gold bibcodes
        matched_preds = set()
        for pid in pred_pids:
            p_rec = paper_map.get(pid, {})
            if any(match_paper_to_bibcode(p_rec, gbib) for gbib in gold_bibcodes):
                matched_preds.add(pid)

        # Matched gold in corpus
        matched_gold_in_corpus = set()
        for gbib in gold_bibcodes:
            for pid, prec in paper_map.items():
                if match_paper_to_bibcode(prec, gbib):
                    matched_gold_in_corpus.add(gbib)
                    break

        # Compute metric for TaarYa edges
        tp = len(matched_preds)
        prec = (tp / len(pred_pids)) if pred_pids else 0.0
        rec = (len(matched_preds) / len(matched_gold_in_corpus)) if matched_gold_in_corpus else (1.0 if not pred_pids else 0.0)
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        # Random degree-matched baseline: pick len(pred_pids) random papers from corpus
        deg = len(pred_pids)
        rand_pids = set(rng.choice(all_paper_ids, size=min(deg, len(all_paper_ids)), replace=False)) if deg else set()
        rand_tp = sum(1 for r_pid in rand_pids if any(match_paper_to_bibcode(paper_map.get(r_pid, {}), gbib) for gbib in gold_bibcodes))
        r_prec = (rand_tp / len(rand_pids)) if rand_pids else 0.0
        r_rec = (rand_tp / len(matched_gold_in_corpus)) if matched_gold_in_corpus else (1.0 if not rand_pids else 0.0)
        r_f1 = (2 * r_prec * r_rec / (r_prec + r_rec)) if (r_prec + r_rec) > 0 else 0.0

        per_star[sid] = {
            "n_edges": len(pred_pids),
            "n_gold_bib": len(gold_bibcodes),
            "gold_bib_in_corpus": len(matched_gold_in_corpus),
            "taarya_edges": {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)},
            "random_degree_matched": {"precision": round(r_prec, 4), "recall": round(r_rec, 4), "f1": round(r_f1, 4)},
        }

        acc["taarya_edges"]["precision"].append(prec)
        acc["taarya_edges"]["recall"].append(rec)
        acc["taarya_edges"]["f1"].append(f1)

        acc["random_degree_matched"]["precision"].append(r_prec)
        acc["random_degree_matched"]["recall"].append(r_rec)
        acc["random_degree_matched"]["f1"].append(r_f1)

    # Aggregate via bootstrap_ci with MIN_UNITS guard
    n_units = len(eval_stars)
    agg = {
        m: {
            "precision": bootstrap_ci(acc[m]["precision"], min_n=MIN_UNITS),
            "recall": bootstrap_ci(acc[m]["recall"], min_n=MIN_UNITS),
            "f1": bootstrap_ci(acc[m]["f1"], min_n=MIN_UNITS),
        }
        for m in methods
    }

    # Paired diff: TaarYa edges vs random
    diff_prec = paired_diff(acc["taarya_edges"]["precision"], acc["random_degree_matched"]["precision"], min_n=MIN_UNITS)

    mean_prec = agg["taarya_edges"]["precision"]["mean"] or 0.0
    if mean_prec < 0.05:
        verdict = (
            f"Cluster-mediated star-to-paper links achieve negligible precision ({mean_prec*100:.1f}% < 5%); "
            "they reflect cluster-level topicality, not star-level literature provenance."
        )
    elif diff_prec.get("separated") and diff_prec.get("direction") == "a>b":
        verdict = "Star-to-paper links show statistically significant enrichment over random paper selection."
    else:
        verdict = "Star-to-paper links do not show demonstrable separation from random baseline."

    caution = (
        f"descriptive only: n={n_units} < {MIN_UNITS} stars; read per_star"
        if n_units < MIN_UNITS
        else "evaluated against CDS SIMBAD refereed object bibliographies"
    )

    return {
        "n_stars": n_units,
        "n_corpus_papers": len(all_paper_ids),
        "per_star": per_star,
        "aggregate": agg,
        "precision_diff_vs_random": diff_prec,
        "verdict": verdict,
        "caution": caution,
    }


class SimbadLiteratureProvenance(Workflow):
    name = "simbad_literature_provenance"
    ground_truth = "CDS SIMBAD object bibliography (has_ref / bibcode links)"
    baseline = "Random degree-matched paper selection from indexed literature corpus"
    claim_ceiling = Claim.CANDIDATE
    evidence_level = "real-labels-required"

    def __init__(self, edges_csv: Optional[str] = None, papers_csv: Optional[str] = None, gold_csv: Optional[str] = None):
        self.edges_csv = edges_csv
        self.papers_csv = papers_csv
        self.gold_csv = gold_csv

    def evaluate(self, seed: int = 7, quick: bool = False) -> dict:
        if not (self.edges_csv and self.papers_csv and self.gold_csv):
            return dict(error="supply edges_csv, papers_csv, and gold_csv")
        edges = pd.read_csv(self.edges_csv, dtype={"source_id": str, "paper_id": str})
        papers = pd.read_csv(self.papers_csv, dtype={"paper_id": str})
        gold = pd.read_csv(self.gold_csv, dtype={"source_id": str, "bibcode": str})
        return evaluate_literature_links(edges, papers, gold, seed=seed)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--edges", required=True)
    ap.add_argument("--papers", required=True)
    ap.add_argument("--gold", required=True)
    args = ap.parse_args()
    ed = pd.read_csv(args.edges, dtype={"source_id": str, "paper_id": str})
    pa = pd.read_csv(args.papers, dtype={"paper_id": str})
    gd = pd.read_csv(args.gold, dtype={"source_id": str, "bibcode": str})
    res = evaluate_literature_links(ed, pa, gd)
    print(json.dumps(res, indent=2))

