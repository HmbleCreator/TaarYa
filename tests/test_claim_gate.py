"""
Unit tests for evidence-driven claim ladder gating.
Verifies that claims can never be promoted beyond what the empirical data supports.
"""
import pytest
from taarya_workflows.core import Claim, claim_from_evidence


def test_noise_when_below_threshold():
    claim, reasons = claim_from_evidence(sde=4.2, threshold=4.8, vetting_passed=True)
    assert claim == Claim.NOISE
    assert any("below detection threshold" in r.lower() for r in reasons)


def test_signal_when_vetting_fails():
    claim, reasons = claim_from_evidence(
        sde=6.5,
        threshold=4.8,
        vetting_passed=False,
        vetting_failures=["odd_even_z=4.1"]
    )
    assert claim == Claim.SIGNAL
    assert "odd_even_z=4.1" in reasons


def test_candidate_when_vetting_passes_without_holdout():
    claim, reasons = claim_from_evidence(
        sde=7.0,
        threshold=4.8,
        vetting_passed=True,
        blind_prediction_p=None
    )
    assert claim == Claim.CANDIDATE


def test_candidate_when_holdout_fails_p_value():
    claim, reasons = claim_from_evidence(
        sde=8.0,
        threshold=4.8,
        vetting_passed=True,
        blind_prediction_p=0.08,
        alpha=0.01
    )
    assert claim == Claim.CANDIDATE
    assert any("not confirmed" in r.lower() for r in reasons)


def test_vetted_candidate_when_holdout_prediction_confirmed():
    claim, reasons = claim_from_evidence(
        sde=9.2,
        threshold=4.8,
        vetting_passed=True,
        blind_prediction_p=0.002,
        alpha=0.01
    )
    assert claim == Claim.VETTED_CANDIDATE
    assert any("confirmed" in r.lower() for r in reasons)

