import json
from taarya_workflows.real import audit_numbers as A

TEX = r"""
\section{Results}
% a commented 99.9\% that must be ignored
Graph PageRank reached AP \graphPPRAP{} on three clusters (Hunt \& Reffert 2023, \cite{Hunt2023}).
The sourced value was 0.868 [see Table 3] with 1,336 published members.
Stars in the catalogue: 34{,}820 in total, and citation precision was below 5\% against SIMBAD.
\begin{equation}
x = 1234.5678
\end{equation}
"""

def test_unsourced_numbers_flagged_and_sourced_or_macro_numbers_pass(tmp_path):
    t = tmp_path / "p.tex"; t.write_text(TEX)
    r = tmp_path / "r.json"; r.write_text(json.dumps({"aggregate": {"graph_ppr": {"AP": {"mean": 0.868}}}, "published": 1336, "frac": 0.0123}))
    bad = A.audit(t, [r]); toks = {b["token"] for b in bad}
    assert "34{,}820" in toks and "5%" in toks                              # stale count and the unmeasured claim
    assert not ({"0.868", "1,336", "99.9%", "2023", "1234.5678"} & toks)   # sourced, commented, a year, and inside an equation

def test_allowlist_requires_explicit_entry(tmp_path):
    t = tmp_path / "p.tex"; t.write_text(TEX); r = tmp_path / "r.json"; r.write_text("{}")
    al = tmp_path / "allow.txt"; al.write_text("34820  # catalogue size, from manifest.json, regenerate before submission\n")
    toks = {b["token"] for b in A.audit(t, [r], al)}; assert "34{,}820" not in toks and "5%" in toks

def test_percentages_match_fractions_in_results(tmp_path):
    t = tmp_path / "p.tex"; t.write_text("Cone purity was 2.6\\% in the Pleiades."); r = tmp_path / "r.json"; r.write_text(json.dumps({"cone_purity": 0.0258}))
    assert A.audit(t, [r]) == []

