import json, re, numpy as np, pandas as pd
from taarya_workflows.real import run_real_eval as R, make_tables as T
from taarya_workflows.tests.test_cluster_retrieval import world
from taarya_workflows.tests.test_real import _synthetic_table

def _results():
    rng = np.random.default_rng(0); s, g = world(rng, n_clusters=3, n_mem=200, n_field=2000)
    s["cluster"] = s.cluster.map({"C0": "Melotte_22 (Pleiades)", "C1": "NGC_2516", "C2": "NGC_2632 (Praesepe)"}); g["cluster"] = g.cluster.map({"C0": "Melotte_22 (Pleiades)", "C1": "NGC_2516", "C2": "NGC_2632 (Praesepe)"})
    edges = s[["cluster", "source_id"]]; s["source_id"] = s.source_id.astype(str); g["source_id"] = g.source_id.astype(str); edges = edges.assign(source_id=edges.source_id.astype(str))
    toi = _synthetic_table(np.random.default_rng(1), 400)
    return R.evaluate_all(s, g, edges, toi, repeats=2)

def test_pipeline_runs_and_tables_match_json_exactly(tmp_path):
    res = _results(); assert {"membership", "retrieval", "toi"} <= set(res)
    made = T.build_tex(res, tmp_path)
    assert {"numbers.tex", "membership_diag.tex", "membership_methods.tex", "retrieval.tex", "toi.tex"} <= set(made)
    nums = (tmp_path / "numbers.tex").read_text()
    d = res["toi"]["delta_auc_with_vs_without_neighbour"]
    assert f"{{{d['mean']:.3f}}}" in nums and "\\toiDeltaCI" in nums
    assert f"{{{res['membership']['median_jaccard_edges_vs_cone']:.3f}}}" in nums
    toi_tex = (tmp_path / "toi.tex").read_text()
    assert res["toi"]["verdict"].split(" (")[0].replace("_", "\\_")[:25] in toi_tex                    # verdict flows into the caption

def test_latex_special_characters_are_escaped_and_no_raw_underscores_in_names(tmp_path):
    res = _results(); T.build_tex(res, tmp_path)
    for f in ("retrieval.tex", "membership_methods.tex"):
        body = (tmp_path / f).read_text().split("\\midrule")[1]
        assert not re.search(r"(?<!\\)_", body), f                                                       # e.g. seed_box must be seed\_box
    assert "Pleiades" in (tmp_path / "membership_diag.tex").read_text() or "pleiades" in (tmp_path / "membership_diag.tex").read_text()

def test_code_hash_changes_when_code_changes(tmp_path):
    (tmp_path / "a.py").write_text("x=1"); h1 = R.code_hash(tmp_path); (tmp_path / "a.py").write_text("x=2"); assert R.code_hash(tmp_path) != h1
    assert R.versions()["numpy"] and isinstance(R.versions()["python"], str)
