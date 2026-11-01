"""
Shared framework for TaarYa discovery workflows.

Every workflow implements the same contract so that claims are comparable:
  * independent ground truth (labels never derived from the features the scorer uses)
  * at least one baseline an astronomer could run in TOPCAT / PyVO
  * unit of replication = field / cluster / star-sample, never single rows
  * confidence intervals on everything; paired differences against the baseline
  * a claim ceiling: the strongest label the workflow may emit
"""
from __future__ import annotations
import abc, dataclasses as dc, enum, hashlib, json, platform, sys, time
import numpy as np


# ------------------------------------------------------------------ claim ladder
class Claim(enum.IntEnum):
    NOISE = 0
    SIGNAL = 1              # statistical excess above a calibrated threshold
    CANDIDATE = 2           # passes the vetting battery
    VETTED_CANDIDATE = 3    # survives a committed, blind, held-out prediction
    # Nothing above this is automatable. "Confirmed"/"discovered" need human follow-up.


# ------------------------------------------------------------------ statistics
MIN_UNITS = 8   # fewer independent units than this -> report per-unit values only, no intervals or 'separated' claims
def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(int(k), int(n))
    return dict(k=int(k), n=int(n), rate=round(k / n, 4) if n else None, ci95=[round(lo, 4), round(hi, 4)])


def bootstrap_ci(x, B: int = 2000, seed: int = 0, min_n: int = 0) -> dict:
    """Percentile bootstrap of the mean over independent units (fields, clusters, papers)."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) == 0:
        return dict(mean=None, ci95=[None, None], n=0)
    if len(x) < min_n:      # a bootstrap of a handful of units just returns their min/max: not an interval
        return dict(mean=round(float(x.mean()), 4), ci95=[None, None], n=int(len(x)), note=f"descriptive only: n={len(x)} < {min_n} units")
    rng = np.random.default_rng(seed)
    m = x[rng.integers(0, len(x), (B, len(x)))].mean(axis=1)
    return dict(mean=round(float(x.mean()), 4), ci95=[round(float(np.quantile(m, .025)), 4),
                                                       round(float(np.quantile(m, .975)), 4)], n=int(len(x)))


def paired_diff(a, b, B: int = 2000, seed: int = 0, min_n: int = 0) -> dict:
    """Bootstrap CI for mean(a-b) over matched units. `separated` = CI excludes zero."""
    d = np.asarray(a, float) - np.asarray(b, float)
    r = bootstrap_ci(d, B, seed, min_n)
    lo, hi = r["ci95"]
    if lo is None and r["n"] > 0:
        r["separated"], r["direction"] = None, None
        return r
    r["separated"] = bool(lo is not None and (lo > 0 or hi < 0))
    r["direction"] = None if not r["separated"] else ("a>b" if lo > 0 else "a<b")
    return r


# ------------------------------------------------------------------ ranking metrics
def rank_by_score(score, rng) -> np.ndarray:
    """Indices best-first. Ties are broken randomly (seeded): discrete heuristic scores
    have many ties and a stable sort would silently favour catalogue order."""
    score = np.asarray(score, float)
    return np.lexsort((rng.random(len(score)), -score))


def precision_at_k(rel_sorted, k):
    return float(np.mean(rel_sorted[:k])) if len(rel_sorted) else float("nan")


def average_precision(rel_sorted):
    rel = np.asarray(rel_sorted, float)
    if rel.sum() == 0:
        return float("nan")
    return float(np.sum(np.cumsum(rel) / np.arange(1, len(rel) + 1) * rel) / rel.sum())


def ndcg_at_k(rel_sorted, k):
    rel = np.asarray(rel_sorted, float)
    disc = 1 / np.log2(np.arange(2, k + 2))
    dcg = float(np.sum(rel[:k] * disc[:len(rel[:k])]))
    ideal = np.sort(rel)[::-1][:k]
    idcg = float(np.sum(ideal * disc[:len(ideal)]))
    return dcg / idcg if idcg > 0 else float("nan")


# ------------------------------------------------------------------ leak guard
class DataVault:
    """Holds labelled/held-out data; reading a protected key before commit() raises."""
    def __init__(self, items: dict, protected: set):
        self._items, self._protected, self.commit_hash = items, set(protected), None

    def get(self, key):
        if key in self._protected and self.commit_hash is None:
            raise PermissionError(f"'{key}' is protected until a prediction is committed")
        return self._items[key]

    def commit(self, record: dict) -> str:
        self.commit_hash = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
        return self.commit_hash


# ------------------------------------------------------------------ workflow contract
@dc.dataclass
class Finding:
    workflow: str
    target: str
    claim: Claim
    score: float = 0.0
    evidence: list = dc.field(default_factory=list)   # [{"name","passed","value"}]


class Workflow(abc.ABC):
    name: str = "base"
    ground_truth: str = ""        # where independent labels come from
    baseline: str = ""            # what an astronomer would do without TaarYa
    claim_ceiling: Claim = Claim.CANDIDATE
    evidence_level: str = "synthetic"   # synthetic | real-labels-required | real

    @abc.abstractmethod
    def evaluate(self, seed: int = 7, quick: bool = False) -> dict: ...

    def describe(self) -> dict:
        return dict(name=self.name, ground_truth=self.ground_truth, baseline=self.baseline,
                    claim_ceiling=self.claim_ceiling.name, evidence_level=self.evidence_level)


def stamp(result: dict, seed: int, files=()) -> dict:
    h = hashlib.sha256()
    for f in files:
        try:
            h.update(open(f, "rb").read())
        except OSError:
            pass
    result["provenance"] = dict(seed=seed, code_hash=h.hexdigest()[:16], python=sys.version.split()[0],
                                numpy=np.__version__, platform=platform.platform(),
                                utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return result


def claim_from_evidence(detection_ok: bool = True, vetters: dict = None, blind_p=None, blind_testable=None, alpha: float = 0.01,
                        *, sde: float = None, threshold: float = None, vetting_passed: bool = None,
                        vetting_failures: list = None, blind_prediction_p: float = None):
    """Claim level is a FUNCTION OF EVIDENCE, never of the user's wording.
    vetters: {name: True/False/None}; None = not run (counts as not passed).
    A held-out prediction counts only if it was testable (enough independent windows)."""
    if sde is not None and threshold is not None:
        if sde < threshold:
            return Claim.NOISE, [f"sde={sde} below detection threshold {threshold}"]
        if vetting_passed is False:
            return Claim.SIGNAL, vetting_failures or ["vetting failed"]
        if blind_prediction_p is not None:
            if blind_prediction_p < alpha:
                return Claim.VETTED_CANDIDATE, [f"holdout prediction confirmed (p={blind_prediction_p} < {alpha})"]
            return Claim.CANDIDATE, [f"holdout prediction not confirmed (p={blind_prediction_p} >= {alpha})"]
        return Claim.CANDIDATE, ["vetting passed; no holdout prediction tested"]

    if not detection_ok:
        return Claim.NOISE
    if not vetters or any(v is not True for v in vetters.values()):
        return Claim.SIGNAL
    if blind_testable and blind_p is not None and blind_p < alpha:
        return Claim.VETTED_CANDIDATE
    return Claim.CANDIDATE
