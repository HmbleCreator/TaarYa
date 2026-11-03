import tempfile, pathlib, pandas as pd
from taarya_workflows.real import snapshot_counts as S, make_tables as T

def fakes(synth=560, neo_stars=5560):
    pg = lambda sql: [("GAIA_DR3", 5000), ("SYNTHETIC_BENCHMARK", synth)] if "GROUP BY" in sql else [(13,)]
    def neo(q):
        if "Star" in q: return [[neo_stars]]
        if "Paper" in q: return [[4997]]
        if "MEMBER_OF" in q: return [[28881]]
        return [[0]]
    return pg, neo, (lambda: 4997)

def test_snapshot_separates_synthetic_and_warns_on_drift():
    s = S.snapshot(*fakes(), regions_sql="SELECT 13")
    assert s["postgres"]["stars_real"] == 5000 and s["postgres"]["stars_synthetic"] == 560 and s["postgres"]["regions"] == 13
    assert any("synthetic" in w for w in s["warnings"]) and not any("out of sync" in w for w in s["warnings"])
    assert any("out of sync" in w for w in S.snapshot(*fakes(neo_stars=29798))["warnings"])
    assert S.snapshot(*fakes(synth=0))["warnings"] == [] or all("synthetic" not in w for w in S.snapshot(*fakes(synth=0))["warnings"])

def test_counts_become_macros_with_the_real_numbers():
    toi = pd.DataFrame(dict(label=[0, 0, 1, -1, -1]))
    s = S.snapshot(*fakes(), toi_df=toi); d = pathlib.Path(tempfile.mkdtemp()); T.build_tex({"counts": s}, d)
    n = (d / "numbers.tex").read_text()
    assert "\\newcommand{\\nStarsReal}{5{,}000}" in n and "\\newcommand{\\nStarsSynthetic}{560}" in n and "\\nMemberOfEdges}{28{,}881}" in n
    assert "\\newcommand{\\nTOICatalog}{5}" in n and "\\nTOICatalogPlanets}{2}" in n
