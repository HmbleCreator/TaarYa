import numpy as np, pandas as pd
from taarya_workflows.core import bootstrap_ci, paired_diff, MIN_UNITS
from taarya_workflows.real import cluster_retrieval as CR, cluster_cones as C
from tests.test_cluster_retrieval import world

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

