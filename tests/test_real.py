import numpy as np, pandas as pd, pytest
from taarya_workflows.real import exofop as X
from taarya_workflows.real import binaries as Bn
from taarya_workflows import blended_eb as B
from taarya_workflows.gaia_triage import make_field, evaluate_scorers, b_ruwe, b_ruwe_offset

def toi_frame(n=10):
    return pd.DataFrame(dict(toi=np.arange(n)+100.01, tid=np.arange(n)+1, tfopwg_disp=["CP","FP","PC","FA","KP","fp"," CP","APC","FP","CP"][:n],
        pl_orbper=3.0, pl_trandep=np.linspace(500,5000,n), pl_trandurh=2.0, st_tmag=10.0,
        ra=[10.0]*n, dec=[-5.0]*n))

def test_normalise_labels_and_tolerant_columns():
    d = X.normalise(toi_frame())
    assert list(d.label[:6]) == [0, 1, -1, -1, 0, 1]          # CP,FP,PC,FA,KP,fp
    exofop_style = toi_frame().rename(columns={"tid":"TIC ID","tfopwg_disp":"TFOPWG Disposition","pl_trandep":"Depth (ppm)",
                                               "st_tmag":"TESS Mag","ra":"RA","dec":"Dec"})
    exofop_style["RA"] = "00:40:00"; exofop_style["Dec"] = "-05:00:00"
    d2 = X.normalise(exofop_style); assert abs(d2.ra[0] - 10.0) < 1e-6 and abs(d2.dec[0] + 5.0) < 1e-6
    with pytest.raises(KeyError): X.normalise(toi_frame().drop(columns=["tfopwg_disp"]))

def test_explain_score_hand_computed():
    nb = pd.DataFrame(dict(sep_arcsec=[0.5, 10.0], G=[10.2, 12.0]))      # first = the target itself, excluded
    fr = np.exp(-0.5*(10/21)**2) * 10**(-0.4*(12-10)); exp = np.log10(0.8*fr/(1+fr)/(1000e-6))
    assert X.explain_score(nb, 10.0, 1000.0) == pytest.approx(exp)
    assert X.explain_score(pd.DataFrame(dict(sep_arcsec=[0.4], G=[10.1])), 10.0, 1000.0) == -3.0
    assert np.isnan(X.explain_score({"error": "x"}, 10.0, 1000.0))

def _synthetic_table(rng, n, informative=True):
    rows = []
    for i in range(n):
        planet = rng.random() < 0.5
        if planet or not informative:
            fr, c, depth = B.one_planet(rng, 25.0)
        else:
            r = B.one_beb(rng, 25.0)
            if r is None: continue
            fr, c, depth = r
        best = 0.8 * fr[c].max() / (1 + fr.sum()) if c.any() else 1e-12
        rows.append(dict(tic=i, label=0 if planet else 1, depth_ppm=depth*1e6, score=np.log10(max(best,1e-12)/depth)))
    return pd.DataFrame(rows)

def test_evaluate_null_is_not_separated():
    """A single seed fails ~5% of the time by construction, so check the behaviour across many null datasets."""
    seps, aucs = 0, []
    for seed in range(8):
        rng = np.random.default_rng(seed); d = _synthetic_table(rng, 400, informative=False)
        d["label"] = rng.integers(0, 2, len(d))                              # labels unrelated to any feature
        r = X.evaluate(d, B=150, seed=seed); aucs.append(r["depth+neighbour_cv"]["auc"])
        seps += r["delta_auc_combined_minus_depth"]["separated"]
    assert abs(np.mean(aucs) - 0.5) < 0.03 and seps <= 3

def test_evaluate_positive_control():
    rng = np.random.default_rng(1); d = _synthetic_table(rng, 800, informative=True)
    r = X.evaluate(d, B=300)
    assert r["neighbour_only_cv"]["auc"] > 0.6 and r["n"]["false_positives"] > 50

def test_binary_loader_roundtrip_and_circular_guard(tmp_path):
    rng = np.random.default_rng(3); rows = []
    for fid in range(8):
        f = make_field(rng, 1200); n = 1200
        M = f["G"] - 5*np.log10(1000/f["parallax"]/10)                    # absolute mag implied by observed parallax
        rows.append(pd.DataFrame(dict(field_id=fid, source_id=fid*10**6+np.arange(n), parallax=f["parallax"], parallax_over_error=20.0,
            pmra=f["pmra"], pmdec=f["pmdec"], G=f["G"], bp_rp=f["bp_rp"], ruwe=f["ruwe"], truth=f["is_binary"])))
    df = pd.concat(rows, ignore_index=True); p = tmp_path/"fields.csv"; df.to_csv(p, index=False)
    ids = set(df.source_id[df.truth == 1])
    out = Bn.run(str(p), {"sb9": ids})
    assert out["label_report"]["sb9"]["matched"] == len(ids)
    res = out["results"]; assert res["baseline_sort_RUWE"]["AP"]["mean"] > res["random"]["AP"]["mean"] + 0.2
    refused = Bn.run(str(p), {"nss_astrometric": ids}); assert "error" in refused or "REFUSED" in str(refused["label_report"])
    assert "REFUSED" in str(Bn.run(str(p), {"made_up": ids}).get("label_report"))

def test_ms_offset_positive_for_brighter_stars():
    rng = np.random.default_rng(5); n = 3000; bp = rng.uniform(0.5, 2.5, n); M = 2 + 3*(bp-0.5) + rng.normal(0, .1, n)
    M[:300] -= 0.7; plx = np.full(n, 5.0); G = M + 5*np.log10(1000/plx) - 5
    df = pd.DataFrame(dict(G=G, parallax=plx, parallax_over_error=30.0, bp_rp=bp, ruwe=np.r_[np.full(300, 1.0), np.full(n-300, 1.0)]))
    off = Bn.compute_ms_offset(df); assert off[:300].mean() > off[300:].mean() + 0.4


def test_postgres_fetch_distinguishes_no_coverage_from_no_neighbours():
    cover = {"n": 5}
    def rq(sql, params):
        if sql.startswith("SELECT count"): return [(cover["n"],)]
        return CONE["rows"]
    CONE = {"rows": []}
    fetch = X.fetch_neighbours_postgres(run_query=rq)
    with pytest.raises(LookupError): fetch(10.0, 5.0)                      # empty cone, no catalogue around -> unusable
    cover["n"] = 500
    assert fetch(10.0, 5.0).empty                                           # empty cone inside coverage -> genuinely no neighbours
    CONE["rows"] = [(12.0, 8.5), (15.0, 30.0)]
    assert list(fetch(10.0, 5.0).columns) == ["G", "sep_arcsec"]
    cache = X.cached_neighbours(pd.DataFrame(dict(tic=[1], ra=[10.0], dec=[5.0])), lambda ra, dec: (_ for _ in ()).throw(LookupError("x")),
                                "/tmp/_nb_cache_test.json", sleep=0)
    assert "error" in cache["1"] and np.isnan(X.explain_score(cache["1"], 10.0, 1000.0))


def test_no_phantom_gain_when_depth_is_anticorrelated_and_neighbour_is_useless():
    """Regression for the smoke-test bug: depth anti-correlated with FP + uninformative neighbour score.
    A fixed-sign depth baseline would give AUC<0.5 and a spurious 'gain'; sign-learning baselines must not."""
    rng = np.random.default_rng(4); n = 500; y = rng.integers(0, 2, n)
    d = pd.DataFrame(dict(tic=np.arange(n), label=y, depth_ppm=10 ** (3.2 - 0.5 * y + rng.normal(0, 0.4, n)),
                          score=rng.normal(0, 1, n)))
    r = X.evaluate(d, B=400)
    assert r["raw_depth_auc_fixed_sign"] < 0.4 and r["warnings"]
    assert r["depth_only_cv"]["auc"] > 0.65                                   # baseline learned the flipped sign
    assert not r["delta_auc_combined_minus_depth"]["separated"] or r["delta_auc_combined_minus_depth"]["mean"] < 0.03


def test_target_brightness_confound_is_not_mistaken_for_vetting_signal():
    """FP label depends ONLY on target Tmag (a follow-up selection effect). The neighbour feature tracks Tmag through G - Tmag but has
    no independent information. Without Tmag in the baseline it looks informative; with it, it must not."""
    rng = np.random.default_rng(8); n = 700; tmag = rng.uniform(8, 14, n); y = (tmag + rng.normal(0, 1.2, n) > 11).astype(int)
    logdip = []
    for tm in tmag:
        nb = pd.DataFrame(dict(sep_arcsec=rng.uniform(5, 40, 6), G=rng.uniform(14, 19, 6)))
        logdip.append(X.neighbour_logdip(nb, tm))
    d = pd.DataFrame(dict(tic=np.arange(n), label=y, depth_ppm=10 ** rng.normal(3.3, 0.3, n), tmag=tmag, logdip=logdip, score=logdip))
    naive = X.evaluate(d.drop(columns=["tmag"]), B=300)               # baseline forgot Tmag
    fair = X.evaluate(d, B=300)
    assert naive["delta_auc_with_vs_without_neighbour"]["separated"] and naive["delta_auc_with_vs_without_neighbour"]["mean"] > 0.08
    assert not (fair["delta_auc_with_vs_without_neighbour"]["separated"] and fair["delta_auc_with_vs_without_neighbour"]["mean"] > 0.03)


def test_tiny_but_significant_gain_is_labelled_negligible():
    rng = np.random.default_rng(3); n = 3000; tmag = rng.uniform(8, 14, n); y = (rng.random(n) < 0.5).astype(int)
    feat = rng.normal(0, 1, n) + 0.12 * y                       # real but very weak information
    d = pd.DataFrame(dict(tic=np.arange(n), label=y, depth_ppm=10 ** rng.normal(3.3, 0.3, n), tmag=tmag, logdip=feat, score=feat))
    r = X.evaluate(d, B=300)
    if r["delta_auc_with_vs_without_neighbour"]["separated"]:
        assert "NEGLIGIBLE" in r["verdict"] or r["delta_auc_with_vs_without_neighbour"]["mean"] >= X.PRACTICAL_DELTA_AUC
    assert "matched_operating_point" in r and "operating_points_note" in r
