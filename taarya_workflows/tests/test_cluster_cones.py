import numpy as np, pandas as pd, pytest
from taarya_workflows.real import cluster_cones as C
from taarya_workflows.real import membership as M

def members_csv(tmp_path, rng):
    rows = []
    for name, ra0, dec0 in [("Melotte_25", 66.7, 15.9), ("NGC_2516", 119.5, -60.8), ("Wrap", 359.9, 10.0)]:
        n = 150; ra = (ra0 + rng.normal(0, 0.6 / np.cos(np.radians(dec0)), n)) % 360; dec = dec0 + rng.normal(0, 0.6, n)
        for i in range(n): rows.append(dict(GaiaDR3=f"Gaia DR3 {3_300_000_000_000_000_000 + hash(name) % 10**6 * 1000 + i}", Name=name,
                                           RA_ICRS=ra[i], DE_ICRS=dec[i], Prob=rng.uniform(0.5, 1.0)))
    p = tmp_path / "m.csv"; pd.DataFrame(rows).to_csv(p, index=False); return str(p)

def fake_fetch_factory(mem_df, rng, n_field=4000, top=60000):
    def fetch(q):
        name = next(n for n in mem_df.cluster.unique() if True)               # replaced below by parsing coordinates
        import re; ra0, dec0 = map(float, re.search(r"CIRCLE\('ICRS',([\d\.\-]+),([\d\.\-]+),", q).groups())
        # members near this centre + field stars (ids in the real Gaia range, > 2^53 so float conversion would corrupt them)
        d = np.hypot(((mem_df.ra - ra0 + 180) % 360 - 180) * np.cos(np.radians(dec0)), mem_df.dec - dec0)
        near = mem_df[d < 3.0]
        field_ids = rng.integers(3_000_000_000_000_000_000, 3_400_000_000_000_000_000, n_field)
        ids = np.r_[near.source_id.to_numpy(), field_ids]
        return pd.DataFrame(dict(source_id=ids.astype("int64"), ra=ra0, dec=dec0, pmra=rng.normal(0, 10, len(ids)), pmdec=rng.normal(0, 10, len(ids)),
                                 parallax=rng.uniform(1, 10, len(ids)), parallax_over_error=20.0, G=15.0, bp_rp=1.0, ruwe=1.0))
    return fetch

def test_cone_centre_survives_ra_wrap_and_radius_is_clipped():
    rng = np.random.default_rng(0); g = pd.DataFrame(dict(ra=(359.9 + rng.normal(0, 0.5, 300)) % 360, dec=10 + rng.normal(0, 0.5, 300)))
    ra0, dec0, r, capped = C.cone_params(g); assert min(ra0, 360 - ra0) < 0.2 and abs(dec0 - 10) < 0.2 and 0.5 <= r <= 5.0 and not capped
    wide = pd.DataFrame(dict(ra=rng.uniform(0, 40, 300), dec=rng.uniform(-20, 20, 300))); assert C.cone_params(wide)[3] is True

def test_build_makes_impure_real_cones_with_manifest_and_exact_ids(tmp_path):
    rng = np.random.default_rng(1); mp = members_csv(tmp_path, rng); mem = C.load_members(mp, min_prob=0.7, min_members=20)
    man = C.build(mp, str(tmp_path / "out"), fetch=fake_fetch_factory(mem, rng), min_members=20, sleep=0)
    for name, info in man["clusters"].items():
        assert info["status"] == "ok" and info["cone_purity"] < 0.2                       # members are a SMALL part of the cone, as in reality
        assert info["member_coverage"] > 0.8 and "SELECT TOP" in info["adql"]
    st = pd.read_csv(tmp_path / "out" / "stars.csv", dtype={"source_id": str}); assert st.source_id.str.len().ge(19).all()
    assert set(man["sha256"]) == {"stars.csv", "gold.csv", "edges_cone.csv", "edges_published.csv"}
    # the output plugs straight into the membership evaluator and the cone-seeding diagnostic fires
    stars = pd.read_csv(tmp_path / "out" / "stars.csv", dtype={"source_id": str}); edges = pd.read_csv(tmp_path / "out" / "edges_cone.csv", dtype={"source_id": str})
    gold = pd.read_csv(tmp_path / "out" / "gold.csv", dtype={"source_id": str}); gold["source_id"] = gold.source_id.astype("int64")
    r = M.evaluate_membership(stars, edges, gold, min_gold=20); assert r["member_of_is_cone_seeding"] and r["n_clusters"] == 3

def test_truncated_cone_is_skipped_not_silently_biased(tmp_path):
    rng = np.random.default_rng(2); mp = members_csv(tmp_path, rng)
    man = C.build(mp, str(tmp_path / "o2"), fetch=lambda q: pd.DataFrame(dict(source_id=np.arange(100, dtype="int64"))), top=100, min_members=20, sleep=0)
    assert all(v["status"].startswith("SKIPPED") for v in man["clusters"].values())
