"""
Blended-EB ablation: what does a Gaia neighbour (Q3C) check actually buy?

Design rules that avoid the tautologies in a naive version:
  * the vetter only sees the CATALOG: hosts can be missing (close pairs, crowded fields)
  * neighbour flux is PSF-weighted by separation, not counted at full strength
  * every setting reports BOTH sides of the trade: blended-EB rejection AND real-planet loss
  * margin is swept, producing a tradeoff curve instead of one flattering operating point
  * crowding regimes (high/mid/low galactic latitude) are reported separately
Assumptions (declared, adjustable): neighbour counts ~ dN/dm ∝ 10^(0.35 m), PSF sigma 21",
catalog completeness 0.98 (0.60 inside 2"), EB host chosen uniformly among neighbours,
intrinsic eclipse depth U(0.1, 0.8), only events with observed depth 300-3000 ppm are kept.
"""
from __future__ import annotations
import numpy as np
from .core import Workflow, Claim, rate

DENSITY = {"high_latitude": 4.0, "mid_latitude": 25.0, "low_latitude": 150.0}   # stars / arcmin^2, T<19
MARGINS = [0.5, 1.0, 2.0, 4.0, 8.0]
D_MAX = 0.8          # deepest eclipse the vetter allows a neighbour to have


def sample_field(rng, dens, radius=42.0, host_missing_ok=True):
    mT = rng.uniform(8.0, 13.0)
    n = rng.poisson(dens * np.pi * (radius / 60.0) ** 2)
    sep = radius * np.sqrt(rng.random(n))
    a, lo, hi = 0.35, 8.0, 19.0
    m = np.log10(10 ** (a * lo) + rng.random(n) * (10 ** (a * hi) - 10 ** (a * lo))) / a
    fr = np.exp(-0.5 * (sep / 21.0) ** 2) * 10 ** (-0.4 * (m - mT))      # PSF-weighted flux ratio
    in_cat = rng.random(n) < np.where(sep < 2.0, 0.60, 0.98)
    return sep, fr, in_cat


def vetter_flags(fr, in_cat, depth_obs, margin):
    """True = catalog says some neighbour could explain the observed dip (reject / caution)."""
    if not in_cat.any():
        return False
    max_dip = D_MAX * fr[in_cat] / (1.0 + fr.sum())
    return bool((max_dip >= margin * depth_obs).any())


def one_beb(rng, dens):
    for _ in range(200):
        sep, fr, in_cat = sample_field(rng, dens)
        if len(fr) == 0:
            continue
        h = rng.integers(len(fr))
        depth = rng.uniform(0.1, 0.8) * fr[h] / (1.0 + fr.sum())
        if 300e-6 <= depth <= 3000e-6:
            return fr, in_cat, depth
    return None


def one_planet(rng, dens):
    sep, fr, in_cat = sample_field(rng, dens)
    return fr, in_cat, float(np.exp(rng.uniform(np.log(300e-6), np.log(3000e-6))))


class BlendedEBAblation(Workflow):
    name = "blended_eb_neighbour_vetter"
    ground_truth = "injected blended EBs vs injected planets (synthetic); drop-in: TOI dispositions (confirmed vs NEB/BEB FP) from ExoFOP"
    baseline = "light-curve-only vetting (no catalog neighbours): rejects 0% of depth-matched BEBs and loses 0% of planets"
    claim_ceiling = Claim.CANDIDATE
    evidence_level = "synthetic"

    def evaluate(self, seed=7, quick=False):
        rng = np.random.default_rng(seed)
        n = 600 if quick else 4000
        out = {}
        for reg, dens in DENSITY.items():
            bebs = [b for b in (one_beb(rng, dens) for _ in range(n)) if b is not None]
            pls = [one_planet(rng, dens) for _ in range(n)]
            row = {}
            for mg in MARGINS:
                rej = sum(vetter_flags(fr, c, d, mg) for fr, c, d in bebs)
                lost = sum(vetter_flags(fr, c, d, mg) for fr, c, d in pls)
                row[f"margin={mg}"] = dict(beb_rejected=rate(rej, len(bebs)), planets_lost=rate(lost, len(pls)))
            out[reg] = row
        # a single summary operating point for the paper table
        pick = {reg: out[reg]["margin=2.0"] for reg in out}
        return dict(workflow=self.name, describe=self.describe(), units=f"{n} injected events per regime/class",
                    tradeoff_by_density=out, operating_point_margin_2=pick,
                    note=("Catalog-only neighbour checks reject many depth-matched BEBs but also discard real planets, "
                          "especially in crowded fields. Use as a CAUTION flag + trigger for centroid/difference-imaging, "
                          "not as a veto. Planet loss must be reported with every FP-rejection number."))
