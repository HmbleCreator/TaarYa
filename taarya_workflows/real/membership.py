"""
Do TaarYa's MEMBER_OF edges encode real cluster membership, or just "was seeded from this cone"?

Step 0 (no external data): Jaccard(edges, cone). ~1.0 means the edges ARE the cone.
Step 1: compare edges and TOPCAT-style baselines against a published membership list.

INPUTS (CSV or DataFrame)
  stars : cluster, source_id, pmra, pmdec, parallax     one row per catalogue star in each seeded cone
  edges : cluster, source_id                              export of (Star)-[:MEMBER_OF]->(Cluster)
  gold  : Hunt & Reffert 2023 (Gaia DR3 ids) or Cantat-Gaudin+2020 (Gaia DR2 ids)

GOTCHAS ENFORCED
  * CG2020 uses Gaia DR2 source_ids; TaarYa stores DR3. DR2 ids are refused unless you pass a dr2->dr3 map
    (e.g. exported from the Gaia archive's dr2_neighbourhood table -- unverified here).
  * Recall is measured against gold members that are IN YOUR CATALOGUE (your parallax-SNR cut removes many
    true members); gold_coverage reports how much of the real cluster your table even contains.
  * Cluster names differ between catalogues (Hyades = Melotte_25 ...): ALIASES is editable.
UNVERIFIED HERE (no network): VizieR table/column names. Column lookup is tolerant and lists what it saw on failure.
"""
from __future__ import annotations
import os, re, json
import numpy as np, pandas as pd
from ..core import bootstrap_ci, MIN_UNITS

ALIASES = {
    "hyades": ["Hyades", "Melotte_25", "Mel_25"], "pleiades": ["Pleiades", "Melotte_22", "Mel_22", "M45"],
    "praesepe": ["Praesepe", "NGC_2632", "Melotte_88", "M44"], "comaberenices": ["Coma Berenices", "Coma_Ber", "Melotte_111", "Mel_111"],
    "alphaperseus": ["Alpha Persei", "alpha_Per", "Melotte_20", "Mel_20"], "ic2391": ["IC 2391", "IC_2391"],
    "ngc2516": ["NGC 2516", "NGC_2516"],
}
GOLD_COLS = dict(id=["GaiaDR3", "DR3Name", "GaiaDR3_ID", "Source", "source_id", "Gaia", "GaiaDR2"],
                 cluster=["Name", "Cluster", "cluster", "ClusterName"],
                 prob=["Prob", "proba", "probability", "PMemb", "memprob"])
NEO4J_QUERY = "MATCH (s:Star)-[:MEMBER_OF]->(c:Cluster) RETURN s.source_id AS source_id, c.name AS cluster"  # property names unverified


def norm(s) -> str:
    return re.sub(r"[\s_\-\.]+", "", str(s)).lower()


_ALIAS = {norm(a): k for k, v in ALIASES.items() for a in v}
def canon(s) -> str:
    """Catalogue names vary: 'Melotte_22 (Pleiades)', 'Melotte_22', 'Pleiades'. Try the whole string, each bracketed part and the unbracketed part."""
    s = str(s); bare = re.sub(r"\([^)]*\)", "", s)
    for part in [s, bare] + re.findall(r"\(([^)]*)\)", s):
        if norm(part) in _ALIAS: return _ALIAS[norm(part)]
    return norm(bare)


def _pick(df, names, required=True):
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    if required: raise KeyError(f"none of {names} in columns {list(df.columns)[:30]}")
    return None


def _ids(series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.extract(r"(\d{6,})")[0], errors="coerce").astype("Int64")


# ----------------------------------------------------------------- gold
def load_gold(src, id_system="dr3", min_prob=0.7, dr2_to_dr3=None):
    df = pd.read_csv(src) if isinstance(src, str) else src.copy()
    if id_system == "dr2":
        if dr2_to_dr3 is None:
            raise ValueError("catalogue uses Gaia DR2 source_ids but TaarYa stores DR3; pass dr2_to_dr3 (DataFrame with "
                             "dr2_source_id, dr3_source_id). Comparing raw ids silently mismatches stars.")
        m = dr2_to_dr3.set_index("dr2_source_id")["dr3_source_id"]
        df["_id"] = _ids(df[_pick(df, GOLD_COLS["id"])]).map(m)
    else:
        df["_id"] = _ids(df[_pick(df, GOLD_COLS["id"])])
    pc = _pick(df, GOLD_COLS["prob"], required=False)
    df["_p"] = pd.to_numeric(df[pc], errors="coerce") if pc else 1.0
    out = pd.DataFrame(dict(cluster=df[_pick(df, GOLD_COLS["cluster"])].map(canon), source_id=df["_id"], prob=df["_p"]))
    out = out.dropna(subset=["source_id"]); out = out[out.prob >= min_prob]
    rep = dict(rows=len(out), prob_column=pc or "MISSING (all treated as 1.0)", min_prob=min_prob)
    return out, rep


# ----------------------------------------------------------------- unsupervised baselines (no labels used)
def sel_cone(g): return set(g.source_id.tolist())


def sel_sigclip(g, k=3.0, iters=6, pm_floor=0.3, plx_floor=0.05):
    X = g[["pmra", "pmdec", "parallax"]].to_numpy(float); ok = np.isfinite(X).all(1)
    if ok.sum() < 30: return set()
    lo, hi = np.percentile(X[ok, :2], [1, 99], axis=0)
    H, xe, ye = np.histogram2d(X[ok, 0], X[ok, 1], bins=40, range=[[lo[0], hi[0]], [lo[1], hi[1]]])
    i, j = np.unravel_index(np.argmax(H), H.shape); w = np.array([xe[1] - xe[0], ye[1] - ye[0]])
    c = np.array([(xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2])
    sel = ok & (np.abs(X[:, 0] - c[0]) <= 3 * w[0]) & (np.abs(X[:, 1] - c[1]) <= 3 * w[1])
    mad = lambda v: 1.4826 * np.median(np.abs(v - np.median(v)))
    for _ in range(iters):
        if sel.sum() < 10: break
        c = np.median(X[sel], axis=0); s = np.maximum([mad(X[sel, 0]), mad(X[sel, 1]), mad(X[sel, 2])], [pm_floor, pm_floor, plx_floor])
        new = ok & (np.abs(X - c) <= k * s).all(1)
        if new.sum() < 10 or (new == sel).all(): break
        sel = new
    return set(g.source_id[sel].tolist())


def sel_gmm(g, seed=0):
    from sklearn.mixture import GaussianMixture
    X = g[["pmra", "pmdec", "parallax"]].to_numpy(float); ok = np.isfinite(X).all(1)
    if ok.sum() < 50: return set()
    med = np.median(X[ok], 0); sc = 1.4826 * np.median(np.abs(X[ok] - med), 0) + 1e-9
    Z = (X[ok] - med) / sc
    gm = GaussianMixture(2, covariance_type="full", n_init=3, random_state=seed).fit(Z)
    comp = int(np.argmin([np.linalg.det(c) for c in gm.covariances_])); lab = gm.predict(Z) == comp
    idx = np.where(ok)[0][lab]
    return set(g.source_id.iloc[idx].tolist())


def sel_informed_box(g, pm_center, plx_center, pm_halfwidth, plx_halfwidth):
    """What an astronomer actually does: cone + a PM/parallax window around the cluster's PUBLISHED mean.
    Take the centre/widths from a DIFFERENT catalogue than the gold (e.g. CG2020 parameters vs HR23 members),
    otherwise the baseline is told the answer."""
    X = g[["pmra", "pmdec", "parallax"]].to_numpy(float)
    m = (np.abs(X[:, 0] - pm_center[0]) <= pm_halfwidth) & (np.abs(X[:, 1] - pm_center[1]) <= pm_halfwidth) & (np.abs(X[:, 2] - plx_center) <= plx_halfwidth)
    return set(g.source_id[m & np.isfinite(X).all(1)].tolist())


def sel_hdbscan(g, min_cluster_size=20):
    """Density-based baseline (the family of method behind Hunt & Reffert 2023). Picks the tightest cluster found."""
    from sklearn.cluster import HDBSCAN  # noqa
    X = g[["pmra", "pmdec", "parallax"]].to_numpy(float); ok = np.isfinite(X).all(1)
    if ok.sum() < 3 * min_cluster_size: return set()
    med = np.median(X[ok], 0); sc = 1.4826 * np.median(np.abs(X[ok] - med), 0) + 1e-9
    Z = (X[ok] - med) / sc
    lab = HDBSCAN(min_cluster_size=min_cluster_size, copy=True).fit_predict(Z)
    best, best_det = None, np.inf
    for l in set(lab) - {-1}:
        pts = Z[lab == l]
        if len(pts) < min_cluster_size: continue
        d = np.linalg.det(np.cov(pts.T) + 1e-9 * np.eye(3))
        if d < best_det: best, best_det = l, d
    if best is None: return set()
    return set(g.source_id.iloc[np.where(ok)[0][lab == best]].tolist())


# ----------------------------------------------------------------- id safety
GAIA_MAX = 2 ** 63 - 1


def drop_synthetic(df: pd.DataFrame, name="table"):
    """Real Gaia source_ids are < 2^63. Ids at or above that are synthetic fixtures (e.g. the benchmark-seeding script).
    Refuses float ids (precision already lost: only ~0.3% of Gaia-range ids survive float64) and drops synthetic rows."""
    if df.source_id.dtype.kind == "f":
        raise TypeError(f"{name}.source_id is float: ids are already corrupted. Read CSVs with dtype={{'source_id': str}} and convert to int.")
    ids = df.source_id.astype(object).map(int)
    keep = ids <= GAIA_MAX
    out = df.assign(source_id=ids)[keep.values].reset_index(drop=True)
    return out, int((~keep).sum())


# ----------------------------------------------------------------- evaluation
def _prf(pred, gold_u):
    tp = len(pred & gold_u)
    p = tp / len(pred) if pred else np.nan; r = tp / len(gold_u) if gold_u else np.nan
    f = 2 * p * r / (p + r) if (p == p and r == r and p + r > 0) else (0.0 if pred and gold_u else np.nan)
    return p, r, f


def evaluate_membership(stars: pd.DataFrame, edges: pd.DataFrame, gold: pd.DataFrame, min_gold=20, seed=0) -> dict:
    stars, n_syn_stars = drop_synthetic(stars, "stars"); edges, n_syn_edges = drop_synthetic(edges, "edges")
    stars = stars.assign(cluster=stars.cluster.map(canon)); edges = edges.assign(cluster=edges.cluster.map(canon))
    gold = gold.assign(cluster=gold.cluster.map(canon))          # idempotent: raw catalogue names ('Melotte_25') must not silently miss
    rng = np.random.default_rng(seed); methods = ["taarya_member_of_edges", "cone_only", "sigma_clip_pm_plx", "gmm_2comp", "hdbscan", "random_same_size_as_edges"]
    per, skipped = {}, []
    for cl, g in stars.groupby("cluster"):
        U = set(g.source_id.tolist()); G = set(gold.loc[gold.cluster == cl, "source_id"].astype("int64").tolist()); Gu = G & U
        if len(Gu) < min_gold:
            skipped.append(dict(cluster=cl, reason=f"only {len(Gu)} gold members in catalogue (need {min_gold})", gold_total=len(G))); continue
        E = set(edges.loc[edges.cluster == cl, "source_id"].tolist()) & U
        pred = {"taarya_member_of_edges": E, "cone_only": sel_cone(g), "sigma_clip_pm_plx": sel_sigclip(g), "gmm_2comp": sel_gmm(g, seed), "hdbscan": sel_hdbscan(g),
                "random_same_size_as_edges": (lambda L: {L[i] for i in rng.choice(len(L), size=min(len(E), len(L)), replace=False)})(sorted(U)) if E else set()}
        per[cl] = dict(n_cone=len(U), n_gold_in_cone=len(Gu), gold_coverage=round(len(Gu) / max(len(G), 1), 3),
                       cone_purity=round(len(Gu) / len(U), 3), jaccard_edges_vs_cone=round(len(E & U) / max(len(E | U), 1), 3),
                       **{m: dict(zip(("precision", "recall", "f1"), map(lambda v: None if v != v else round(v, 3), _prf(pred[m], Gu)))) for m in methods})
    agg = {m: {k: bootstrap_ci([v[m][k] for v in per.values() if v[m][k] is not None], min_n=MIN_UNITS) for k in ("precision", "recall", "f1")} for m in methods} if per else {}
    jac = [v["jaccard_edges_vs_cone"] for v in per.values()]
    seeding = bool(jac) and float(np.median(jac)) >= 0.9
    return dict(n_clusters=len(per), per_cluster=per, skipped=skipped, aggregate=agg,
                synthetic_rows_dropped=dict(stars=n_syn_stars, edges=n_syn_edges),
                member_of_is_cone_seeding=seeding, median_jaccard_edges_vs_cone=round(float(np.median(jac)), 3) if jac else None,
                verdict=("MEMBER_OF edges are indistinguishable from the seeding cone: they encode proximity, not membership"
                         if seeding else "MEMBER_OF differs from the cone; compare precision/recall below"),
                caution=(f"{len(per)} clusters < {MIN_UNITS}: descriptive only, no intervals reported; read per_cluster" if len(per) < MIN_UNITS else f"{len(per)} clusters; intervals are bootstrap over clusters"))


def rebuild_member_edges(gold: pd.DataFrame, stars: pd.DataFrame) -> pd.DataFrame:
    """Edges to load back into Neo4j: published members present in the catalogue, with probability as a property."""
    stars = stars.assign(cluster=stars.cluster.map(canon))
    m = gold.merge(stars[["cluster", "source_id"]].drop_duplicates(), on=["cluster", "source_id"])
    return m.assign(source_catalogue="published_membership")[["source_id", "cluster", "prob", "source_catalogue"]]


def export_neo4j_members(uri="bolt://localhost:7687", user="neo4j", password_env="NEO4J_PASSWORD", query=NEO4J_QUERY) -> pd.DataFrame:
    from neo4j import GraphDatabase
    with GraphDatabase.driver(uri, auth=(user, os.environ[password_env])) as d, d.session() as s:
        return pd.DataFrame([dict(r) for r in s.run(query)])


def run(stars_csv, edges_csv, gold_csv, id_system="dr3", min_prob=0.7, dr2_map_csv=None):
    gold, rep = load_gold(gold_csv, id_system, min_prob, pd.read_csv(dr2_map_csv) if dr2_map_csv else None)
    out = evaluate_membership(pd.read_csv(stars_csv), pd.read_csv(edges_csv), gold)
    out["gold_report"] = rep
    return out


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser()
    for a in ("stars", "edges", "gold"): ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--id-system", default="dr3"); ap.add_argument("--min-prob", type=float, default=0.7); ap.add_argument("--dr2-map")
    a = ap.parse_args(); print(json.dumps(run(a.stars, a.edges, a.gold, a.id_system, a.min_prob, a.dr2_map), indent=2, default=str))
