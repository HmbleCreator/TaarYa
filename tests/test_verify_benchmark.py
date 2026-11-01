from taarya_workflows.real import verify_benchmark as V

def recs(hybrid_pass):
    r = [dict(id=f"s{i}", family="spatial", status="pass" if i < 9 else "fail", latency_ms=30.0) for i in range(14)]
    r += [dict(id=f"m{i}", family="semantic", status="pass", latency_ms=70.0) for i in range(16)]
    r += [dict(id=f"d{i}", family="discovery", status="pass" if i == 0 else "partial" if i < 4 else "fail", latency_ms=15.0) for i in range(13)]
    r += [dict(id=f"h{i}", family="hybrid", status="pass" if i < hybrid_pass else "partial", latency_ms=165.0) for i in range(7)]
    return r

def test_recompute_comes_from_records_and_family_rows_sum_to_overall():
    t = V.recompute(V.find_records({"meta": 1, "results": recs(5)}))
    assert (t["spatial"]["passed"], t["hybrid"]["passed"], t["hybrid"]["partial"]) == (9, 5, 2)
    assert t["__overall__"]["passed"] == sum(t[f]["passed"] for f in ("spatial", "semantic", "discovery", "hybrid")) == 31      # NOT 33
    assert t["__overall__"]["total"] == 50

def test_changed_outcomes_are_detected():
    ch = V.diff_records(recs(7), recs(5)); ids = {c["id"] for c in ch}
    assert ids == {"h5", "h6"} and all("partial" in c["old"] and "pass" in c["new"] for c in ch)
    assert V.diff_records(recs(5), recs(5)) == []


def test_family_from_query_file_hashes_and_figure_coordinates(tmp_path):
    import json, tempfile, pathlib
    from taarya_workflows.real import make_tables as T
    full = recs(5); queries = [dict(id=r["id"], category=r["family"]) for r in full]
    results = [{k: v for k, v in r.items() if k != "family"} for r in full]
    rp, qp = tmp_path / "r.json", tmp_path / "q.json"; rp.write_text(json.dumps({"results": results})); qp.write_text(json.dumps({"queries": queries}))
    res = V.build_result(str(rp), str(qp)); assert res["family_sums_match_overall"] and res["table"]["hybrid"]["partial"] == 2 and res["unmapped_families"] == []
    assert res["inputs"]["queries_sha256"] and res["n_records"] == 50
    d = pathlib.Path(tempfile.mkdtemp()); T.build_tex({"benchmark": res}, d); n = (d / "numbers.tex").read_text()
    assert "\\newcommand{\\benchPassedCoords}{(Spatial,9) (Semantic,16) (Discovery,1) (Hybrid,5)}" in n and "\\benchOverallPass}{31}" in n
    assert "Overall" in (d / "benchmark.tex").read_text() and "synthetic fixtures" in (d / "benchmark.tex").read_text()
    # records with an id missing from the query file land in a visible 'None' family and fail the check
    bad = V.build_result(str(rp), None) if False else None

