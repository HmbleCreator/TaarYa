"""
Cluster-member retrieval: "I know a few members of cluster X -- find the rest."

This is what a membership graph claims to be for, so it is the fair test of the graph layer.

PROTOCOL (leak-free)
  * unit of replication = cluster (cone); results are bootstrapped over clusters
  * seeds = n known members drawn from gold (prob >= seed_min_prob); seeds are REMOVED from the candidate list
  * every method sees only the seeds + the cone's (pmra, pmdec, parallax); gold labels are used only to score
  * several random seed draws per cluster are averaged
METHODS
  current_graph_traversal : what MEMBER_OF-from-cone returns -- every cone star, no ordering  (== random order)
  seed_box                : TOPCAT-style: window of +-k robust sigma around the seeds' median          [BASELINE]
  seed_mahalanobis        : distance to the seed centroid with the seeds' shrinkage covariance
  seed_knn                : distance to the k-th nearest seed
  graph_ppr               : personalised PageRank from the seeds on a kNN similarity graph of cone stars
                            (a graph method that could justify a graph layer)
  hdbscan_with_seeds      : HDBSCAN; rank the cluster that contains most seeds first
CAVEAT (state it in the paper): Hunt & Reffert members were themselves found by clustering in this same space, so
all methods are measuring agreement with that algorithm; confirm on an independent catalogue (e.g. RV membership).
"""
from __future__ import annotations
import json
import numpy as np, pandas as pd
from ..core import Workflow, Claim, rank_by_score, average_precision, precision_at_k, ndcg_at_k, bootstrap_ci, paired_diff, MIN_UNITS
from .membership import canon, drop_synthetic

FEATS = ["pmra", "pmdec", "parallax"]


def _z(X):
    med = np.nanmedian(X, 0); sc = 1.4826 * np.nanmedian(np.abs(X - med), 0) + 1e-9
    return (X - med) / sc


def m_current_graph(Z, seeds, rng): return rng.random(len(Z))                          # unordered set == random order


def m_seed_box(Z, seeds, rng, floor=0.05):
    S = Z[seeds]; med = np.median(S, 0); sd = np.maximum(1.4826 * np.median(np.abs(S - med), 0), floor)
    return -np.max(np.abs(Z - med) / sd, axis=1)


def m_seed_mahalanobis(Z, seeds, rng):
    from sklearn.covariance import LedoitWolf
    S = Z[seeds]; mu = np.median(S, 0); P = LedoitWolf().fit(S).precision_
    D = Z - mu; return -np.einsum("ij,jk,ik->i", D, P, D)


def m_seed_knn(Z, seeds, rng, k=3):
    from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=min(k, len(seeds))).fit(Z[seeds]); d, _ = nn.kneighbors(Z)
    return -d[:, -1]


def m_graph_ppr(Z, seeds, rng, k=15, alpha=0.15, iters=60):
    from sklearn.neighbors import NearestNeighbors
    from scipy.sparse import csr_matrix
    n = len(Z); nn = NearestNeighbors(n_neighbors=min(k + 1, n)).fit(Z); d, idx = nn.kneighbors(Z)
    sig = np.median(d[:, 1:]) + 1e-9; w = np.exp(-(d[:, 1:] / sig) ** 2)
    A = csr_matrix((w.ravel(), (np.repeat(np.arange(n), idx.shape[1] - 1), idx[:, 1:].ravel())), shape=(n, n)); A = A + A.T
    deg = np.asarray(A.sum(1)).ravel() + 1e-12; T = csr_matrix(A.multiply(1 / deg[:, None]))
    p0 = np.zeros(n); p0[seeds] = 1.0 / len(seeds); p = p0.copy()
    for _ in range(iters): p = alpha * p0 + (1 - alpha) * (T.T @ p)
    return p


def m_hdbscan_with_seeds(Z, seeds, rng, min_cluster_size=20):
    from sklearn.cluster import HDBSCAN
    lab = HDBSCAN(min_cluster_size=min_cluster_size, copy=True).fit_predict(Z)
    sl = lab[seeds]; sl = sl[sl >= 0]
    if len(sl) == 0: return rng.random(len(Z)) * 0.01
    best = np.bincount(sl).argmax(); return (lab == best).astype(float) + rng.random(len(Z)) * 1e-3


METHODS = {"current_graph_traversal": m_current_graph, "seed_box": m_seed_box, "seed_mahalanobis": m_seed_mahalanobis,
           "seed_knn": m_seed_knn, "graph_ppr": m_graph_ppr, "hdbscan_with_seeds": m_hdbscan_with_seeds}
BASELINE = "seed_box"


def evaluate_retrieval(stars: pd.DataFrame, gold: pd.DataFrame, n_seeds=10, repeats=5, min_hidden=20, seed_min_prob=0.9, seed=0, methods=None, k_eval=50) -> dict:
    methods = methods or METHODS
    stars, _ = drop_synthetic(stars, "stars"); gold = gold.assign(cluster=gold.cluster.map(canon))
    stars = stars.assign(cluster=stars.cluster.map(canon)); rng = np.random.default_rng(seed)
    per, skipped, acc = {}, [], {m: dict(ap=[], pk=[], ndcg=[]) for m in methods}
    for cl, g in stars.groupby("cluster"):
        g = g.dropna(subset=FEATS).reset_index(drop=True); ids = g.source_id.to_numpy(object); pos = {int(i): j for j, i in enumerate(ids)}
        gc = gold[gold.cluster == cl]; gold_idx = np.array(sorted({pos[int(i)] for i in gc.source_id if int(i) in pos}))
        conf = np.array(sorted({pos[int(i)] for i in gc.source_id[gc.prob >= seed_min_prob] if int(i) in pos})) if "prob" in gc else gold_idx
        if len(gold_idx) < n_seeds + min_hidden or len(conf) < n_seeds:
            skipped.append(dict(cluster=cl, reason=f"{len(gold_idx)} gold in cone ({len(conf)} confident); need >= {n_seeds + min_hidden}")); continue
        Z = _z(g[FEATS].to_numpy(float)); is_gold = np.zeros(len(g), bool); is_gold[gold_idx] = True
        m_res = {m: dict(ap=[], pk=[], ndcg=[]) for m in methods}
        for _ in range(repeats):
            seeds = rng.choice(conf, n_seeds, replace=False); cand = np.ones(len(g), bool); cand[seeds] = False       # seeds are not candidates
            for m, fn in methods.items():
                sc = fn(Z, seeds, rng)[cand]; order = rank_by_score(sc, rng); rel = is_gold[cand][order].astype(int)
                m_res[m]["ap"].append(average_precision(rel)); m_res[m]["pk"].append(precision_at_k(rel, k_eval)); m_res[m]["ndcg"].append(ndcg_at_k(rel, 100))
        per[cl] = dict(n_cone=len(g), n_gold_in_cone=int(len(gold_idx)), cone_purity=round(len(gold_idx) / len(g), 4),
                       **{m: {k: round(float(np.mean(v)), 3) for k, v in r.items()} for m, r in m_res.items()})
        for m in methods:
            for k in ("ap", "pk", "ndcg"): acc[m][k].append(float(np.mean(m_res[m][k])))
    if not per: return dict(n_clusters=0, skipped=skipped, error="no cluster has enough gold members in its cone")
    agg = {m: dict(AP=bootstrap_ci(acc[m]["ap"], min_n=MIN_UNITS), **{f"P@{k_eval}": bootstrap_ci(acc[m]["pk"], min_n=MIN_UNITS), "nDCG@100": bootstrap_ci(acc[m]["ndcg"], min_n=MIN_UNITS)}) for m in methods}
    for m in methods:
        if m != BASELINE and BASELINE in methods: agg[m]["AP_diff_vs_seed_box"] = paired_diff(acc[m]["ap"], acc[BASELINE]["ap"], min_n=MIN_UNITS)
    caution = f"descriptive only: n={len(per)} < {MIN_UNITS} clusters; read per_cluster" if len(per) < MIN_UNITS else "agreement with Hunt & Reffert (itself a clustering in this space)"
    return dict(n_clusters=len(per), n_seeds=n_seeds, repeats=repeats, per_cluster=per, skipped=skipped, aggregate=agg, caution=caution)


class ClusterMemberRetrieval(Workflow):
    name = "cluster_member_retrieval"
    ground_truth = "Hunt & Reffert 2023 members (prob>=0.7) inside real Gaia cones; drop-in: any membership list"
    baseline = "TOPCAT: select a few known members, window the cone in PM/parallax around them"
    claim_ceiling = Claim.CANDIDATE
    evidence_level = "real-labels-required"

    def __init__(self, stars_csv=None, gold_csv=None): self.stars_csv, self.gold_csv = stars_csv, gold_csv

    def evaluate(self, seed=7, quick=False):
        if not (self.stars_csv and self.gold_csv): return dict(error="supply stars.csv and gold.csv from cluster_cones.build")
        st = pd.read_csv(self.stars_csv, dtype={"source_id": str}); gd = pd.read_csv(self.gold_csv, dtype={"source_id": str})
        return evaluate_retrieval(st, gd, repeats=2 if quick else 5, seed=seed)


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("--stars", required=True); ap.add_argument("--gold", required=True)
    ap.add_argument("--n-seeds", type=int, default=10); a = ap.parse_args()
    st = pd.read_csv(a.stars, dtype={"source_id": str}); gd = pd.read_csv(a.gold, dtype={"source_id": str})
    print(json.dumps(evaluate_retrieval(st, gd, n_seeds=a.n_seeds), indent=2))
