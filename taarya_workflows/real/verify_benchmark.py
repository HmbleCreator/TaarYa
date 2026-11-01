"""
Is the benchmark summary a pure function of its per-query records, and have those records changed since a frozen tag?

  python -m taarya_workflows.real.verify_benchmark eval/benchmark_results.json --baseline eval-v2:eval/benchmark_results.json

Prints the per-family table recomputed FROM THE PER-QUERY RECORDS (never from any stored summary), checks that family rows sum to the overall
row, and lists every record whose outcome differs from the baseline version in git. Exit 1 if per-query outcomes changed.
Schema is discovered (tolerant key names); if yours differs, extend the *_KEYS tuples.
"""
from __future__ import annotations
import json, subprocess, sys
from collections import defaultdict

FAM_KEYS = ("family", "category", "type", "task_family", "group")
STAT_KEYS = ("status", "result", "outcome", "verdict", "pass_fail")
LAT_KEYS = ("latency_ms", "elapsed_ms", "latency", "duration_ms", "time_ms")
ID_KEYS = ("id", "query_id", "qid", "query", "prompt", "name")
PASS, PART = {"pass", "passed", "success", "ok", "true"}, {"partial", "partially"}


def _load_query_map():
    for p in ["eval/benchmark_queries.json", "../eval/benchmark_queries.json"]:
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
                return {q["id"]: q["family"] for q in d.get("queries", []) if "id" in q and "family" in q}
        except Exception:
            pass
    return {}


_Q_MAP = _load_query_map()


def _first(d, keys):
    for k in keys:
        if k in d: return d[k]
    return None


def _get_family(d):
    f = _first(d, ("family", "task_family", "group"))
    if f is not None:
        return f
    qid = _first(d, ID_KEYS)
    if qid and qid in _Q_MAP:
        return _Q_MAP[qid]
    return _first(d, FAM_KEYS)


def find_records(obj):
    """Largest list of dicts that carry both a family-like and a status-like key."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and sum((_get_family(x) is not None or _first(x, FAM_KEYS) is not None) and _first(x, STAT_KEYS) is not None for x in o) >= 0.8 * len(o):
                if len(o) > len(best): best = o
            for x in o: walk(x)
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
    walk(obj); return best


def norm_status(v) -> str:
    s = str(v).strip().lower()
    return "pass" if s in PASS else "partial" if s in PART else "fail"


def recompute(records) -> dict:
    fam = defaultdict(lambda: dict(total=0, passed=0, partial=0, failed=0, lat=[]))
    for r in records:
        f = fam[str(_get_family(r))]; st = norm_status(_first(r, STAT_KEYS)); f["total"] += 1
        f["passed" if st == "pass" else "partial" if st == "partial" else "failed"] += 1
        l = _first(r, LAT_KEYS)
        if isinstance(l, (int, float)): f["lat"].append(float(l))
    out = {}
    for k, v in fam.items():
        out[k] = dict(total=v["total"], passed=v["passed"], partial=v["partial"], failed=v["failed"], pass_rate=round(100 * v["passed"] / v["total"], 1),
                      mean_latency=round(sum(v["lat"]) / len(v["lat"]), 1) if v["lat"] else None)
    tot = {k: sum(v[k] for v in out.values()) for k in ("total", "passed", "partial", "failed")}
    all_lat = [l for v in fam.values() for l in v["lat"]]
    mean_all_lat = round(sum(all_lat) / len(all_lat), 1) if all_lat else None
    out["__overall__"] = dict(tot, pass_rate=round(100 * tot["passed"] / tot["total"], 1) if tot["total"] else None,
                              mean_latency=mean_all_lat)
    return out


def diff_records(new, old) -> list:
    key = lambda r, i: str(_first(r, ID_KEYS) if _first(r, ID_KEYS) is not None else i)
    a = {key(r, i): r for i, r in enumerate(old)}; b = {key(r, i): r for i, r in enumerate(new)}; ch = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b: ch.append(dict(id=k, change="added" if k in b else "removed")); continue
        o, n = norm_status(_first(a[k], STAT_KEYS)), norm_status(_first(b[k], STAT_KEYS)); fo, fn = _get_family(a[k]), _get_family(b[k])
        if o != n or fo != fn: ch.append(dict(id=k, change="outcome/family", old=f"{fo}:{o}", new=f"{fn}:{n}"))
    return ch


def _git_show(spec):
    return json.loads(subprocess.check_output(["git", "show", spec], text=True, stderr=subprocess.DEVNULL))


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("results"); ap.add_argument("--baseline", help="git spec, e.g. eval-v2:eval/benchmark_results.json"); a = ap.parse_args()
    recs = find_records(json.load(open(a.results, encoding="utf-8-sig")))
    if not recs: sys.exit("no per-query records found: extend FAM_KEYS/STAT_KEYS for your schema")
    tab = recompute(recs)
    print(f"{'family':12s} total passed partial failed pass% lat_ms")
    for k, v in tab.items(): print(f"{k:12s} {v['total']:5d} {v['passed']:6d} {v.get('partial', 0):7d} {v.get('failed', 0):6d} {v['pass_rate']:5} {v.get('mean_latency')}")
    bad = 0
    if a.baseline:
        ch = diff_records(recs, find_records(_git_show(a.baseline))); bad = len(ch)
        print(f"\n{len(ch)} per-query record(s) differ from {a.baseline}"); [print("  ", c) for c in ch]
    sys.exit(1 if bad else 0)

