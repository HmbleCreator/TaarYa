"""
Is the benchmark summary a pure function of its per-query records, and have those records changed since a frozen tag?

  python -m taarya_workflows.real.verify_benchmark eval/benchmark_results.json --baseline eval-v2:eval/benchmark_results.json

Prints the per-family table recomputed FROM THE PER-QUERY RECORDS (never from any stored summary), checks that family rows sum to the overall
row, and lists every record whose outcome differs from the baseline version in git. Exit 1 if per-query outcomes changed.
Schema is discovered (tolerant key names); if yours differs, extend the *_KEYS tuples.
"""
from __future__ import annotations
import hashlib, json, subprocess, sys
from collections import defaultdict

FAM_KEYS = ("family", "category", "type", "task_family", "group")
STAT_KEYS = ("status", "result", "outcome", "verdict", "pass_fail")
LAT_KEYS = ("latency_ms", "elapsed_ms", "latency", "duration_ms", "time_ms")
ID_KEYS = ("id", "query_id", "qid", "query", "prompt", "name")
PASS, PART = {"pass", "passed", "success", "ok", "true"}, {"partial", "partially"}


def _first(d, keys):
    for k in keys:
        if k in d: return d[k]
    return None


def find_records(obj, require_family=True):
    """Largest list of dicts that carry both a family-like and a status-like key."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and sum(_first(x, STAT_KEYS) is not None and (_first(x, FAM_KEYS) is not None or require_family is False) for x in o) >= 0.8 * len(o):
                if len(o) > len(best): best = o
            for x in o: walk(x)
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
    walk(obj); return best


def norm_status(v) -> str:
    s = str(v).strip().lower()
    return "pass" if s in PASS else "partial" if s in PART else "fail"


def family_map(queries_obj) -> dict:
    """id -> family from the benchmark definition file, for result records that carry no family."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and sum(_first(x, ID_KEYS) is not None and _first(x, FAM_KEYS) is not None for x in o) >= 0.8 * len(o):
                if len(o) > len(best): best = o
            for x in o: walk(x)
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
    walk(queries_obj); return {str(_first(x, ID_KEYS)): str(_first(x, FAM_KEYS)) for x in best}


def recompute(records, fmap=None) -> dict:
    fam = defaultdict(lambda: dict(total=0, passed=0, partial=0, failed=0, lat=[]))
    for r in records:
        fk = _first(r, FAM_KEYS)
        if fk is None and fmap: fk = fmap.get(str(_first(r, ID_KEYS)))
        f = fam[str(fk)]; st = norm_status(_first(r, STAT_KEYS)); f["total"] += 1
        f["passed" if st == "pass" else "partial" if st == "partial" else "failed"] += 1
        l = _first(r, LAT_KEYS)
        if isinstance(l, (int, float)): f["lat"].append(float(l))
    out = {}
    for k, v in fam.items():
        out[k] = dict(total=v["total"], passed=v["passed"], partial=v["partial"], failed=v["failed"], pass_rate=round(100 * v["passed"] / v["total"], 1),
                      mean_latency=round(sum(v["lat"]) / len(v["lat"]), 1) if v["lat"] else None)
    tot = {k: sum(v[k] for v in out.values()) for k in ("total", "passed", "partial", "failed")}
    out["__overall__"] = dict(tot, pass_rate=round(100 * tot["passed"] / tot["total"], 1) if tot["total"] else None)
    return out


def diff_records(new, old) -> list:
    key = lambda r, i: str(_first(r, ID_KEYS) if _first(r, ID_KEYS) is not None else i)
    a = {key(r, i): r for i, r in enumerate(old)}; b = {key(r, i): r for i, r in enumerate(new)}; ch = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b: ch.append(dict(id=k, change="added" if k in b else "removed")); continue
        o, n = norm_status(_first(a[k], STAT_KEYS)), norm_status(_first(b[k], STAT_KEYS)); fo, fn = _first(a[k], FAM_KEYS), _first(b[k], FAM_KEYS)
        if o != n or fo != fn: ch.append(dict(id=k, change="outcome/family", old=f"{fo}:{o}", new=f"{fn}:{n}"))
    return ch


def _sha(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def build_result(results_path, queries_path=None, baseline=None) -> dict:
    """results/benchmark.json: recomputed table + hashes of every input, so the paper's table cannot drift from the records."""
    fmap = family_map(json.load(open(queries_path, encoding="utf-8-sig"))) if queries_path else None
    recs = find_records(json.load(open(results_path, encoding="utf-8-sig")), require_family=fmap is None)
    if not recs: raise ValueError("no per-query records found")
    tab = recompute(recs, fmap)
    unmapped = [k for k in tab if k in ("None", "none")]
    out = dict(table=tab, n_records=len(recs), inputs=dict(results_sha256=_sha(results_path), queries_sha256=_sha(queries_path) if queries_path else None),
               family_sums_match_overall=all(sum(v[k] for n, v in tab.items() if n != "__overall__") == tab["__overall__"][k] for k in ("total", "passed", "partial", "failed")),
               unmapped_families=unmapped)
    if baseline:
        ch = diff_records(recs, find_records(_git_show(baseline), require_family=False)); out["baseline"] = dict(spec=baseline, n_changed=len(ch), changed=ch)
    return out


def _git_show(spec):
    return json.loads(subprocess.check_output(["git", "show", spec], text=True, stderr=subprocess.DEVNULL))


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("results"); ap.add_argument("--queries"); ap.add_argument("--out")
    ap.add_argument("--baseline", help="git spec of the FIRST commit with these records (not a movable tag), e.g. abc1234:eval/benchmark_results.json"); a = ap.parse_args()
    res = build_result(a.results, a.queries, a.baseline); tab = res["table"]
    if a.out: json.dump(res, open(a.out, "w"), indent=2)
    print(f"{'family':12s} total passed partial failed pass% lat_ms")
    for k, v in tab.items(): print(f"{k:12s} {v['total']:5d} {v['passed']:6d} {v.get('partial', 0):7d} {v.get('failed', 0):6d} {v['pass_rate']:5} {v.get('mean_latency')}")
    print("\nfamily rows sum to overall:", res["family_sums_match_overall"], "| input hashes:", res["inputs"])
    bad = res.get("baseline", {}).get("n_changed", 0)
    if a.baseline: print(f"{bad} per-query record(s) differ from {a.baseline}"); [print("  ", c) for c in res["baseline"]["changed"]]
    sys.exit(1 if bad or not res["family_sums_match_overall"] or res["unmapped_families"] else 0)
