"""
Build real cluster cones for the membership / retrieval evaluation.

Each cone is a Gaia cone query (members AND field stars, same quality cuts everywhere), with published members
MARKED inside it. Inserting only the published members would make the cone 100% pure by construction and
destroy both the membership test and the retrieval ablation -- this module exists to avoid that.

Outputs (out_dir):
  stars.csv           cluster, source_id, ra, dec, pmra, pmdec, parallax, parallax_over_error, G, bp_rp, ruwe   (whole cone)
  gold.csv            cluster, source_id, prob                     (published members, any that fall in the cone)
  edges_cone.csv      cluster, source_id                           (what cone-seeding does: EVERY cone star)
  edges_published.csv cluster, source_id, prob                     (published members inside the cone; do not score these against gold)
  manifest.json       TAP url, ADQL per cluster, cuts, UTC date, row counts, truncation flags, sha256 of every output
UNVERIFIED HERE (no network): TAP endpoint behaviour and column availability (e.g. `ruwe`). Fetch is injectable for tests.
"""
from __future__ import annotations
import hashlib, io, json, os, time
import numpy as np, pandas as pd

MEMBER_COLS = dict(id=["GaiaDR3", "source_id", "DR3Name", "Source"], cluster=["Name", "Cluster", "cluster"],
                   ra=["RA_ICRS", "RAdeg", "ra"], dec=["DE_ICRS", "DEdeg", "dec"], prob=["Prob", "proba", "probability"])
DEFAULT_TAP = "https://gaia.aip.de/tap"


def _pick(df, names):
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    raise KeyError(f"none of {names} in {list(df.columns)[:30]}")


def load_members(path, min_prob=0.7, min_members=100, max_clusters=None) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str)
    out = pd.DataFrame(dict(cluster=raw[_pick(raw, MEMBER_COLS["cluster"])],
                            source_id=pd.to_numeric(raw[_pick(raw, MEMBER_COLS["id"])].str.extract(r"(\d{6,})")[0], errors="coerce"),
                            ra=pd.to_numeric(raw[_pick(raw, MEMBER_COLS["ra"])], errors="coerce"),
                            dec=pd.to_numeric(raw[_pick(raw, MEMBER_COLS["dec"])], errors="coerce"),
                            prob=pd.to_numeric(raw[_pick(raw, MEMBER_COLS["prob"])], errors="coerce")))
    out = out.dropna(subset=["source_id", "ra", "dec"]); out["source_id"] = out.source_id.astype("int64"); out = out[out.prob >= min_prob]
    keep = out.cluster.value_counts(); keep = keep[keep >= min_members].index.tolist()
    if max_clusters: keep = keep[:max_clusters]
    return out[out.cluster.isin(keep)].reset_index(drop=True)


CLUSTER_COLS = dict(name=["Name", "Cluster", "cluster"], dist=["Dist", "dist", "d", "Distance", "dpc"], plx=["Plx", "plx", "parallax"],
                    n=["nbstars07", "N", "Nstars", "n_members", "nbstars"], r50=["r50", "R50", "rc", "r50deg"])


def select_clusters(clusters_csv, max_dist_pc=1000.0, min_members=100, max_r50_deg=2.0, n=30, seed=0):
    """Pre-specified, seeded selection from a published cluster table (Hunt & Reffert `clusters`). Criteria + seed go in the manifest,
    so the sample cannot be cherry-picked toward clusters on which a method looks good. Unverified here: column names (tolerant lookup)."""
    raw = pd.read_csv(clusters_csv); nm = raw[_pick(raw, CLUSTER_COLS["name"])]
    try: dist = pd.to_numeric(raw[_pick(raw, CLUSTER_COLS["dist"])], errors="coerce")
    except KeyError: dist = 1000.0 / pd.to_numeric(raw[_pick(raw, CLUSTER_COLS["plx"])], errors="coerce")
    cnt = pd.to_numeric(raw[_pick(raw, CLUSTER_COLS["n"])], errors="coerce"); r50 = pd.to_numeric(raw[_pick(raw, CLUSTER_COLS["r50"])], errors="coerce")
    ok = (dist <= max_dist_pc) & (cnt >= min_members) & (r50 <= max_r50_deg)
    pool = sorted(nm[ok].astype(str).tolist()); rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(pool, size=min(n, len(pool)), replace=False).tolist()) if pool else []
    return dict(selected=pick, eligible=len(pool), criteria=dict(max_dist_pc=max_dist_pc, min_members=min_members, max_r50_deg=max_r50_deg, n=n, seed=seed))


def cone_params(g: pd.DataFrame, min_deg=0.5, cap_deg=5.0):
    """Centre = mean unit vector (safe across RA wrap); radius = 95th percentile member separation, clipped."""
    ra, dec = np.radians(g.ra.to_numpy()), np.radians(g.dec.to_numpy())
    v = np.column_stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]).mean(0); v /= np.linalg.norm(v)
    ra0, dec0 = np.degrees(np.arctan2(v[1], v[0])) % 360.0, np.degrees(np.arcsin(v[2]))
    sep = np.degrees(np.arccos(np.clip(np.cos(dec) * np.cos(np.radians(dec0)) * np.cos(ra - np.radians(ra0)) + np.sin(dec) * np.sin(np.radians(dec0)), -1, 1)))
    r95 = float(np.percentile(sep, 95))
    return float(ra0), float(dec0), float(np.clip(r95, min_deg, cap_deg)), r95 > cap_deg


def adql(ra0, dec0, r, snr_min, g_max, top):
    return (f"SELECT TOP {top} source_id, ra, dec, pmra, pmdec, parallax, parallax_over_error, phot_g_mean_mag AS G, bp_rp, ruwe "
            f"FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra0:.6f},{dec0:.6f},{r:.6f})) "
            f"AND parallax_over_error >= {snr_min} AND phot_g_mean_mag <= {g_max} AND pmra IS NOT NULL")


def tap_sync_csv(tap_url, query, timeout=300):
    import requests
    r = requests.post(tap_url.rstrip("/") + "/sync", data=dict(REQUEST="doQuery", LANG="ADQL", FORMAT="csv", QUERY=query), timeout=timeout,
                      headers={"User-Agent": "taarya-cluster-cones"})
    r.raise_for_status()
    if r.content.strip().startswith(b"<"):
        from astropy.io.votable import parse_single_table
        df = parse_single_table(io.BytesIO(r.content)).to_table().to_pandas()
        if "datalinkID" in df.columns and "source_id" not in df.columns:
            df = df.rename(columns={"datalinkID": "source_id"})
        return df
    return pd.read_csv(io.BytesIO(r.content), dtype={"source_id": "int64"})


def build(members_csv, out_dir, fetch=None, tap_url=DEFAULT_TAP, snr_min=5.0, g_max=18.0, top=60000, min_prob=0.7,
          min_members=100, max_clusters=None, sleep=0.5):
    os.makedirs(out_dir, exist_ok=True)
    fetch = fetch or (lambda q: tap_sync_csv(tap_url, q))
    mem = load_members(members_csv, min_prob, min_members, max_clusters)
    S, GD, EP, EC, man = [], [], [], [], dict(tap_url=tap_url, retrieved_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                              cuts=dict(parallax_over_error_min=snr_min, G_max=g_max, member_prob_min=min_prob), clusters={})
    for name, g in mem.groupby("cluster"):
        ra0, dec0, r, capped = cone_params(g); q = adql(ra0, dec0, r, snr_min, g_max, top)
        st = fetch(q); trunc = len(st) >= top
        info = dict(ra0=ra0, dec0=dec0, radius_deg=r, radius_capped=bool(capped), adql=q, n_cone=int(len(st)), truncated=bool(trunc))
        if trunc:
            info["status"] = "SKIPPED: row cap hit (cone truncated, membership would be biased); lower G_max or radius"; man["clusters"][name] = info; continue
        st = st.assign(cluster=name, source_id=st.source_id.astype("int64"))
        inside = g[g.source_id.isin(set(st.source_id))]
        info.update(status="ok", n_published_total=int(len(g)), n_published_in_cone=int(len(inside)), member_coverage=round(len(inside) / len(g), 3),
                    cone_purity=round(len(inside) / max(len(st), 1), 4))
        man["clusters"][name] = info
        S.append(st); GD.append(inside.assign(cluster=name)[["cluster", "source_id", "prob"]]); EC.append(st[["cluster", "source_id"]]); EP.append(GD[-1])
        time.sleep(sleep if fetch is not None and sleep else 0)
    files = {}
    for fname, parts in (("stars.csv", S), ("gold.csv", GD), ("edges_cone.csv", EC), ("edges_published.csv", EP)):
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        path = os.path.join(out_dir, fname); df.to_csv(path, index=False); files[fname] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    man["sha256"] = files; json.dump(man, open(os.path.join(out_dir, "manifest.json"), "w"), indent=2)
    return man


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser()
    ap.add_argument("--members", required=True); ap.add_argument("--out", default="cluster_cones"); ap.add_argument("--tap", default=DEFAULT_TAP)
    ap.add_argument("--max-clusters", type=int, default=None); ap.add_argument("--g-max", type=float, default=18.0); a = ap.parse_args()
    m = build(a.members, a.out, tap_url=a.tap, max_clusters=a.max_clusters, g_max=a.g_max)
    print(json.dumps({k: {x: v[x] for x in ("status", "n_cone", "member_coverage", "cone_purity") if x in v} for k, v in m["clusters"].items()}, indent=2))
