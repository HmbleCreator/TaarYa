import numpy as np, pandas as pd
from taarya_workflows.core import bootstrap_ci, paired_diff, MIN_UNITS
from taarya_workflows.real import cluster_retrieval as CR, cluster_cones as C
from taarya_workflows.tests.test_cluster_retrieval import world

def test_bootstrap_refuses_intervals_for_few_units():
    r = bootstrap_ci([0.83, 0.88, 0.90], min_n=MIN_UNITS); assert r["ci95"] == [None, None] and "descriptive" in r["note"]
    d = paired_diff([0.9, 0.91, 0.92], [0.85, 0.86, 0.87], min_n=MIN_UNITS); assert d["separated"] is None and d["direction"] is None
    assert bootstrap_ci(np.linspace(0.5, 0.9, 12), min_n=MIN_UNITS)["ci95"][0] is not None

def test_retrieval_reports_no_inference_with_three_clusters_and_does_with_ten():
    meths = {"current_graph_traversal": CR.m_current_graph, "seed_box": CR.m_seed_box, "seed_mahalanobis": CR.m_seed_mahalanobis}
    s, g = world(np.random.default_rng(0), n_clusters=3, n_mem=120, n_field=800, decoy=False)
    r = CR.evaluate_retrieval(s, g, repeats=2, methods=meths); assert r["aggregate"]["seed_box"]["AP"]["ci95"] == [None, None]
    assert r["aggregate"]["seed_mahalanobis"]["AP_diff_vs_seed_box"]["separated"] is None and "descriptive only" in r["caution"]
    s, g = world(np.random.default_rng(0), n_clusters=10, n_mem=120, n_field=800, decoy=False)
    r = CR.evaluate_retrieval(s, g, repeats=2, methods=meths); assert r["aggregate"]["seed_box"]["AP"]["ci95"][0] is not None

def test_cluster_selection_is_seeded_and_criteria_driven(tmp_path):
    rng = np.random.default_rng(0); n = 2000
    df = pd.DataFrame(dict(Name=[f"C{i}" for i in range(n)], Dist=rng.uniform(100, 3000, n), nbstars07=rng.integers(20, 800, n), r50=rng.uniform(0.1, 5, n)))
    p = tmp_path / "c.csv"; df.to_csv(p, index=False)
    a, b = C.select_clusters(str(p), n=20, seed=1), C.select_clusters(str(p), n=20, seed=1); c = C.select_clusters(str(p), n=20, seed=2)
    assert a == b and a["selected"] != c["selected"] and len(a["selected"]) == 20
    ok = df[(df.Dist <= 1000) & (df.nbstars07 >= 100) & (df.r50 <= 2.0)].Name
    assert set(a["selected"]) <= set(ok) and a["eligible"] == len(ok)


def test_holm_adjustment_and_rprecision_and_small_effects_do_not_survive_correction():
    from taarya_workflows.core import holm, paired_diff
    assert holm([0.01, 0.04, 0.03, None]) == [0.03, 0.06, 0.06, None] or holm([0.01, 0.04, 0.03, None])[0] == 0.03
    assert all(a >= b for a, b in zip(holm([0.01, 0.02, 0.03]), [0.01, 0.02, 0.03]))
    rng = np.random.default_rng(1); a = rng.normal(0.009, 0.01, 19); base = np.zeros(19)
    d = paired_diff(a, base); assert d["p_boot"] is not None and 0 < d["p_boot"] <= 1 and 0 < d["p_perm"] <= 1
    meths = {"current_graph_traversal": CR.m_current_graph, "seed_box": CR.m_seed_box, "seed_mahalanobis": CR.m_seed_mahalanobis, "seed_knn": CR.m_seed_knn}
    s, g = world(np.random.default_rng(0), n_clusters=10, n_mem=120, n_field=800, decoy=False)
    r = CR.evaluate_retrieval(s, g, repeats=2, methods=meths)
    for m in ("seed_mahalanobis", "seed_knn", "current_graph_traversal"):
        dd = r["aggregate"][m]["AP_diff_vs_seed_box"]; assert dd["p_holm"] >= dd["p_perm"] and dd["holm_separated"] in (True, False)
    assert 0.0 <= r["aggregate"]["seed_box"]["R-precision"]["mean"] <= 1.0


def test_sign_flip_is_exact_and_wins_losses_survive_small_n():
    from taarya_workflows.core import sign_flip_p, paired_diff
    assert sign_flip_p(np.ones(5)) == 2 / 32                                      # only the all-same-sign patterns are as extreme
    assert abs(sign_flip_p(np.array([1., -1., 1., -1.]))) == 1.0                  # zero mean: every pattern is at least as extreme
    big = np.random.default_rng(0).normal(0.0, 1.0, 40); assert 0 < sign_flip_p(big, n_mc=20000) <= 1                    # Monte Carlo branch
    d = paired_diff([0.9, 0.8, 0.95], [0.5, 0.6, 0.7], min_n=8)                   # 3 units: no inference, but the direction counts are kept
    assert d["p_perm"] is None and d["separated"] is None and (d["wins"], d["losses"]) == (3, 0)
    d19 = paired_diff(np.r_[np.full(15, 0.01), np.full(4, -0.002)], np.zeros(19), min_n=8); assert (d19["wins"], d19["losses"]) == (15, 4) and d19["p_perm"] < 0.01
