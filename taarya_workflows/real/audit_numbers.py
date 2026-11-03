"""
Audit a LaTeX manuscript for numbers that have no source.

Every decimal, percentage and large number written literally in the text must appear in a results file (or an explicit allowlist
with a reason). Numbers that come through generated macros (\\toiDeltaAUC{}) are never literals, so they pass by construction.
This catches the failure modes seen so far: stale hand-copied counts, and claims ("<5% precision") that nothing measured.

  python -m taarya_workflows.real.audit_numbers paper.tex --results results eval/benchmark_results.json cluster_cones/manifest.json --allow allow.txt
Exit code 1 if anything is unsourced (usable as a pre-commit / CI check).
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import numpy as np

TOKEN = re.compile(r"(?<![\w\\.])((?:\d{1,3}(?:(?:\{,\}|,)\d{3})+|\d+\.\d+|\d{4,}|\d+(?=\s*\\?%))(?:\.\d+)?)(\s*\\?%)?")
INT = re.compile(r"(?<![\w\\.!=/\-])(\d{2,3})(?![\d.,%{}])")      # plain 2-3 digit integers: counts such as "42 regions"
UNIT = re.compile(r"\s*(?:pt|mm|cm|em|ex|px|bp)\b|\\(?:linewidth|textwidth|columnwidth)")
SKIP_ENV = ("lstlisting", "thebibliography", "equation", "equation*", "align", "align*", "verbatim", "tikzpicture", "axis", "semilogxaxis", "semilogyaxis", "loglogaxis")


def strip_tex(src: str) -> list:
    """-> [(line_no, text)] with comments, citations, refs, urls and skipped environments removed."""
    out, skip = [], None
    for i, line in enumerate(src.splitlines(), 1):
        m = re.match(r"\s*\\begin\{([^}]+)\}", line)
        if skip is None and m and m.group(1) in SKIP_ENV: skip = m.group(1)
        if skip is None:
            line = re.sub(r"(?<!\\)%.*$", "", line)
            line = re.sub(r"\\(?:cite[a-z]*|citep|citet|ref|eqref|label|url|doi|input|include|bibliography|bibliographystyle|newcommand|href)\*?(?:\[[^\]]*\])*\{[^}]*\}(?:\{[^}]*\})?", " ", line)
            line = re.sub(r"\b(?:Table|Figure|Section|Eq\.?|Equation|Appendix)~?\s*\d+(?:\.\d+)*", " ", line)      # structural numbers
            line = re.sub(r"\\includegraphics(?:\[[^\]]*\])?", " ", line)
            out.append((i, line))
        if skip and re.match(rf"\s*\\end\{{{re.escape(skip)}\}}", line): skip = None
    return out


def _walk(o, acc):
    if isinstance(o, bool): return
    if isinstance(o, (int, float)):
        if np.isfinite(o): acc.add(float(o))
    elif isinstance(o, dict): [_walk(v, acc) for v in o.values()]
    elif isinstance(o, (list, tuple)): [_walk(v, acc) for v in o]


def allowed_values(paths) -> np.ndarray:
    base = set()
    for p in paths:
        p = Path(p); files = list(p.glob("*.json")) if p.is_dir() else [p]
        for f in files:
            try: _walk(json.loads(f.read_text(encoding="utf-8-sig")), base)
            except Exception: pass
    vals = set(base)
    for v in base:
        vals.add(abs(v))
        if 0 <= abs(v) <= 1: vals.add(abs(v) * 100)                  # fractions quoted as percentages
    return np.array(sorted(vals))


def parse_allow(path) -> np.ndarray:
    if not path: return np.array([])
    vals = []
    for ln in Path(path).read_text().splitlines():
        ln = ln.split("#")[0].strip()
        if ln: vals.append(float(ln.replace(",", "")))
    return np.array(vals)


def audit(tex_path, result_paths, allow_path=None, ignore_years=True, ints=True) -> list:
    allowed = np.concatenate([allowed_values(result_paths), parse_allow(allow_path)]) if result_paths or allow_path else np.array([])
    flagged = []
    for ln, text in strip_tex(Path(tex_path).read_text(encoding="utf-8")):
        found = [(m, m.group(1), m.group(2)) for m in TOKEN.finditer(text)]
        spans = [m.span() for m, _, _ in found]
        found += [(m, m.group(1), None) for m in INT.finditer(text) if not any(a0 <= m.start() < b0 for a0, b0 in spans)] if ints else []
        for m, raw, pct in found:
            if UNIT.match(text[m.end():]): continue
            tok = float(raw.replace("{,}", "").replace(",", "")); dec = len(raw.split(".")[1]) if "." in raw else 0
            if ignore_years and dec == 0 and 1900 <= tok <= 2100 and not pct: continue
            if dec == 0 and tok < 10 and not pct: continue                                          # small plain integers ('three clusters')
            tol = 0.5 * 10 ** (-dec) + 1e-9
            if allowed.size and np.any(np.abs(allowed - tok) <= tol): continue
            flagged.append(dict(line=ln, token=raw + ("%" if pct else ""), context=text.strip()[max(0, m.start() - 50): m.end() + 40]))
    return flagged


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("tex"); ap.add_argument("results", nargs="*"); ap.add_argument("--allow")
    a = ap.parse_args(); bad = audit(a.tex, a.results, a.allow)
    for b in bad: print(f"line {b['line']:>4}  {b['token']:>10}   ...{b['context']}...")
    print(f"\n{len(bad)} unsourced number(s)"); sys.exit(1 if bad else 0)
