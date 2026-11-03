"""
Gaia triage workflows: (a) unresolved-binary search, (b) high-velocity / kinematic outliers.

Ground truth is a LATENT physical flag (is this a binary? is v_t > 220 km/s?) that the
generator uses to *produce* noisy features. Labels are therefore independent of every
threshold the rankers apply -- unlike the paper's earlier threshold-defined labels.

Real data: `evaluate_scorers(fields, label_key, scorers)` takes any list of dicts of equal-length
numpy arrays with the keys used below, so El-Badry binaries / Gaia NSS orbits / published HVS lists
can be dropped in without touching the code.
"""
from __future__ import annotations
import numpy as np
from .core import (Workflow, Claim, rank_by_score, average_precision, precision_at_k, ndcg_at_k,
                   bootstrap_ci, paired_diff)

# ---- TaarYa discovery ranker: weights from Table 1 of the manuscript ----------------------
PROFILES = {
    "strict":     dict(ruwe_high=14., ruwe_elev=8.,  ruwe_tight=1.5, color=10.,  mot_high=14., mot_mid=7., bright=5.),
    "balanced":   dict(ruwe_high=16., ruwe_elev=9.,  ruwe_tight=2.0, color=10.5, mot_high=12., mot_mid=6., bright=5.5),
    "aggressive": dict(ruwe_high=18., ruwe_elev=11., ruwe_tight=2.5, color=11.5, mot_high=14., mot_mid=7., bright=6.5),
}


def taarya_score(f: dict, profile: str = "balanced", extra_offset_weight: float = 0.0) -> np.ndarray:
    """Vectorised S2-S5 of the paper's ranker. S1/S6/S7 are constants for single-catalogue
    samples with no neighbour counts, so they cannot affect ordering and are omitted."""
    p = PROFILES[profile]
    r, c, g = f["ruwe"], f["bp_rp"], f["G"]
    pm = np.hypot(f["pmra"], f["pmdec"]); d = 1000.0 / np.clip(f["parallax"], 1e-3, None)
    s = np.where(r >= 2.0, p["ruwe_high"], np.where(r >= 1.4, p["ruwe_elev"], np.where(r < 0.9, p["ruwe_tight"], 0.0)))
    s = s + np.where((c <= -0.1) | (c >= 2.8), p["color"], 0.0)
    s = s + np.where(pm >= 80, p["mot_high"], np.where(pm >= 40, p["mot_mid"], 0.0))
    s = s + np.where(((g <= 10) & (d >= 500)) | ((g >= 16) & (d <= 50)), p["bright"], 0.0)
    if extra_offset_weight:                                   # proposed S8: photometric binary-sequence offset
        s = s + extra_offset_weight * (f["ms_offset_obs"] >= 0.3)
    return np.minimum(s, 100.0)


# ---- baselines an astronomer can run in TOPCAT (column filters + sort) -----------------------
def b_random(f, rng): return rng.random(len(f["ruwe"]))
def b_ruwe(f, rng): return f["ruwe"]                                          # "sort by RUWE"
def b_ruwe_offset(f, rng):                                                    # two manual column criteria
    return np.maximum(f["ruwe"] - 1, 0) / 0.4 + np.maximum(f["ms_offset_obs"], 0) / 0.3
def b_pm(f, rng): return np.hypot(f["pmra"], f["pmdec"])                      # "sort by proper motion"
def b_vt(f, rng):                                                             # tangential velocity from PM/parallax
    return 4.74 * np.hypot(f["pmra"], f["pmdec"]) / np.clip(f["parallax"], 1e-3, None)


# ---- synthetic Gaia-like fields with latent truth --------------------------------------------
def make_field(rng, n=2500, contam=0.04, bin_frac=0.25) -> dict:
    d = np.exp(rng.normal(np.log(300), 0.7, n)).clip(30, 2500)               # pc
    plx = 1000.0 / d
    bp_rp = np.clip(rng.normal(1.2, 0.6, n), -0.3, 3.6)
    kind = rng.choice(4, n, p=[0.94, 0.02, 0.03, 0.01])                       # MS, WD, giant, halo
    bp_rp = np.where(kind == 1, rng.uniform(-0.3, 0.6, n), bp_rp)
    bp_rp = np.where(kind == 2, rng.uniform(1.0, 3.0, n), bp_rp)
    MG = 2.5 + 3.2 * (bp_rp - 0.3)
    MG = np.where(kind == 1, 11 + rng.normal(0, 1, n), MG)
    MG = np.where(kind == 2, 0.5 + rng.normal(0, 0.7, n), MG)

    # --- binaries (latent label) ---
    is_bin = (rng.random(n) < bin_frac) & (kind != 1)
    q = rng.uniform(0.3, 1.0, n)
    L2_L1 = q ** 3.5
    dm = 2.5 * np.log10(1 + L2_L1) * is_bin                                   # true brightening
    a_au = 10 ** rng.uniform(np.log10(0.05), np.log10(300), n)
    M1 = np.clip(1.5 - 0.5 * bp_rp, 0.15, 2.0)
    P_yr = np.sqrt(a_au ** 3 / (M1 * (1 + q)))
    lfrac = L2_L1 / (1 + L2_L1)
    theta = a_au * plx * np.abs(q / (1 + q) - lfrac)                          # photocentre wobble (mas)
    G = MG - dm + 5 * np.log10(d / 10)
    sigma_al = np.clip(0.05 * 10 ** (0.15 * (G - 13)), 0.03, 0.6)
    vis = 1 / (1 + (P_yr / 12) ** 2) / (1 + (0.1 / np.maximum(P_yr, 1e-3)) ** 2)
    ruwe = np.exp(rng.normal(0, 0.07, n)) + is_bin * np.clip(theta / sigma_al, 0, 6) * vis
    ruwe = ruwe + (rng.random(n) < contam) * rng.uniform(0.5, 4.0, n)         # non-binary contaminants (crowding, bad fits)
    ruwe = np.clip(ruwe, 0.7, 12)
    ms_off = (dm + rng.normal(0, 0.25, n))                                     # offset above the MS ridge; realistic scatter

    # --- kinematics (latent label) ---
    vt = np.abs(rng.normal(30, 25, n))
    vt = np.where(rng.random(n) < 0.08, rng.uniform(90, 215, n), vt)          # thick-disc-like tail, NOT labelled fast
    fast = (kind == 3) | (rng.random(n) < 0.02)
    vt = np.where(fast, rng.uniform(220, 450, n), vt)
    plx_err = np.clip(0.02 * 10 ** (0.2 * (G - 15)), 0.015, 0.8)               # mas, grows toward faint magnitudes
    plx_obs = np.clip(plx + rng.normal(0, 1, n) * plx_err, 0.05, None)
    pm_tot = vt / (4.74 * (d / 1000.0))
    ang = rng.uniform(0, 2 * np.pi, n)
    return dict(ruwe=ruwe, bp_rp=bp_rp, G=G, parallax=plx_obs, ms_offset_obs=ms_off,
                pmra=pm_tot * np.cos(ang) + rng.normal(0, 0.1, n), pmdec=pm_tot * np.sin(ang) + rng.normal(0, 0.1, n),
                is_binary=is_bin.astype(int), is_fast=fast.astype(int))


def paper_style_labels(f) -> np.ndarray:
    """Threshold-defined 'anomaly' labels like the earlier ablation used (RUWE/colour/PM cuts)."""
    pm = np.hypot(f["pmra"], f["pmdec"])
    return ((f["ruwe"] > 1.4) | (f["bp_rp"] <= -0.1) | (f["bp_rp"] >= 2.8) | (pm > 40)).astype(int)


# ---- v2: calibrated, continuous, task-specific scorers (fit on train fields, scored on held-out fields) ----
def _bin_features(f):
    return np.column_stack([np.log(f["ruwe"]), np.maximum(f["ruwe"] - 1.4, 0), np.maximum(f["ms_offset_obs"], 0)])


def _kin_features(f):
    vt = 4.74 * np.hypot(f["pmra"], f["pmdec"]) / np.clip(f["parallax"], 1e-3, None)
    return np.column_stack([np.log1p(vt), vt / 100.0])


def fit_logistic(train_fields, label_key, featurize):
    from sklearn.linear_model import LogisticRegression
    X = np.vstack([featurize(f) for f in train_fields]); y = np.concatenate([f[label_key] for f in train_fields])
    return LogisticRegression(C=1.0, max_iter=500).fit(X, y)


# ---- evaluation core ---------------------------------------------------------------------------
def evaluate_scorers(fields, label_fn, scorers: dict, baseline: str, k: int = 100, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    per = {name: dict(ap=[], pk=[], ndcg=[]) for name in scorers}
    for f in fields:
        y = label_fn(f)
        if y.sum() == 0:
            continue
        for name, fn in scorers.items():
            order = rank_by_score(fn(f, rng), rng)
            rel = y[order]
            per[name]["ap"].append(average_precision(rel)); per[name]["pk"].append(precision_at_k(rel, k))
            per[name]["ndcg"].append(ndcg_at_k(rel, k))
    out = {}
    for name, m in per.items():
        out[name] = dict(AP=bootstrap_ci(m["ap"]), **{f"P@{k}": bootstrap_ci(m["pk"])}, **{f"nDCG@{k}": bootstrap_ci(m["ndcg"])})
        if name != baseline:
            out[name]["AP_diff_vs_" + baseline] = paired_diff(m["ap"], per[baseline]["ap"])
    return out


class GaiaBinaryTriage(Workflow):
    name = "gaia_binary_triage"
    ground_truth = "latent binary flag (synthetic); drop-in: El-Badry+21 binaries, Gaia DR3 NSS orbital solutions"
    baseline = "TOPCAT: sort by RUWE; or RUWE + photometric-offset column criteria"
    claim_ceiling = Claim.CANDIDATE
    evidence_level = "synthetic"

    def _run(self, rng, n_fields, n, contam, bin_frac, seed):
        fields = [make_field(rng, n, contam, bin_frac) for _ in range(n_fields)]
        tr, te = fields[: n_fields // 2], fields[n_fields // 2:]            # split by FIELD, never by row
        lr = fit_logistic(tr, "is_binary", _bin_features)
        scorers = {
            "random": b_random, "baseline_sort_RUWE": b_ruwe, "baseline_RUWE+offset_columns": b_ruwe_offset,
            "taarya_v1_balanced": lambda f, r: taarya_score(f, "balanced"),
            "taarya_v1_strict": lambda f, r: taarya_score(f, "strict"),
            "taarya_v1_balanced+S8_offset": lambda f, r: taarya_score(f, "balanced", extra_offset_weight=12.0),
            "taarya_v2_calibrated": lambda f, r: lr.decision_function(_bin_features(f)),
        }
        return te, scorers, lr

    def evaluate(self, seed=7, quick=False):
        rng = np.random.default_rng(seed)
        n_fields, n = (16, 1500) if quick else (60, 2500)
        te, scorers, lr = self._run(rng, n_fields, n, 0.04, 0.25, seed)
        indep = evaluate_scorers(te, lambda f: f["is_binary"], scorers, "baseline_sort_RUWE", seed=seed)
        circ = evaluate_scorers(te, paper_style_labels, scorers, "baseline_sort_RUWE", seed=seed)
        sens = {}
        for contam, bf in [(0.02, 0.25), (0.08, 0.25), (0.20, 0.25), (0.08, 0.10)]:
            te2, sc2, _ = self._run(np.random.default_rng(seed + 5), 12 if quick else 24, n, contam, bf, seed)
            r = evaluate_scorers(te2, lambda f: f["is_binary"], sc2, "baseline_sort_RUWE", seed=seed)
            sens[f"contam={contam},bin_frac={bf}"] = {k: r[k]["AP"]["mean"] for k in
                                                       ("baseline_sort_RUWE", "baseline_RUWE+offset_columns",
                                                        "taarya_v1_balanced", "taarya_v2_calibrated")}
        base = float(np.mean([f["is_binary"].mean() for f in te]))
        return dict(workflow=self.name, describe=self.describe(), units=f"{len(te)} held-out fields (fit on {len(te)} others)",
                    base_rate=round(base, 3), independent_labels=indep, circular_threshold_labels=circ,
                    sensitivity_AP_mean=sens,
                    v2_coefficients=dict(zip(["log_ruwe", "ruwe_excess", "ms_offset"], np.round(lr.coef_[0], 3).tolist())),
                    note="circular_threshold_labels shows how threshold-defined labels flatter a threshold-based ranker.")


class GaiaKinematicOutliers(Workflow):
    name = "gaia_kinematic_outliers"
    ground_truth = "latent v_t > 220 km/s flag (synthetic); drop-in: published hypervelocity / halo-star lists"
    baseline = "TOPCAT: sort by proper motion; or by v_t = 4.74*PM/parallax (still a column expression)"
    claim_ceiling = Claim.CANDIDATE
    evidence_level = "synthetic"

    def evaluate(self, seed=7, quick=False):
        rng = np.random.default_rng(seed + 1)
        n_fields, n = (16, 1500) if quick else (60, 2500)
        fields = [make_field(rng, n) for _ in range(n_fields)]
        tr, te = fields[: n_fields // 2], fields[n_fields // 2:]
        lr = fit_logistic(tr, "is_fast", _kin_features)
        scorers = {
            "random": b_random, "baseline_sort_PM": b_pm, "baseline_sort_vt": b_vt,
            "taarya_v1_strict": lambda f, r: taarya_score(f, "strict"),
            "taarya_v1_balanced": lambda f, r: taarya_score(f, "balanced"),
            "taarya_v2_calibrated": lambda f, r: lr.decision_function(_kin_features(f)),
        }
        res = evaluate_scorers(te, lambda f: f["is_fast"], scorers, "baseline_sort_PM", seed=seed)
        return dict(workflow=self.name, describe=self.describe(), units=f"{len(te)} held-out fields",
                    base_rate=round(float(np.mean([f["is_fast"].mean() for f in te])), 3),
                    independent_labels=res,
                    note="PM-threshold selection returns nearby slow stars; v_t separates genuinely fast stars. "
                         "(80 mas/yr at 1 kpc is ~380 km/s, not 600.)")
