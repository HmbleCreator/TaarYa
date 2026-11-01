import numpy as np, pandas as pd, pytest
from taarya_workflows.real import membership as M

def cone(rng, name, id0, n_field=3000, n_mem=300, pm=(20., -30.), plx=8.0):
    mem = np.arange(n_mem) < n_mem
    pmra = np.r_[rng.normal(pm[0], .7, n_mem), rng.normal(0, 15, n_field)]; pmdec = np.r_[rng.normal(pm[1], .7, n_mem), rng.normal(0, 15, n_field)]
    p = np.r_[rng.normal(plx, .15, n_mem), np.abs(rng.normal(3, 2, n_field)) + .3]
    df = pd.DataFrame(dict(cluster=name, source_id=id0 + np.arange(n_mem + n_field), pmra=pmra, pmdec=pmdec, parallax=p))
    return df, set(df.source_id[:n_mem])

def world(edges_mode="cone", seed=0):
    rng = np.random.default_rng(seed); S, G, E = [], [], []
    for i, (nm, pm, plx) in enumerate([("Hyades", (20, -30), 8.0), ("Pleiades", (20, -45), 7.3), ("Praesepe", (-36, -13), 5.4), ("IC 2391", (-25, 23), 6.6)]):
        d, g = cone(rng, nm, 10**9 * (i + 1), pm=pm, plx=plx); S.append(d); G += [(M.canon(nm), s, 0.95) for s in g]
        E.append(d[["cluster", "source_id"]] if edges_mode == "cone" else d.loc[d.source_id.isin(g), ["cluster", "source_id"]])
    return pd.concat(S, ignore_index=True), pd.concat(E, ignore_index=True), pd.DataFrame(G, columns=["cluster", "source_id", "prob"])

def test_edges_equal_cone_is_detected_without_gold():
    s, e, g = world("cone"); r = M.evaluate_membership(s, e, g)
    assert r["member_of_is_cone_seeding"] and r["median_jaccard_edges_vs_cone"] > 0.99
    assert r["aggregate"]["taarya_member_of_edges"]["precision"]["mean"] < 0.15          # cluster is ~9% of the cone

def test_true_edges_are_not_flagged():
    s, e, g = world("true"); r = M.evaluate_membership(s, e, g)
    assert not r["member_of_is_cone_seeding"] and r["aggregate"]["taarya_member_of_edges"]["f1"]["mean"] > 0.99

def test_unsupervised_baselines_recover_separated_clusters_and_null_does_not():
    s, e, g = world("cone"); a = M.evaluate_membership(s, e, g)["aggregate"]
    assert a["sigma_clip_pm_plx"]["f1"]["mean"] > 0.8 and a["gmm_2comp"]["f1"]["mean"] > 0.8 and a["hdbscan"]["f1"]["mean"] > 0.8
    assert a["random_same_size_as_edges"]["f1"]["mean"] < 0.25

def test_dr2_ids_refused_without_map():
    with pytest.raises(ValueError): M.load_gold(pd.DataFrame(dict(Source=[1234567], Cluster=["x"], proba=[.9])), id_system="dr2")
    mp = pd.DataFrame(dict(dr2_source_id=[1234567], dr3_source_id=[7654321]))
    g, _ = M.load_gold(pd.DataFrame(dict(Source=[1234567], Cluster=["x"], proba=[.9])), id_system="dr2", dr2_to_dr3=mp); assert int(g.source_id[0]) == 7654321

def test_alias_and_column_tolerance_and_prob_filter():
    assert M.canon("Melotte_25") == M.canon("Hyades") == "hyades" and M.canon("NGC 2632") == "praesepe"
    hr = pd.DataFrame(dict(GaiaDR3=["Gaia DR3 1000000001", "Gaia DR3 1000000002"], Name=["Melotte_25", "Melotte_25"], Prob=[0.95, 0.4]))
    g, rep = M.load_gold(hr, "dr3", 0.7); assert list(g.source_id.astype(int)) == [1000000001] and g.cluster[0] == "hyades"
    g2, rep2 = M.load_gold(pd.DataFrame(dict(source_id=[1000000001], cluster=["Hyades"])), "dr3"); assert "MISSING" in rep2["prob_column"]
    with pytest.raises(KeyError): M.load_gold(pd.DataFrame(dict(foo=[1])), "dr3")

def test_rebuild_edges_and_small_gold_skipped():
    s, e, g = world("cone"); out = M.rebuild_member_edges(g, s)
    assert set(out.columns) == {"source_id", "cluster", "prob", "source_catalogue"} and len(out) == len(g)
    r = M.evaluate_membership(s, e, g.iloc[:5], min_gold=20); assert r["n_clusters"] == 0 and r["skipped"]


def test_float_ids_refused_and_synthetic_ids_dropped_and_random_baseline_exact():
    s, e, g = world("cone")
    s2 = s.copy(); s2["source_id"] = s2.source_id.astype(float)
    with pytest.raises(TypeError): M.evaluate_membership(s2, e, g)
    big = pd.DataFrame(dict(cluster="Hyades", source_id=[2**63 + 11, 2**63 + 12], pmra=0., pmdec=0., parallax=1.))
    s3 = pd.concat([s, big], ignore_index=True); e3 = pd.concat([e, big[["cluster", "source_id"]]], ignore_index=True)
    s3["source_id"] = s3.source_id.astype(object); e3["source_id"] = e3.source_id.astype(object)
    r = M.evaluate_membership(s3, e3, g)
    assert r["synthetic_rows_dropped"] == dict(stars=2, edges=2)
    h = r["per_cluster"]["hyades"]
    # edges == cone, so a same-size random pick is the whole cone: identical to cone_only (this failed when ids went through float64)
    assert h["random_same_size_as_edges"] == h["cone_only"] == h["taarya_member_of_edges"]

def test_informed_box_baseline_is_strong_on_separated_cluster():
    rng = np.random.default_rng(0); d, g = cone(rng, "Hyades", 10**9)
    p, r, f = M._prf(M.sel_informed_box(d, (20., -30.), 8.0, 3.0, 1.0), g); assert p > 0.8 and r > 0.95
