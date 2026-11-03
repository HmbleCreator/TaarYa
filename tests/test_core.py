import numpy as np, pytest
from taarya_workflows.core import (Claim, DataVault, claim_from_evidence, wilson, rate, average_precision,
                                   ndcg_at_k, paired_diff, rank_by_score)

def test_wilson_bounds():
    lo, hi = wilson(0, 60); assert lo == 0 and 0.05 < hi < 0.07
    lo, hi = wilson(6, 6); assert hi == pytest.approx(1.0) and 0.5 < lo < 0.7        # 6/6 is NOT "100%": lower bound ~0.61

def test_claim_gate_is_evidence_driven():
    ok = dict(odd_even=True, secondary=True, aperture=True)
    assert claim_from_evidence(False, ok) == Claim.NOISE
    assert claim_from_evidence(True, dict(ok, aperture=None)) == Claim.SIGNAL      # unrun vetter blocks promotion
    assert claim_from_evidence(True, ok) == Claim.CANDIDATE
    assert claim_from_evidence(True, ok, blind_p=0.001, blind_testable=True) == Claim.VETTED_CANDIDATE
    assert claim_from_evidence(True, ok, blind_p=0.001, blind_testable=False) == Claim.CANDIDATE   # untestable != passed
    assert claim_from_evidence(True, ok, blind_p=0.2, blind_testable=True) == Claim.CANDIDATE

def test_vault_blocks_until_commit():
    v = DataVault({"s2": 1}, {"s2"})
    with pytest.raises(PermissionError): v.get("s2")
    v.commit({"P": 3.18}); assert v.get("s2") == 1

def test_metrics_and_ties():
    assert average_precision([1, 1, 0, 0]) == 1.0
    assert 0 < ndcg_at_k([0, 1, 0, 1], 4) < 1
    rng = np.random.default_rng(0)
    first = {int(rank_by_score(np.zeros(10), np.random.default_rng(i))[0]) for i in range(40)}
    assert len(first) > 3          # ties are not resolved by catalogue order

def test_paired_diff_detects_shift():
    r = np.random.default_rng(0); a = r.normal(0.1, 0.02, 40); b = r.normal(0.0, 0.02, 40)
    assert paired_diff(a, b)["separated"] and not paired_diff(a, a + r.normal(0, 1e-6, 40) * 0)["separated"]
