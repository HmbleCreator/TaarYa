import json, re, urllib.parse
import numpy as np, pandas as pd
from taarya_workflows.real import fetch_hr23 as F, cluster_cones as CC

def clusters_tsv(n=300, seed=0):
    rng = np.random.default_rng(seed); rows = ["Name\tDist50\tnbstars07\tr50\tType", "\tpc\t\tdeg\t", "-----\t-----\t-----\t-----\t-----"]
    for i in range(n): rows.append(f"C_{i}\t{rng.uniform(100, 3000):.0f}\t{rng.integers(20, 800)}\t{rng.uniform(0.1, 5):.2f}\t{'g' if i % 7 == 0 else 'm' if i % 11 == 0 else 'o'}")
    return "#RESOURCE=VizieR\n#comment line\n" + "\n".join(rows) + "\n"

def members_tsv(name):
    rows = ["GaiaDR3\tName\tRA_ICRS\tDE_ICRS\tProb", "\t\tdeg\tdeg\t", "-----\t-----\t-----\t-----\t-----"]
    rows += [f"{3_300_000_000_000_000_000 + i + 1000 * abs(hash(name)) % 10**6 * 7}\t{name}\t{50 + i * 0.01:.3f}\t{20 + i * 0.01:.3f}\t0.9" for i in range(120)]
    rows.append(f"3299999999999999999\t{name}0\t50.0\t20.0\t0.9")            # a pattern-match neighbour (e.g. C_1 vs C_10) that must be dropped
    return "\n".join(rows) + "\n"

class FakeNet:
    def __init__(self, fail_first=False): self.calls, self.fail_first = [], fail_first
    def __call__(self, url):
        self.calls.append(url)
        if self.fail_first and len(self.calls) == 1: raise OSError("mirror down")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return members_tsv(q["Name"][0]) if q["-source"][0].endswith("members") else clusters_tsv()

def test_parser_skips_comments_units_and_dashes():
    df = F.parse_asu_tsv(clusters_tsv(5)); assert list(df.columns) == ["Name", "Dist50", "nbstars07", "r50", "Type"] and len(df) == 5 and df.Name[0] == "C_0"

def test_selection_is_open_clusters_only_seeded_and_outputs_feed_cone_builder(tmp_path):
    net = FakeNet(); r = F.run(tmp_path / "h", n=5, seed=1, min_members=100, http_get=net, mirrors=["m1", "m2"])
    cl = pd.read_csv(tmp_path / "h" / "clusters.csv"); typ = dict(zip(cl.Name, cl.Type)); assert len(r["selected"]) == 5 and all(typ[c] == "o" for c in r["selected"])
    assert r["criteria"]["open_only"] and r["criteria"]["kind_column"] == "Type"
    sm = pd.read_csv(tmp_path / "h" / "selected_members.csv", dtype=str)
    assert not sm.Name.str.endswith("0").where(sm.Name.isin([c + "0" for c in r["selected"]]), False).any() and set(sm.Name) == set(r["selected"])   # neighbour rows dropped
    assert all(v == 120 for v in r["members_per_cluster"].values())
    mem = CC.load_members(str(tmp_path / "h" / "selected_members.csv"), min_prob=0.7, min_members=100); assert set(mem.cluster) == set(r["selected"])
    again = F.run(tmp_path / "h", n=5, seed=1, http_get=(net2 := FakeNet()), mirrors=["m1"]); assert net2.calls == [] and again["selected"] == r["selected"]   # cached: zero requests
    assert F.run(tmp_path / "h2", n=5, seed=2, http_get=FakeNet(), mirrors=["m1"])["selected"] != r["selected"]

def test_mirror_fallback_and_total_failure_message(tmp_path):
    net = FakeNet(fail_first=True); df, used = F.fetch_table(F.CLUSTERS_CAT, None, ["bad", "good"], net, retries=0, sleep=0); assert used == "good" and len(df) == 300
    try: F.fetch_table(F.CLUSTERS_CAT, None, ["a", "b"], lambda u: (_ for _ in ()).throw(OSError("x")), retries=0, sleep=0); assert False
    except RuntimeError as e: assert "all mirrors failed" in str(e)
