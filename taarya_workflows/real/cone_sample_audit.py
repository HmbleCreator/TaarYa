"""
Is the cluster sample what it claims to be? Run BEFORE reading any retrieval result.

  python -m taarya_workflows.real.cone_sample_audit --cones hr23/cones --selection hr23/selection.json --clusters hr23/clusters.csv --members hr23/selected_members.csv

Checks: (1) every cone used the same cuts (ADQL identical after removing the cone), (2) no truncated cone was kept, (3) published-member coverage,
(4) members actually fetched vs the catalogue's own count (a shortfall means a truncated download), (5) who was excluded and whether exclusion
is selective, e.g. crowded low-|b| fields dropped (selection bias), (6) stars shared between cones. Exit 1 on any hard failure.
"""
from __future__ import annotations
import json, re, sys
from collections import Counter
from pathlib import Path
import numpy as np, pandas as pd
from . import cluster_cones as CC
from .membership import canon


def abs_b(ra, dec):
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    return np.abs(SkyCoord(np.asarray(ra, float) * u.deg, np.asarray(dec, float) * u.deg).galactic.b.deg)


def audit(cones_dir, selection_json, clusters_csv=None, members_csv=None, top=60000, min_cov=0.5, shortfall=0.10) -> dict:
    cones = Path(cones_dir); man = json.loads((cones / "manifest.json").read_text()); sel = json.loads(Path(selection_json).read_text())
    cl = man["clusters"]; ok = {k: v for k, v in cl.items() if v.get("status") == "ok"}; skipped = {k: v for k, v in cl.items() if v.get("status") != "ok"}
    hard, soft = [], []
    forms = Counter(re.sub(r"CIRCLE\('ICRS',[^)]*\)", "CIRCLE(<cone>)", v["adql"]) for v in cl.values() if "adql" in v)
    if len(forms) > 1: hard.append(f"{len(forms)} different ADQL forms across cones: cuts are not uniform, results are not comparable")
    over = [k for k, v in ok.items() if v["n_cone"] >= top]
    if over: hard.append(f"truncated cones kept as 'ok': {over}")
    lowcov = {k: v["member_coverage"] for k, v in ok.items() if v["member_coverage"] < min_cov}
    if lowcov: soft.append(f"low published-member coverage (<{min_cov}) in {len(lowcov)} cone(s): the cone radius misses much of the cluster: {lowcov}")
    selected = sel["selected"]; known = {canon(k) for k in cl}
    dropped_members = [c for c in selected if canon(c) not in known]
    out = dict(n_selected=len(selected), n_evaluable=len(ok), n_skipped_truncated=len(skipped), dropped_before_cones=dropped_members, adql_forms=len(forms), low_coverage=lowcov)
    # (4) fetched members vs the catalogue's own count
    if clusters_csv and members_csv:
        raw = pd.read_csv(clusters_csv); nm = raw[CC._pick(raw, CC.CLUSTER_COLS["name"])].astype(str); cnt = pd.to_numeric(raw[CC._pick(raw, CC.CLUSTER_COLS["n"])], errors="coerce")
        want = dict(zip(nm, cnt)); got = CC.load_members(members_csv, min_prob=0.7, min_members=0).cluster.value_counts().to_dict()
        short = {c: (int(got.get(c, 0)), int(want[c])) for c in selected if c in want and got.get(c, 0) < (1 - shortfall) * want[c]}
        out["member_shortfall"] = short
        if short: hard.append(f"{len(short)} cluster(s) have >{int(shortfall*100)}% fewer P>=0.7 members than the catalogue says (fetched, expected): {short}; the member download was probably truncated or the criteria column differs")
    # (5) selective exclusion by crowding
    pos = lambda d: ([v["ra0"] for v in d.values() if "ra0" in v], [v["dec0"] for v in d.values() if "dec0" in v])
    ra_ok, de_ok = pos(ok); ra_sk, de_sk = pos(skipped)
    if len(ra_ok) >= 3 and len(ra_sk) >= 3:
        b_ok, b_sk = abs_b(ra_ok, de_ok), abs_b(ra_sk, de_sk)
        from scipy.stats import mannwhitneyu
        p = float(mannwhitneyu(b_ok, b_sk).pvalue)
        out["abs_b_median"] = dict(kept=round(float(np.median(b_ok)), 1), skipped_truncated=round(float(np.median(b_sk)), 1), mannwhitney_p=round(p, 3))
        if np.median(b_sk) < np.median(b_ok) and p < 0.1: soft.append("truncated (skipped) cones sit at lower galactic latitude than kept ones: the sample is biased toward uncrowded fields; state this")
    # (6) overlap between cones
    sp = cones / "stars.csv"
    if sp.exists():
        st = pd.read_csv(sp, usecols=["cluster", "source_id"], dtype={"source_id": str}); dup = st.drop_duplicates().source_id.duplicated().sum()
        out["stars_shared_between_cones"] = int(dup)
        if dup: soft.append(f"{dup} stars appear in more than one cone (overlapping clusters); fine for per-cluster scoring, but not independent units")
    out.update(hard_failures=hard, warnings=soft, passed=not hard)
    return out


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("--cones", required=True); ap.add_argument("--selection", required=True)
    ap.add_argument("--clusters"); ap.add_argument("--members"); a = ap.parse_args(); r = audit(a.cones, a.selection, a.clusters, a.members)
    print(json.dumps(r, indent=2)); sys.exit(0 if r["passed"] else 1)
