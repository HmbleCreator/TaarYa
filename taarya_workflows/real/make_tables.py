"""
Results JSON -> LaTeX. Every number in the paper's real-data section comes from here, never from hand-copying.
Writes  numbers.tex (\\newcommand macros for in-text numbers) and one tabular fragment per result.
Figure coordinates: \\expandafter\\addplot\\expandafter coordinates\\expandafter{\\benchPassedCoords}; (standard pgfplots idiom for macro-held data; untested in the build sandbox).
In the paper:  \\input{tables/numbers.tex}  then write "\\toiDeltaAUC{} (95\\% CI \\toiDeltaCI)" in the text.
"""
from __future__ import annotations
import json, re
from pathlib import Path


def esc(s) -> str:
    return re.sub(r"([_&%#$])", r"\\\1", str(s))


def f(x, nd=3): return "--" if x is None else f"{x:.{nd}f}"


def mci(d, nd=3):
    if not d or d.get("mean") is None: return "--"
    lo, hi = d["ci95"]
    if lo is None: return f"{d['mean']:.{nd}f} (n={d.get('n', '?')}, no CI)"
    return f"{d['mean']:.{nd}f} [{lo:.{nd}f}, {hi:.{nd}f}]"


def macro(name, val): return f"\\newcommand{{\\{name}}}{{{val}}}\n"


def tabular(cols, rows, caption, label):
    body = " \\\\\n".join(" & ".join(r) for r in rows)
    return (f"\\begin{{table}}[htbp]\\centering\\small\n\\caption{{{caption}}}\\label{{{label}}}\n\\begin{{tabular}}{{{'l' + 'r' * (len(cols) - 1)}}}\n\\toprule\n"
            f"{' & '.join(cols)} \\\\\n\\midrule\n{body} \\\\\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


def build_tex(results: dict, out_dir) -> list:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True); nums = ""; made = []
    m = results.get("membership")
    if m and m.get("per_cluster"):
        pc = m["per_cluster"]
        rows = [[esc(c), f"{v['n_cone']:,}", str(v["n_gold_in_cone"]), f"{100 * v['cone_purity']:.1f}\\%", f(v["gold_coverage"], 2), f(v["jaccard_edges_vs_cone"], 3)] for c, v in pc.items()]
        (out / "membership_diag.tex").write_text(tabular(["Cluster", "Cone stars", "Published members in cone", "Cone purity", "Member coverage", "Jaccard(edges, cone)"], rows,
                                                         "Seeding cones versus published membership (Hunt \\& Reffert 2023).", "tab:membership_diag")); made.append("membership_diag.tex")
        a = m["aggregate"]
        rows = [[esc(k), mci(v["precision"]), mci(v["recall"]), mci(v["f1"])] for k, v in a.items()]
        (out / "membership_methods.tex").write_text(tabular(["Method", "Precision", "Recall", "F1"], rows, f"Membership recovery, mean over {m['n_clusters']} clusters (95\\% bootstrap CI).", "tab:membership_methods")); made.append("membership_methods.tex")
        nums += macro("nMembClusters", m["n_clusters"]) + macro("medianJaccardEdgesCone", f(m["median_jaccard_edges_vs_cone"], 3))
        nums += macro("edgesPrecision", f(a["taarya_member_of_edges"]["precision"]["mean"], 3))
    r = results.get("retrieval")
    if r and r.get("aggregate"):
        rows = []
        for k, v in r["aggregate"].items():
            d = v.get("AP_diff_vs_seed_box"); rows.append([esc(k), mci(v["AP"]), mci(v["P@50"]), mci(v["nDCG@100"]), mci(d) if d else "baseline"])
        (out / "retrieval.tex").write_text(tabular(["Method", "AP", "P@50", "nDCG@100", "$\\Delta$AP vs seed box"], rows,
                                                   f"Cluster-member retrieval from {r['n_seeds']} seeds, mean over {r['n_clusters']} clusters (95\\% CI).", "tab:retrieval")); made.append("retrieval.tex")
        nums += macro("nRetrClusters", r["n_clusters"]) + macro("graphCurrentAP", f(r["aggregate"]["current_graph_traversal"]["AP"]["mean"], 3))
        if "graph_ppr" in r["aggregate"]: nums += macro("graphPPRAP", f(r["aggregate"]["graph_ppr"]["AP"]["mean"], 3))
    t = results.get("toi")
    if t:
        rows = [[esc(k), mci(dict(mean=t[k]["auc"], ci95=t[k]["ci95"]))] for k in ("covariates_only_cv", "neighbour_only_cv", "covariates+neighbour_cv")]
        d = t["delta_auc_with_vs_without_neighbour"]; mo = t.get("matched_operating_point", {})
        rows.append(["$\\Delta$AUC (with minus without neighbour)", mci(d)])
        if mo: rows.append(["Planets lost at 80\\% FP rejection: without / with", f"{mo['planet_loss_covariates_only']:.3f} / {mo['planet_loss_with_neighbour']:.3f}"])
        (out / "toi.tex").write_text(tabular(["Model", "AUC (95\\% CI)"], rows, f"TOI vetting: neighbour feature versus TOI-table covariates ({t['n']['stars']} stars). {esc(t['verdict'])}", "tab:toi")); made.append("toi.tex")
        nums += macro("toiDeltaAUC", f(d["mean"], 3)) + macro("toiDeltaCI", f"[{f(d['ci95'][0])}, {f(d['ci95'][1])}]") + macro("toiNStars", t["n"]["stars"])
        nums += macro("toiNPlanets", t["n"]["planets"]) + macro("toiNFP", t["n"]["false_positives"])
    if m and m.get("per_cluster"):
        nums += macro("nConeStars", f"{sum(v['n_cone'] for v in m['per_cluster'].values()):,}".replace(",", "{,}")) + macro("nPublishedInCones", f"{sum(v['n_gold_in_cone'] for v in m['per_cluster'].values()):,}".replace(",", "{,}"))
    bm = results.get("benchmark")
    if bm:
        tab = bm["table"]; order = [k for k in ("spatial", "semantic", "discovery", "hybrid") if k in tab] + [k for k in tab if k not in ("spatial", "semantic", "discovery", "hybrid", "__overall__")]
        rows = [[esc(k.capitalize()), str(tab[k]["total"]), str(tab[k]["passed"]), str(tab[k]["partial"]), str(tab[k]["failed"]), f"{tab[k]['pass_rate']:.1f}\\%", "--" if tab[k]["mean_latency"] is None else f"{tab[k]['mean_latency']:.1f}"] for k in order]
        o = tab["__overall__"]; rows.append(["\\textbf{Overall}", str(o["total"]), str(o["passed"]), str(o["partial"]), str(o["failed"]), f"{o['pass_rate']:.1f}\\%", "--"])
        (out / "benchmark.tex").write_text(tabular(["Family", "Total", "Passed", "Partial", "Failed", "Pass rate", "Mean latency (ms)"], rows,
            f"Software regression suite ({o['total']} prompts; project-authored pass/partial/fail checks, run on a corpus that included synthetic fixtures). Recomputed from per-query records (results {bm['inputs']['results_sha256']}).", "tab:benchmark")); made.append("benchmark.tex")
        coords = lambda key: " ".join(f"({k.capitalize()},{tab[k][key]})" for k in order)
        nums += macro("benchPassedCoords", coords("passed")) + macro("benchPartialCoords", coords("partial")) + macro("benchFailedCoords", coords("failed"))
        nums += macro("benchOverallPass", str(o["passed"])) + macro("benchOverallTotal", str(o["total"])) + macro("benchOverallRate", f"{o['pass_rate']:.1f}\\%")
    c = results.get("counts")
    if c:
        g = lambda v: f"{v:,}".replace(",", "{,}")
        nums += macro("nStarsReal", g(c["postgres"]["stars_real"])) + macro("nStarsSynthetic", g(c["postgres"]["stars_synthetic"])) + macro("nPapersQdrant", g(c["qdrant"]["papers"]))
        nums += macro("nStarNodes", g(c["neo4j"]["nodes_star"])) + macro("nPaperNodes", g(c["neo4j"]["nodes_paper"])) + macro("nClusterNodes", g(c["neo4j"]["nodes_cluster"]))
        nums += macro("nMemberOfEdges", g(c["neo4j"]["edges_member_of"])) + macro("nCoversEdges", g(c["neo4j"]["edges_covers"])) + macro("nMentionedInEdges", g(c["neo4j"]["edges_mentioned_in"]))
        if "regions" in c["postgres"]: nums += macro("nRegions", c["postgres"]["regions"])
        gap_stars = c["postgres"]["stars_total"] - c["neo4j"]["nodes_star"]
        nums += macro("nStoreStarGap", f"{gap_stars:,}".replace(",", "{,}"))
        gap_papers = c["neo4j"]["nodes_paper"] - c["qdrant"]["papers"]
        nums += macro("nStorePaperGap", f"{gap_papers:,}".replace(",", "{,}"))
        if "toi_catalog" in c:
            t = c["toi_catalog"]; nums += macro("nTOICatalog", g(t["total"])) + macro("nTOICatalogPlanets", g(t["planets_cp_kp"])) + macro("nTOICatalogFP", g(t["false_positives"]))
    (out / "numbers.tex").write_text("% generated by make_tables.py -- do not edit by hand\n" + nums); made.append("numbers.tex")
    return made


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("--results", default="results"); ap.add_argument("--out", default="tables"); a = ap.parse_args()
    res = {p.stem: json.loads(p.read_text()) for p in Path(a.results).glob("*.json") if p.stem in ("membership", "retrieval", "toi", "counts", "benchmark")}
    print(build_tex(res, a.out))
