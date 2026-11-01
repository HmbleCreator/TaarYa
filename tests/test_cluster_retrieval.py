import numpy as np, pandas as pd, pytest
from taarya_workflows.real import cluster_retrieval as CR

def world(rng, n_clusters=4, n_field=3000, n_mem=250, spread=0.7, decoy=True):
    S, G, nid = [], [], 3_300_000_000_000_000_000
    for c in range(n_clusters):
        pm = rng.uniform(-30, 30, 2); plx = rng.uniform(3, 9)
        pmra = np.r_[rng.normal(pm[0], spread, n_mem), rng.normal(0, 15, n_field)]; pmdec = np.r_[rng.normal(pm[1], spread, n_mem), rng.normal(0, 15, n_field)]
        p = np.r_[rng.normal(plx, 0.15, n_mem), np.abs(rng.normal(3, 2, n_field)) + .3]
        if decoy:                                                         # co-moving field decoys: same PM, different parallax
            k = 150; pmra[n_mem:n_mem + k] = rng.normal(pm[0], 1.5, k); pmdec[n_mem:n_mem + k] = rng.normal(pm[1], 1.5, k); p[n_mem:n_mem + k] = plx + rng.choice([-1.2, 1.2], k) + rng.normal(0, .2, k)
        ids = nid + c * 10**7 + np.arange(n_mem + n_field)
        S.append(pd.DataFrame(dict(cluster=f"C{c}", source_id=ids, pmra=pmra, pmdec=pmdec, parallax=p)))
        G.append(pd.DataFrame(dict(cluster=f"C{c}", source_id=ids[:n_mem], prob=rng.uniform(0.7, 1.0, n_mem))))
    return pd.concat(S, ignore_index=True), pd.concat(G, ignore_index=True)

def test_seed_methods_beat_current_graph_which_is_random_order():
    rng = np.random.default_rng(0); s, g = world(rng); r = CR.evaluate_retrieval(s, g, repeats=2)
    a = r["aggregate"]; purity = np.mean([v["cone_purity"] for v in r["per_cluster"].values()])
    assert abs(a["current_graph_traversal"]["AP"]["mean"] - purity) < 0.03          # unordered cone == base rate
    for m in ("seed_box", "seed_mahalanobis", "seed_knn", "graph_ppr"): assert a[m]["AP"]["mean"] > 0.7
    assert a["seed_mahalanobis"]["AP_diff_vs_seed_box"]["mean"] is not None

def test_seeds_are_excluded_from_candidates():
    """A method that cheats by ranking the seeds first must get NO credit: seeds are removed from the candidate list.
    If they were left in, putting 10 gold seeds on top would lift AP well above the base rate."""
    rng = np.random.default_rng(1); s, g = world(rng, n_clusters=3, n_mem=60, n_field=600, decoy=False)
    def cheat(Z, seeds, rng_):
        sc = rng_.random(len(Z)); sc[seeds] = 10.0; return sc
    r = CR.evaluate_retrieval(s, g, n_seeds=10, repeats=3, methods={"cheat": cheat, "current_graph_traversal": CR.m_current_graph})
    ap_c, ap_r = r["aggregate"]["cheat"]["AP"]["mean"], r["aggregate"]["current_graph_traversal"]["AP"]["mean"]
    assert abs(ap_c - ap_r) < 0.03 and ap_c < 0.15

def test_too_few_hidden_members_is_skipped_not_scored():
    rng = np.random.default_rng(2); s, g = world(rng, n_clusters=1, n_mem=25, n_field=300, decoy=False)
    r = CR.evaluate_retrieval(s, g, n_seeds=10, min_hidden=20); assert r["n_clusters"] == 0 and r["skipped"]

def test_float_ids_refused():
    rng = np.random.default_rng(3); s, g = world(rng, n_clusters=1); s["source_id"] = s.source_id.astype(float)
    with pytest.raises(TypeError): CR.evaluate_retrieval(s, g)

