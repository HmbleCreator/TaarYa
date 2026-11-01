"""
Shared framework for TaarYa discovery workflows.

Every workflow implements the same contract so that claims are comparable:
  * independent ground truth (labels never derived from the features the scorer uses)
  * at least one baseline an astronomer could run in TOPCAT / PyVO
  * unit of replication = field / cluster / star-sample, never pooled single rows
  * confidence intervals on everything; paired differences against the baseline
  * a claim ceiling: the strongest label the workflow may emit
"""
from __future__ import annotations

import abc
import dataclasses as dc
import enum
import hashlib
import json
import platform
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np


# ------------------------------------------------------------------ claim ladder
class Claim(enum.IntEnum):
    NOISE = 0
    SIGNAL = 1              # statistical excess above a calibrated threshold
    CANDIDATE = 2           # passes the physical vetting battery
    VETTED_CANDIDATE = 3    # survives a committed, blind, held-out prediction
    # Nothing above this is automatable. "Confirmed" / "Discovered" requires human follow-up.


def claim_from_evidence(
    sde: float,
    threshold: float,
    vetting_passed: bool,
    blind_prediction_p: Optional[float] = None,
    alpha: float = 0.01,
    vetting_failures: Optional[List[str]] = None,
) -> Tuple[Claim, List[str]]:
    """
    Evidence-driven gate mapping empirical data to the claim ladder.
    
    Claims are strictly bounded by evidence, never by user prompts or queries:
      - sde < threshold -> NOISE
      - sde >= threshold, but fails vetters -> SIGNAL
      - passes vetters -> CANDIDATE
      - passes blind prediction on held-out data (p < alpha) -> VETTED_CANDIDATE
    """
    reasons = []
    if sde < threshold:
        reasons.append(f"Peak SDE {sde:.2f} below detection threshold {threshold:.2f}")
        return Claim.NOISE, reasons

    if not vetting_passed:
        reasons.append("Failed transit/physical vetting battery")
        if vetting_failures:
            reasons.extend(vetting_failures)
        return Claim.SIGNAL, reasons

    # Survives vetting -> at least CANDIDATE
    if blind_prediction_p is None:
        reasons.append("Survives physical vetting; held-out prediction not yet evaluated")
        return Claim.CANDIDATE, reasons

    if blind_prediction_p < alpha:
        reasons.append(f"Held-out prediction confirmed at p={blind_prediction_p:.4f} < {alpha}")
        return Claim.VETTED_CANDIDATE, reasons
    else:
        reasons.append(f"Held-out prediction not confirmed (p={blind_prediction_p:.4f} >= {alpha})")
        return Claim.CANDIDATE, reasons


# ------------------------------------------------------------------ statistics
def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score confidence interval for binomial proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1.0 + z * z / n
    c = (p + z * z / (2.0 * n)) / den
    h = z * np.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(int(k), int(n))
    return dict(
        k=int(k),
        n=int(n),
        rate=round(k / n, 4) if n else None,
        ci95=[round(lo, 4), round(hi, 4)]
    )


def bootstrap_ci(x: Any, B: int = 2000, seed: int = 0) -> dict:
    """Percentile bootstrap of the mean over independent units (fields, clusters, papers)."""
    arr = np.asarray(x, float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return dict(mean=None, ci95=[None, None], n=0)
    rng = np.random.default_rng(seed)
    m = arr[rng.integers(0, len(arr), (B, len(arr)))].mean(axis=1)
    return dict(
        mean=round(float(arr.mean()), 4),
        ci95=[round(float(np.quantile(m, 0.025)), 4), round(float(np.quantile(m, 0.975)), 4)],
        n=int(len(arr))
    )


def paired_diff(a: Any, b: Any, B: int = 2000, seed: int = 0) -> dict:
    """Bootstrap CI for mean(a - b) over matched units. `separated` = CI excludes zero."""
    d = np.asarray(a, float) - np.asarray(b, float)
    r = bootstrap_ci(d, B, seed)
    lo, hi = r["ci95"]
    r["separated"] = bool(lo is not None and (lo > 0 or hi < 0))
    r["direction"] = None if not r["separated"] else ("a>b" if lo > 0 else "a<b")
    return r


# ------------------------------------------------------------------ ranking metrics
def rank_by_score(score: Any, rng: np.random.Generator) -> np.ndarray:
    """Indices best-first. Ties are broken randomly with seed to avoid favoring catalog order."""
    score_arr = np.asarray(score, float)
    return np.lexsort((rng.random(len(score_arr)), -score_arr))


def precision_at_k(rel_sorted: np.ndarray, k: int) -> float:
    return float(np.mean(rel_sorted[:k])) if len(rel_sorted) else float("nan")


def average_precision(rel_sorted: np.ndarray) -> float:
    rel = np.asarray(rel_sorted, float)
    if rel.sum() == 0:
        return float("nan")
    return float(np.sum(np.cumsum(rel) / np.arange(1, len(rel) + 1) * rel) / rel.sum())


def ndcg_at_k(rel_sorted: np.ndarray, k: int) -> float:
    rel = np.asarray(rel_sorted, float)
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    dcg = float(np.sum(rel[:k] * disc[:len(rel[:k])]))
    ideal = np.sort(rel)[::-1][:k]
    idcg = float(np.sum(ideal * disc[:len(ideal)]))
    return dcg / idcg if idcg > 0 else float("nan")


# ------------------------------------------------------------------ leak guard
class DataVault:
    """Holds labelled/held-out data; reading a protected key before commit() raises PermissionError."""
    def __init__(self, items: dict, protected: Set[str]):
        self._items = items
        self._protected = set(protected)
        self.commit_hash: Optional[str] = None

    def get(self, key: str) -> Any:
        if key in self._protected and self.commit_hash is None:
            raise PermissionError(f"'{key}' is protected until an ephemeris prediction is committed")
        return self._items[key]

    def commit(self, record: dict) -> str:
        self.commit_hash = hashlib.sha256(
            json.dumps(record, sort_keys=True, default=str).encode()
        ).hexdigest()
        return self.commit_hash


# ------------------------------------------------------------------ workflow contract
@dc.dataclass
class Finding:
    workflow: str
    target: str
    claim: Claim
    score: float = 0.0
    evidence: list = dc.field(default_factory=list)   # [{"name": str, "passed": bool, "value": Any}]


class Workflow(abc.ABC):
    name: str = "base"
    ground_truth: str = ""        # where independent labels come from
    baseline: str = ""            # what an astronomer would do without TaarYa (e.g. TOPCAT, plain BLS)
    claim_ceiling: Claim = Claim.CANDIDATE
    evidence_level: str = "synthetic"   # synthetic | real-labels-required | real

    @abc.abstractmethod
    def evaluate(self, seed: int = 7, quick: bool = False) -> dict: ...

    def describe(self) -> dict:
        return dict(
            name=self.name,
            ground_truth=self.ground_truth,
            baseline=self.baseline,
            claim_ceiling=self.claim_ceiling.name,
            evidence_level=self.evidence_level
        )


def stamp(result: dict, seed: int, files: Tuple[str, ...] = ()) -> dict:
    h = hashlib.sha256()
    for f in files:
        try:
            h.update(open(f, "rb").read())
        except OSError:
            pass
    result["provenance"] = dict(
        seed=seed,
        code_hash=h.hexdigest()[:16],
        python=sys.version.split()[0],
        numpy=np.__version__,
        platform=platform.platform(),
        utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    return result

