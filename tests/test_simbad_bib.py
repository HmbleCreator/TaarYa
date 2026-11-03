import numpy as np, pandas as pd, pytest
from taarya_workflows.core import MIN_UNITS
from taarya_workflows.real import simbad_bib as SB


def test_normalize_id_preserves_64bit_gaia_ids():
    big_id = 4295837210984729182
    assert SB.normalize_id(big_id) == "4295837210984729182"
    assert SB.normalize_id(str(big_id)) == "4295837210984729182"
    assert SB.normalize_id(np.int64(big_id)) == "4295837210984729182"


def test_bibcode_and_arxiv_matching():
    # ADS arXiv bibcode: 2020arXiv200407274C
    gold = "2020arXiv200407274C"
    paper_exact = {"bibcode": "2020arXiv200407274C", "arxiv_id": "2004.07274"}
    paper_arxiv_only = {"bibcode": None, "arxiv_id": "2004.07274"}
    paper_diff = {"bibcode": "2018A&A...616A...1G", "arxiv_id": "1804.09365"}

    assert SB.match_paper_to_bibcode(paper_exact, gold) is True
    assert SB.match_paper_to_bibcode(paper_arxiv_only, gold) is True
    assert SB.match_paper_to_bibcode(paper_diff, gold) is False


def test_adql_query_generation():
    q = SB.adql_bib_query(["1234567890", "9876543210"])
    assert "SELECT TOP" in q
    assert "FROM ident i" in q
    assert "'Gaia DR3 1234567890'" in q
    assert "'9876543210'" in q


def test_positive_control_perfect_linking():
    # 10 stars, each correctly linked to its single cited paper
    sids = [f"33000000000000000{i}" for i in range(10)]
    pids = [f"paper_{i}" for i in range(10)]
    bibs = [f"2020A&A...640A..{i:02d}X" for i in range(10)]

    edges = pd.DataFrame({"source_id": sids, "paper_id": pids})
    papers = pd.DataFrame({"paper_id": pids, "bibcode": bibs, "arxiv_id": [f"2001.{i:05d}" for i in range(10)]})
    gold = pd.DataFrame({"source_id": sids, "bibcode": bibs})

    res = SB.evaluate_literature_links(edges, papers, gold, seed=42)
    agg = res["aggregate"]["taarya_edges"]
    assert agg["precision"]["mean"] == 1.0
    assert agg["recall"]["mean"] == 1.0
    assert agg["f1"]["mean"] == 1.0
    # 10 stars >= MIN_UNITS (8), so intervals are computed
    assert agg["precision"]["ci95"][0] == 1.0


def test_cluster_mediated_dilution_negative_verdict():
    # Simulate cluster-mediated linking:
    # 10 stars in a cluster; each linked to 10 papers about the cluster.
    # But only star 0 is actually cited in 1 paper. Stars 1-9 are never cited.
    sids = [f"44000000000000000{i}" for i in range(10)]
    pids = [f"cluster_paper_{j}" for j in range(10)]
    bibs = [f"2022ApJ...900..{j:02d}A" for j in range(10)]

    edge_rows = []
    for sid in sids:
        for pid in pids:
            edge_rows.append({"source_id": sid, "paper_id": pid})
    edges = pd.DataFrame(edge_rows)

    papers = pd.DataFrame({"paper_id": pids, "bibcode": bibs, "arxiv_id": [f"2201.{j:05d}" for j in range(10)]})
    # Only star 0 is actually in paper 0
    gold = pd.DataFrame({"source_id": [sids[0]], "bibcode": [bibs[0]]})

    res = SB.evaluate_literature_links(edges, papers, gold, seed=42)
    agg = res["aggregate"]["taarya_edges"]

    # Star 0 has precision = 1/10 = 0.10. Stars 1-9 have precision = 0/10 = 0.0.
    # Mean precision across 10 stars = 0.01 (1%), well below 5%.
    assert agg["precision"]["mean"] == pytest.approx(0.01, abs=0.005)
    assert "negligible precision" in res["verdict"]
    assert "cluster-level topicality" in res["verdict"]


def test_small_sample_refuses_inference_intervals():
    # 4 stars < MIN_UNITS (8) -> descriptive only, no ci95
    sids = [f"55000000000000000{i}" for i in range(4)]
    pids = [f"paper_{i}" for i in range(4)]
    bibs = [f"2021MNRAS.500..{i:02d}Y" for i in range(4)]

    edges = pd.DataFrame({"source_id": sids, "paper_id": pids})
    papers = pd.DataFrame({"paper_id": pids, "bibcode": bibs})
    gold = pd.DataFrame({"source_id": sids, "bibcode": bibs})

    res = SB.evaluate_literature_links(edges, papers, gold)
    assert res["aggregate"]["taarya_edges"]["precision"]["ci95"] == [None, None]
    assert "descriptive only" in res["caution"]

