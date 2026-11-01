"""
One command regenerates every real-data number in the paper.

  python -m taarya_workflows.real.run_real_eval --cones cluster_cones --toi-cache toi_nb.json --toi-n 500 --out results

Writes results/{membership,retrieval,toi}.json and results/summary.json (code hash, git commit, package versions, UTC,
input-manifest hash). Then:  python -m taarya_workflows.real.make_tables --results results --out tables
`evaluate_all` is pure (no network, no files) so it is unit-tested; main() does the IO.
"""
from __future__ import annotations
import argparse, hashlib, json, os, platform, subprocess, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from . import membership, cluster_retrieval, exofop


def code_hash(pkg_dir=None) -> str:
    pkg = Path(pkg_dir or Path(__file__).resolve().parents[1]); h = hashlib.sha256()
    for f in sorted(pkg.rglob("*.py")): h.update(f.relative_to(pkg).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()[:16]


def git_commit():
    try: return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception: return None


def versions() -> dict:
    out = dict(python=sys.version.split()[0], platform=platform.platform())
    for m in ("numpy", "pandas", "scipy", "sklearn", "astropy"):
        try: out[m] = __import__(m).__version__
        except Exception: out[m] = None
    return out


def evaluate_all(stars=None, gold=None, edges_cone=None, toi_table=None, n_seeds=10, repeats=5, seed=0) -> dict:
    res = {}
    if stars is not None and gold is not None:
        g = gold.copy(); g["source_id"] = g.source_id.astype(object).map(int)
        if edges_cone is not None: res["membership"] = membership.evaluate_membership(stars, edges_cone, g, seed=seed)
        res["retrieval"] = cluster_retrieval.evaluate_retrieval(stars, g, n_seeds=n_seeds, repeats=repeats, seed=seed)
    if toi_table is not None: res["toi"] = exofop.evaluate(toi_table, seed=seed)
    return res


def build_toi_table(toi_source, cache_path, n, fetch=None, seed=0):
    """Defined random sample of labelled TOI stars (seeded), neighbours fetched into the cache. Reports fetch failures."""
    df = exofop.load_tois(toi_source); lab = df[df.label >= 0].drop_duplicates("tic")
    cache_existing = json.load(open(cache_path)) if cache_path and os.path.exists(cache_path) else {}
    cached_tics = {int(k) for k in cache_existing.keys() if k.isdigit()}
    if cached_tics and (fetch is None or not os.environ.get("TAARYA_ONLINE_EVAL")):
        in_cache = lab[lab.tic.isin(cached_tics)]
        sub = in_cache.sample(min(n, len(in_cache)), random_state=seed) if (n and len(in_cache) > n) else in_cache
    else:
        sub = lab.sample(min(n, len(lab)), random_state=seed) if n else lab
    cache = exofop.cached_neighbours(sub, fetch or exofop.fetch_neighbours_gaia, cache_path)
    tab = exofop.build_table(df[df.tic.isin(sub.tic)], cache)
    errs = sum(1 for t in sub.tic if "error" in cache.get(str(int(t)), {"error": 1}))
    tab.attrs["sample"] = dict(requested=int(len(sub)), usable=int(tab.tic.nunique()), fetch_failed=int(errs), seed=seed,
                               design="seeded random sample of all labelled (CP/KP/FP) TOI stars")
    return tab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cones"); ap.add_argument("--toi-source", default="archive"); ap.add_argument("--toi-cache"); ap.add_argument("--toi-n", type=int, default=500)
    ap.add_argument("--n-seeds", type=int, default=10); ap.add_argument("--out", default="results"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stars = gold = edges = None; man_hash = None
    if a.cones:
        c = Path(a.cones); rd = lambda f: pd.read_csv(c / f, dtype={"source_id": str})
        stars, gold, edges = rd("stars.csv"), rd("gold.csv"), rd("edges_cone.csv")
        man_hash = hashlib.sha256((c / "manifest.json").read_bytes()).hexdigest()[:16]
    toi = None; sample = None
    if a.toi_cache:
        toi = build_toi_table(a.toi_source, a.toi_cache, a.toi_n, seed=a.seed); sample = toi.attrs.get("sample")
    res = evaluate_all(stars, gold, edges, toi, a.n_seeds, seed=a.seed)
    for k, v in res.items(): json.dump(v, open(out / f"{k}.json", "w"), indent=2, default=str)
    summ = dict(utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), code_hash=code_hash(), git_commit=git_commit(), versions=versions(),
                cone_manifest_hash=man_hash, toi_sample=sample, seed=a.seed, outputs=sorted(res))
    json.dump(summ, open(out / "summary.json", "w"), indent=2); print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()

