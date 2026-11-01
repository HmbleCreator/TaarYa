"""
Real-label evaluation of the Gaia-neighbour (Q3C/TAP) vetter using TESS TOI dispositions.

  planets        = TFOPWG dispositions CP, KP          (label 0)
  false positives= TFOPWG disposition  FP              (label 1)
  excluded       = PC/APC (unresolved), FA (false alarm = noise, not astrophysical FP)

Question answered: does the neighbour-explainability score separate FPs from planets
BEYOND what depth alone does?  (EBs are deeper, so depth is a strong baseline.)

CAVEAT (state it in the paper): TFOPWG vetting itself uses Gaia neighbour checks, so these labels
are not independent of the feature. The result measures agreement with human vetting, not truth.

UNVERIFIED HERE (no network in the build sandbox): endpoint URLs and column names. Column lookup is
tolerant (candidate lists below) and fails loudly with the columns it did see.
"""
from __future__ import annotations
import io, json, os, time, urllib.parse, urllib.request
import numpy as np, pandas as pd
from ..core import rate, bootstrap_ci

ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=select+*+from+toi&format=csv"
EXOFOP_CSV = "https://exofop.ipac.caltech.edu/tess/download_toi.php?sort=toi&output=csv"
CANDIDATES = {
    "toi": ["toi", "TOI"], "tic": ["tid", "TIC ID", "tic"], "disp": ["tfopwg_disp", "TFOPWG Disposition"],
    "period": ["pl_orbper", "Period (days)"], "depth_ppm": ["pl_trandep", "Depth (ppm)"],
    "dur_h": ["pl_trandurh", "Duration (hours)"], "tmag": ["st_tmag", "TESS Mag"],
    "ra": ["ra", "RA"], "dec": ["dec", "Dec"],
}
PLANET, FP = {"CP", "KP"}, {"FP"}
PSF_SIGMA_ARCSEC, D_MAX = 21.0, 0.8


def download(url: str, timeout: int = 60) -> pd.DataFrame:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return pd.read_csv(io.BytesIO(r.read()))


def _to_deg(v, is_ra: bool):
    if isinstance(v, str) and (":" in v or " " in v.strip()):
        from astropy.coordinates import Angle
        import astropy.units as u
        return float(Angle(v, unit=u.hourangle if is_ra else u.deg).deg)
    return float(v)


def normalise(raw: pd.DataFrame) -> pd.DataFrame:
    cols, out = {c.lower(): c for c in raw.columns}, {}
    for key, names in CANDIDATES.items():
        hit = next((raw.columns[[c.lower() for c in raw.columns].index(n.lower())] for n in names
                    if n.lower() in cols), None)
        if hit is None and key in ("tic", "disp", "depth_ppm", "tmag", "ra", "dec"):
            raise KeyError(f"required column '{key}' not found; saw {list(raw.columns)[:40]}")
        out[key] = raw[hit] if hit is not None else np.nan
    df = pd.DataFrame(out)
    df["disp"] = df["disp"].astype(str).str.strip().str.upper()
    df["ra"] = [_to_deg(v, True) for v in df["ra"]]; df["dec"] = [_to_deg(v, False) for v in df["dec"]]
    df["label"] = np.where(df.disp.isin(PLANET), 0, np.where(df.disp.isin(FP), 1, -1))
    for c in ("depth_ppm", "tmag", "period", "dur_h"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_tois(source: str = "archive") -> pd.DataFrame:
    if source == "archive":
        if os.path.exists("data/tess_cache/nasa_tois.csv"):
            raw = pd.read_csv("data/tess_cache/nasa_tois.csv")
        else:
            raw = download(ARCHIVE_TAP)
    elif source == "exofop":
        raw = download(EXOFOP_CSV)
    else:
        raw = pd.read_csv(source)
    return normalise(raw)


# ----------------------------------------------------------------- neighbours
def fetch_neighbours_gaia(ra, dec, radius_arcsec=42.0) -> pd.DataFrame:
    """Gaia DR3 cone via AIP Potsdam TAP with fallback to astroquery. Returns columns sep_arcsec, G."""
    q = (f"SELECT source_id, phot_g_mean_mag AS G, DISTANCE(POINT('ICRS',ra,dec),POINT('ICRS',{ra},{dec}))*3600 AS sep_arcsec "
         f"FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra},{dec},{radius_arcsec/3600})) "
         f"AND phot_g_mean_mag IS NOT NULL")
    try:
        url = "https://gaia.aip.de/tap/sync?REQUEST=doQuery&LANG=ADQL&QUERY=" + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers={"User-Agent": "taarya-toi-vetter"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return pd.read_csv(io.BytesIO(r.read()))
    except Exception:
        from astroquery.gaia import Gaia
        return Gaia.launch_job(q).get_results().to_pandas()


def fetch_neighbours_postgres(dsn=None, table="stars", ra_col="ra", dec_col="dec", g_col="phot_g_mean_mag",
                              radius_arcsec=42.0, min_cover=20, cover_radius_deg=0.5, run_query=None):
    """Neighbour fetcher backed by the local Q3C table.

    IMPORTANT: a local table only covers its seeded regions. An empty cone there means "no catalogue",
    NOT "no neighbours" -- treating it as zero neighbours would score every out-of-coverage TOI as
    planet-like. So an empty cone is checked against surrounding coverage and raises LookupError
    (cached as an error, row dropped) when the catalogue is simply absent.
    The DSN comes from the TAARYA_PG_DSN environment variable; never hard-code credentials in the repo."""
    import os
    dsn = dsn or os.environ.get("TAARYA_PG_DSN")

    def _default(sql, params):
        import psycopg2
        with psycopg2.connect(dsn) as c, c.cursor() as cur:
            cur.execute(sql, params); return cur.fetchall()
    rq = run_query or _default

    def fetch(ra, dec, radius_arcsec=radius_arcsec):
        rows = rq(f"SELECT {g_col}, 3600*q3c_dist({ra_col},{dec_col},%s,%s) FROM {table} "
                  f"WHERE q3c_radial_query({ra_col},{dec_col},%s,%s,%s)", (ra, dec, ra, dec, radius_arcsec / 3600.0))
        if not rows:
            n = rq(f"SELECT count(*) FROM {table} WHERE q3c_radial_query({ra_col},{dec_col},%s,%s,%s)",
                   (ra, dec, cover_radius_deg))[0][0]
            if n < min_cover:
                raise LookupError(f"no local catalogue coverage near ({ra:.3f},{dec:.3f})")
        return pd.DataFrame(rows, columns=["G", "sep_arcsec"])
    return fetch


def cached_neighbours(df, fetch, cache_path, sleep=0.2, max_n=None):
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for i, r in enumerate(df.itertuples()):
        if max_n and i >= max_n: break
        k = f"{int(r.tic)}"
        if k in cache: continue
        try: cache[k] = fetch(r.ra, r.dec).to_dict("list")
        except Exception as e: cache[k] = {"error": str(e)}
        time.sleep(sleep); json.dump(cache, open(cache_path, "w"))
    return cache


def _best_dip(nb, tmag):
    """Largest dip (fraction of flux) any catalogued neighbour could produce; None if the fetch is unusable."""
    if isinstance(nb, dict) and ("error" in nb or not nb): return None
    nb = pd.DataFrame(nb)
    if nb.empty and not len(nb.columns): return None
    nb = nb[~((nb.sep_arcsec < 1.5) & ((nb.G - tmag).abs() < 1.0))]       # drop the target itself
    if nb.empty: return 0.0
    fr = np.exp(-0.5 * (nb.sep_arcsec / PSF_SIGMA_ARCSEC) ** 2) * 10 ** (-0.4 * (nb.G - tmag))
    return float(D_MAX * fr.max() / (1.0 + fr.sum()))


def explain_score(nb, tmag: float, depth_ppm: float) -> float:
    """Legacy ratio score: log10(best possible neighbour dip / observed depth). NOTE it contains -log(depth) and, through
    G - Tmag, a dependence on target brightness; prefer neighbour_logdip + explicit covariates."""
    b = _best_dip(nb, tmag)
    if b is None: return np.nan
    return -3.0 if b == 0.0 else float(np.log10(max(b, 1e-12) / (depth_ppm * 1e-6)))


def neighbour_logdip(nb, tmag: float) -> float:
    b = _best_dip(nb, tmag)
    return np.nan if b is None else float(np.log10(max(b * 1e6, 1e-3)))


def build_table(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    d = df[(df.label >= 0) & df.depth_ppm.notna() & df.tmag.notna()].copy()
    nbs = [cache.get(str(int(t)), {"error": "missing"}) for t in d.tic]
    d["score"] = [explain_score(nb, m, dp) for nb, m, dp in zip(nbs, d.tmag, d.depth_ppm)]
    d["logdip"] = [neighbour_logdip(nb, m) for nb, m in zip(nbs, d.tmag)]
    return d[d.score.notna() & d.logdip.notna()]


# ----------------------------------------------------------------- evaluation
def _auc(y, s):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def _pipe():
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import SplineTransformer, StandardScaler
    from sklearn.linear_model import LogisticRegression
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         SplineTransformer(n_knots=4, degree=3, extrapolation="constant"), LogisticRegression(C=0.3, max_iter=3000))


def evaluate(d: pd.DataFrame, B: int = 1000, seed: int = 0) -> dict:
    """Does the neighbour feature add information BEYOND what the TOI table already says?
    Baseline = flexible (spline) model on depth, Tmag, period, duration (whatever columns exist). A 1-D linear depth baseline was too
    weak: FP-vs-depth is not monotone, and the neighbour score also encodes target brightness (a follow-up selection effect), so
    Tmag must be in the baseline. All arms are grouped-CV (by TIC), each learns its own sign. Resampling unit = TIC."""
    from sklearn.model_selection import GroupKFold
    y = d.label.to_numpy(); g = d.tic.to_numpy()
    cov = []
    for c, lg in (("depth_ppm", True), ("tmag", False), ("period", True), ("dur_h", True)):
        if c in d and d[c].notna().mean() > 0.8:
            v = d[c].to_numpy(float); cov.append(np.log10(np.clip(v, 1e-9, None)) if lg else v)
    if "ra" in d and "dec" in d and d.ra.notna().all():                     # crowding proxy: follow-up feasibility depends on it
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        cov.append(np.abs(SkyCoord(d.ra.to_numpy(float) * u.deg, d.dec.to_numpy(float) * u.deg).galactic.b.deg))
    Xc = np.column_stack(cov); nf = (d["logdip"] if "logdip" in d else d["score"]).to_numpy(float)[:, None]
    n_splits = min(5, len(np.unique(g)))

    def cvp(X, repeats=5):
        """Out-of-fold decision values averaged over `repeats` different grouped splits (one split's AUC is partition-noisy)."""
        from sklearn.model_selection import StratifiedGroupKFold
        out = np.zeros(len(y))
        for r in range(repeats):
            for tr, te in StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=r).split(X, y, g):
                out[te] += _pipe().fit(X[tr], y[tr]).decision_function(X[te]) / repeats
        return out
    arms = {"covariates_only_cv": cvp(Xc), "neighbour_only_cv": cvp(nf), "covariates+neighbour_cv": cvp(np.hstack([Xc, nf]))}
    rng = np.random.default_rng(seed); tics = np.unique(g); idx_by = {t: np.where(g == t)[0] for t in tics}
    boot = {k: [] for k in arms}; diff = []
    for _ in range(B):
        ii = np.concatenate([idx_by[t] for t in rng.choice(tics, len(tics))])
        if y[ii].sum() == 0 or y[ii].sum() == len(ii): continue
        a_ = {k: _auc(y[ii], v[ii]) for k, v in arms.items()}
        for k in arms: boot[k].append(a_[k])
        diff.append(a_["covariates+neighbour_cv"] - a_["covariates_only_cv"])
    ci = lambda v: [round(float(np.quantile(v, .025)), 3), round(float(np.quantile(v, .975)), 3)]
    res = {k: dict(auc=round(_auc(y, v), 3), ci95=ci(boot[k])) for k, v in arms.items()}
    res["baseline_covariates"] = [c for c in ("depth_ppm", "tmag", "period", "dur_h") if c in d and d[c].notna().mean() > 0.8] + (["abs_galactic_lat"] if "ra" in d and "dec" in d and d.ra.notna().all() else [])
    res["analysis_spec_frozen"] = dict(model="SimpleImputer+StandardScaler+SplineTransformer(4 knots, deg 3)+LogisticRegression(C=0.3)",
                                       cv="5-fold StratifiedGroupKFold by TIC, 5 repeats averaged", bootstrap=f"{B} resamples by TIC",
                                       note="do not tune after seeing results; report any change as a new analysis")
    dep = np.log10(np.clip(d.depth_ppm.to_numpy(float), 1e-9, None)); res["raw_depth_auc_fixed_sign"] = round(_auc(y, dep), 3)
    res["warnings"] = ([f"depth is ANTI-correlated with FP in this sample (raw AUC {res['raw_depth_auc_fixed_sign']:.2f}); check selection"]
                       if res["raw_depth_auc_fixed_sign"] < 0.4 else [])
    dd = dict(mean=round(float(np.mean(diff)), 3), ci95=ci(diff)); dd["separated"] = bool(dd["ci95"][0] > 0 or dd["ci95"][1] < 0)
    res["delta_auc_with_vs_without_neighbour"] = dd
    # backward-compatible aliases
    res["depth_only_cv"], res["depth+neighbour_cv"], res["delta_auc_combined_minus_depth"] = res["covariates_only_cv"], res["covariates+neighbour_cv"], dd
    sc = d.score.to_numpy(float); ops = {}
    for thr in (-1.0, 0.0, 0.5, 1.0):
        fl = sc >= thr; nfp, npl = max((y == 1).sum(), 1), max((y == 0).sum(), 1)
        ops[f"score>={thr}"] = dict(fp_rejected=rate(int((fl & (y == 1)).sum()), int((y == 1).sum())),
                                    planets_lost=rate(int((fl & (y == 0)).sum()), int((y == 0).sum())),
                                    enrichment_vs_random=round(float((fl & (y == 1)).sum() / nfp - (fl & (y == 0)).sum() / npl), 3))
    res["operating_points"] = ops
    res["n"] = dict(planets=int((y == 0).sum()), false_positives=int((y == 1).sum()), stars=int(len(tics)))
    res["verdict"] = ("neighbour feature adds information beyond the TOI-table covariates (labels overlap with human vetting; report as agreement)"
                      if dd["separated"] and dd["mean"] > 0 else "no demonstrated gain over TOI-table covariates" if not dd["separated"]
                      else "adding the neighbour feature hurts")
    return res


def run(source="archive", cache_path="toi_neighbours_cache.json", fetch=None, max_n=None, cache_only=False):
    df = load_tois(source)
    if cache_only:
        cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        return evaluate(build_table(df, cache))
    sub = df[(df.label >= 0)].drop_duplicates("tic")
    if max_n:                                                   # random, seeded: the head of a TOI-sorted list is NOT representative
        sub = sub.sample(min(max_n, len(sub)), random_state=0)
    cache = cached_neighbours(sub, fetch or fetch_neighbours_gaia, cache_path)
    return evaluate(build_table(df, cache))


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="archive"); ap.add_argument("--cache", default="toi_neighbours_cache.json")
    ap.add_argument("--max", type=int, default=None); ap.add_argument("--cache-only", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.source, a.cache, max_n=a.max, cache_only=a.cache_only), indent=2))
