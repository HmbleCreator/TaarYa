"""
One command: select ~30 open clusters from Hunt & Reffert 2023 by pre-specified criteria, fetch their members, optionally build the Gaia cones.

  python -m taarya_workflows.real.fetch_hr23 --out hr23 --n 30 --seed 0 [--run-cones --tap https://gaia.aip.de/tap --g-max 16]

Writes  hr23/clusters.csv, hr23/members/<name>.csv (cached), hr23/selected_members.csv, hr23/selection.json (criteria, seed, eligible count,
mirror used, UTC, per-cluster member counts). Re-running costs zero requests for anything already cached.
UNVERIFIED HERE (no network): the VizieR mirror URLs, the asu-tsv layout (comment lines, header, units row, dashes row, data) and the catalogue's column
names. The parser and column lookup are tolerant and fail loudly with what they saw.
"""
from __future__ import annotations
import io, json, re, time, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd
from . import cluster_cones as CC

CLUSTERS_CAT, MEMBERS_CAT = "J/A+A/673/A114/clusters", "J/A+A/673/A114/members"
MIRRORS = ["https://vizier.cds.unistra.fr/viz-bin/asu-tsv", "http://vizier.china-vo.org/viz-bin/asu-tsv", "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"]


def default_http_get(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "taarya-hr23-fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read().decode("utf-8", "replace")


def parse_asu_tsv(text) -> pd.DataFrame:
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not lines: return pd.DataFrame()
    header = [h.strip() for h in lines[0].split("\t")]; start = 1
    for i, l in enumerate(lines[1:5], 1):                                  # units row, then a row of dashes, then data
        if l.strip() and set(l.replace("\t", "").replace(" ", "")) <= {"-"}: start = i + 1; break
    rows = [(r.split("\t") + [""] * len(header))[:len(header)] for r in lines[start:]]
    return pd.DataFrame([[c.strip() for c in r] for r in rows], columns=header, dtype=str)


def fetch_table(cat, constraints=None, mirrors=None, http_get=None, retries=2, sleep=1.0):
    http_get, errs = http_get or default_http_get, []
    for base in (mirrors or MIRRORS):
        for attempt in range(retries + 1):
            try:
                q = {"-source": cat, "-out.max": "unlimited", **(constraints or {})}
                df = parse_asu_tsv(http_get(f"{base}?{urllib.parse.urlencode(q, safe='/')}"))
                if len(df.columns) > 1: return df, base
                errs.append(f"{base}: empty/unparseable response")
            except Exception as e: errs.append(f"{base}: {e}")
            time.sleep(sleep if attempt < retries else 0)
    raise RuntimeError("all mirrors failed: " + " | ".join(errs[-6:]))


safe = lambda s: re.sub(r"[^A-Za-z0-9_.-]", "_", s)


def run(out_dir, n=30, seed=0, max_dist_pc=1000.0, min_members=100, max_r50_deg=2.0, name_col="Name", http_get=None, mirrors=None,
        run_cones=False, tap_url=CC.DEFAULT_TAP, g_max=16.0, sleep=0.0):
    out = Path(out_dir); (out / "members").mkdir(parents=True, exist_ok=True); used = None
    cp = out / "clusters.csv"
    if not cp.exists():
        df, used = fetch_table(CLUSTERS_CAT, None, mirrors, http_get, sleep=sleep); df.to_csv(cp, index=False)
    sel = CC.select_clusters(str(cp), max_dist_pc, min_members, max_r50_deg, n, seed)
    parts, counts, failed = [], {}, {}
    for name in sel["selected"]:
        f = out / "members" / f"{safe(name)}.csv"
        if not f.exists():
            try:
                df, used = fetch_table(MEMBERS_CAT, {name_col: name}, mirrors, http_get, sleep=sleep)
                if name_col not in df.columns: raise KeyError(f"'{name_col}' not in members columns {list(df.columns)}")
                df = df[df[name_col].str.strip() == name]                 # the server matches patterns; keep exact names only
                df.to_csv(f, index=False)
            except Exception as e: failed[name] = str(e); continue
        d = pd.read_csv(f, dtype=str); counts[name] = int(len(d)); parts.append(d)
    if not parts: raise RuntimeError(f"no members fetched; failures: {failed}")
    pd.concat(parts, ignore_index=True).to_csv(out / "selected_members.csv", index=False)
    info = dict(sel, catalogue=dict(clusters=CLUSTERS_CAT, members=MEMBERS_CAT), mirror_last_used=used, utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                members_per_cluster=counts, failed=failed, g_max_planned=g_max)
    (out / "selection.json").write_text(json.dumps(info, indent=2))
    if run_cones:
        info["cones_manifest"] = CC.build(str(out / "selected_members.csv"), str(out / "cones"), tap_url=tap_url, g_max=g_max, min_members=min_members)
    return info


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("--out", default="hr23"); ap.add_argument("--n", type=int, default=30); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-dist-pc", type=float, default=1000.0); ap.add_argument("--min-members", type=int, default=100); ap.add_argument("--max-r50-deg", type=float, default=2.0)
    ap.add_argument("--mirror", action="append"); ap.add_argument("--run-cones", action="store_true"); ap.add_argument("--tap", default=CC.DEFAULT_TAP); ap.add_argument("--g-max", type=float, default=16.0)
    a = ap.parse_args(); r = run(a.out, a.n, a.seed, a.max_dist_pc, a.min_members, a.max_r50_deg, mirrors=a.mirror, run_cones=a.run_cones, tap_url=a.tap, g_max=a.g_max, sleep=1.0)
    print(json.dumps({k: r[k] for k in ("selected", "eligible", "criteria", "members_per_cluster", "failed")}, indent=2))
    if "cones_manifest" in r: print({k: (v.get("status"), v.get("n_cone"), v.get("member_coverage")) for k, v in r["cones_manifest"]["clusters"].items()})
