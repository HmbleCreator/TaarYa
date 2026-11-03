import json, numpy as np, pandas as pd
from taarya_workflows.real import cone_sample_audit as A

ADQL = "SELECT TOP 60000 source_id FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.6f},{dec:.6f},{r:.6f})) AND parallax_over_error >= 5.0 AND phot_g_mean_mag <= 16.0"

def build(tmp, bad_cut=False, short=False, crowded_skips=True):
    rng = np.random.default_rng(0); man = dict(clusters={}); names = [f"K_{i}" for i in range(14)]; rows = []
    for i, n in enumerate(names):
        trunc = i >= 8; ra, dec = (rng.uniform(250, 290), rng.uniform(-5, 5)) if (trunc and crowded_skips) else (rng.uniform(0, 360), rng.uniform(30, 70))
        q = ADQL.format(ra=ra, dec=dec, r=1.0) + (" AND ruwe < 1.4" if (bad_cut and i == 3) else "")
        man["clusters"][n] = dict(ra0=ra, dec0=dec, radius_deg=1.0, adql=q, n_cone=60000 if trunc else 9000, status="SKIPPED: row cap hit" if trunc else "ok",
                                  member_coverage=0.8, n_published_in_cone=150)
        rows += [dict(Name=n, GaiaDR3=str(3_000_000_000_000_000_000 + i * 10**6 + j), RA_ICRS=ra, DE_ICRS=dec, Prob=0.9) for j in range(150 if not (short and i == 2) else 60)]
    (tmp / "manifest.json").write_text(json.dumps(man)); pd.DataFrame(dict(Name=names, Dist50=300, nbstars07=150, r50=1.0, Type="o")).to_csv(tmp / "clusters.csv", index=False)
    pd.DataFrame(rows).to_csv(tmp / "members.csv", index=False); (tmp / "selection.json").write_text(json.dumps(dict(selected=names + ["DROPPED_1"])))

def test_clean_sample_passes_but_flags_crowding_bias_and_dropped_clusters(tmp_path):
    build(tmp_path); r = A.audit(tmp_path, tmp_path / "selection.json", tmp_path / "clusters.csv", tmp_path / "members.csv")
    assert r["passed"] and r["adql_forms"] == 1 and r["n_evaluable"] == 8 and r["n_skipped_truncated"] == 6 and r["dropped_before_cones"] == ["DROPPED_1"]
    assert r["abs_b_median"]["skipped_truncated"] < r["abs_b_median"]["kept"] and any("uncrowded" in w for w in r["warnings"])

def test_nonuniform_cuts_and_truncated_member_download_are_hard_failures(tmp_path):
    build(tmp_path, bad_cut=True); r = A.audit(tmp_path, tmp_path / "selection.json")
    assert not r["passed"] and any("ADQL forms" in h for h in r["hard_failures"])
    build(tmp_path, short=True); r = A.audit(tmp_path, tmp_path / "selection.json", tmp_path / "clusters.csv", tmp_path / "members.csv")
    assert not r["passed"] and "K_2" in r["member_shortfall"] and any("truncated" in h for h in r["hard_failures"])
