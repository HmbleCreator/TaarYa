"""
TaarYa discovery workflows framework.

Provides workflow-agnostic discovery primitives:
  - Claim ladder: NOISE < SIGNAL < CANDIDATE < VETTED_CANDIDATE
  - Leak guard: Cryptographic commitment before accessing held-out test data
  - Independent ground truth evaluation against TOPCAT / PyVO baselines
  - Paired bootstrap confidence intervals over independent units of replication
"""

from .core import (
    Claim,
    DataVault,
    Finding,
    Workflow,
    bootstrap_ci,
    claim_from_evidence,
    paired_diff,
    rate,
    wilson,
)

__all__ = [
    "Claim",
    "DataVault",
    "Finding",
    "Workflow",
    "bootstrap_ci",
    "claim_from_evidence",
    "paired_diff",
    "rate",
    "wilson",
]

