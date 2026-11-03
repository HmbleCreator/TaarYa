"""
Real-label evaluation for Gaia binary triage.

You supply (a) a CSV of stars grouped into FIELDS (cones/tiles) with Gaia columns and (b) one or more
sets of labelled source_ids. This module builds the feature columns, enforces label-provenance rules,
and calls the same evaluate_scorers() used for the synthetic study.

LABEL PROVENANCE (enforced):
  independent : SB9 / spectroscopic binaries, Gaia NSS SB1/SB2 (spectroscopic), resolved co-moving pairs (El-Badry+21)
  circular    : Gaia NSS *astrometric* orbits -- they exist BECAUSE of the astrometric residuals that inflate RUWE.
                Scoring a RUWE-based ranker on them is circular; refused unless allow_circular=True.
Negatives are "not in any label set" -> UNLABELLED, not confirmed single. Report that. Prefer restricting the
evaluation to stars that were SEARCHED (e.g. inside the SB9 / NSS completeness footprint) in the paper.

UNVERIFIED HERE (no network): the ADQL below. Check column names against your Gaia Archive release.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from ..gaia_triage import evaluate_scorers, taarya_score, b_random, b_ruwe, b_ruwe_offset, fit_logistic, _bin_features

ADQL_FIELD = """SELECT source_id, ra, dec, parallax, parallax_over_error, pmra, pmdec, phot_g_mean_mag AS G, bp_rp, ruwe
FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra},{dec},{radius_deg}))
  AND parallax_over_error > 10 AND phot_g_mean_mag < 17 AND bp_rp IS NOT NULL
-- if `ruwe` is not in gaia_source for your release, join the RUWE table instead"""
ADQL_NSS = """SELECT source_id, nss_solution_type FROM gaiadr3.nss_two_body_orbit
WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra},{dec},{radius_deg}))"""
PROVENANCE = {"sb9": "independent", "nss_sb1_sb2": "independent", "elbadry_wide": "independent",
              "nss_astrometric": "circular"}


def compute_ms_offset(df: pd.DataFrame, ruwe_max=1.2, quantile=0.35, bin_width=0.2, min_bin=15) -> np.ndarray:
    """Magnitude ABOVE the field's single-star main-sequence ridge (positive = binary-like). The ridge comes
    from low-RUWE stars in the same field; labels are never used."""
    M = df.G.to_numpy() + 5 * np.log10(np.clip(df.parallax.to_numpy(), 1e-3, None)) - 10
    ref = (df.ruwe < ruwe_max).to_numpy() & (df.parallax_over_error > 10).to_numpy()
    edges = np.arange(df.bp_rp.min(), df.bp_rp.max() + bin_width, bin_width)
    cx, cy = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = ref & (df.bp_rp.to_numpy() >= lo) & (df.bp_rp.to_numpy() < hi)
        if m.sum() >= min_bin:
            cx.append((lo + hi) / 2); cy.append(np.quantile(M[m], quantile))
    if len(cx) < 3: return np.zeros(len(df))
    return np.interp(df.bp_rp.to_numpy(), cx, cy) - M          # bright (smaller M) => positive


def fields_from_dataframe(df: pd.DataFrame, labels: np.ndarray, field_col="field_id", min_stars=300, min_pos=10):
    out = []
    for fid, g in df.groupby(field_col):
        if len(g) < min_stars: continue
        y = labels[g.index.to_numpy()]
        if y.sum() < min_pos: continue
        out.append(dict(ruwe=g.ruwe.to_numpy(), bp_rp=g.bp_rp.to_numpy(), G=g.G.to_numpy(), parallax=g.parallax.to_numpy(),
                        pmra=g.pmra.to_numpy(), pmdec=g.pmdec.to_numpy(), ms_offset_obs=compute_ms_offset(g),
                        is_binary=y.astype(int), field_id=fid))
    return out


def build_labels(df: pd.DataFrame, label_sets: dict, allow_circular=False) -> tuple[np.ndarray, dict]:
    """label_sets: {name: set(source_id)}. Returns union labels + provenance report."""
    rep, y = {}, np.zeros(len(df), bool)
    for name, ids in label_sets.items():
        prov = PROVENANCE.get(name, "unknown")
        if prov == "circular" and not allow_circular:
            rep[name] = "REFUSED (circular with RUWE)"; continue
        if prov == "unknown":
            rep[name] = "REFUSED (declare provenance in PROVENANCE first)"; continue
        m = df.source_id.isin(ids).to_numpy(); y |= m
        rep[name] = dict(provenance=prov, matched=int(m.sum()), supplied=len(ids))
    return y.astype(int), rep


def run(csv_path: str, label_sets: dict, allow_circular=False, seed=0) -> dict:
    df = pd.read_csv(csv_path).reset_index(drop=True)
    y, rep = build_labels(df, label_sets, allow_circular)
    fields = fields_from_dataframe(df, y)
    if len(fields) < 6: return dict(error=f"only {len(fields)} usable fields; need >= 6", label_report=rep)
    half = len(fields) // 2
    tr, te = fields[:half], fields[half:]                          # split by FIELD, never by row
    lr = fit_logistic(tr, "is_binary", _bin_features)
    scorers = {"random": b_random, "baseline_sort_RUWE": b_ruwe, "baseline_RUWE+offset_columns": b_ruwe_offset,
               "taarya_v1_balanced": lambda f, r: taarya_score(f, "balanced"),
               "taarya_v2_calibrated": lambda f, r: lr.decision_function(_bin_features(f))}
    res = evaluate_scorers(te, lambda f: f["is_binary"], scorers, "baseline_sort_RUWE", seed=seed)
    return dict(n_fields_train=len(tr), n_fields_test=len(te), label_report=rep,
                base_rate=round(float(np.mean([f["is_binary"].mean() for f in te])), 4), results=res,
                caution="negatives are UNLABELLED, not confirmed single; restrict to the label survey's footprint")
