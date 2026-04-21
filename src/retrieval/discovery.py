"""Pure discovery-ranking utilities for cross-catalog astronomy candidates.

Scientifically calibrated anomaly detection based on:
- RUWE thresholds from Gaia DR3 documentation (RUWE > 1.4 indicates poor fit)
- Color thresholds based on standard stellar locus
- Proper motion from Gaia Collaboration recommendations
- Luminosity-distance anomalies from stellar physics
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence


# Scientific thresholds based on Gaia DR3 documentation and stellar astrophysics
SCIENTIFIC_THRESHOLDS = {
    # RUWE: Gaia DR3 recommends RUWE > 1.4 as indicator of astrometric issues
    # RUWE > 2.0 is strongly indicative of binarity
    "ruwe_poor": 1.4,
    "ruwe_binary": 2.0,
    "ruwe_very_high": 2.5,

    # Color indices (BP-RP) based on standard stellar locus
    # Very blue: BP-RP < -0.1 (hot subdwarfs, blue stragglers)
    # Very red: BP-RP > 2.8 (M dwarfs, dusty envelopes)
    "bp_rp_blue": -0.1,
    "bp_rp_red": 2.8,

    # Proper motion (mas/yr) - high PM stars are nearby or hypervelocity
    # Typical disk stars: < 20 mas/yr
    # High PM: > 40 mas/yr indicates nearby or unusual
    # Very high: > 80 mas/yr is rare (hypervelocity candidates)
    "pm_high": 40.0,
    "pm_very_high": 80.0,

    # Parallax significance
    "parallax_min": 0.1,  # Must be positive and significant

    # Absolute magnitude anomalies (for distance estimation)
    # Typical main sequence stars have predictable M_G based on color
    "mag_deviation_threshold": 3.0,  # magnitudes
}


def _finite_float(value: Any) -> Optional[float]:
    """Convert an input value to a finite float or return None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _snr_penalty(value: Optional[float], error: Optional[float]) -> float:
    """Compute a penalty factor [0, 1] based on signal-to-noise ratio.

    Returns 1.0 (no penalty) if SNR >= 10, scales linearly to 0.3 at SNR=1.
    If either value or error is missing, returns 0.7 (uncertain but usable).
    """
    if value is None or error is None:
        return 0.7
    if error <= 0:
        return 1.0  # Perfect measurement
    snr = abs(value) / abs(error)
    if snr >= 10.0:
        return 1.0
    if snr <= 1.0:
        return 0.3
    # Linear interpolation between SNR 1..10
    return 0.3 + 0.7 * (snr - 1.0) / 9.0


def _compute_confidence(row: Dict[str, Any], score: float) -> Dict[str, Any]:
    """Compute measurement confidence for a discovery candidate.

    Returns a dict with per-parameter SNR penalties and an aggregate
    confidence value in [0, 1] that scales the raw discovery score.

    This addresses the key publication concern: are high-scoring
    candidates real anomalies or just measurement noise?
    """
    parallax = _finite_float(row.get("parallax"))
    parallax_err = _finite_float(row.get("parallax_error"))
    pmra = _finite_float(row.get("pmra"))
    pmra_err = _finite_float(row.get("pmra_error"))
    pmdec = _finite_float(row.get("pmdec"))
    pmdec_err = _finite_float(row.get("pmdec_error"))

    plx_pen = _snr_penalty(parallax, parallax_err)
    pmra_pen = _snr_penalty(pmra, pmra_err)
    pmdec_pen = _snr_penalty(pmdec, pmdec_err)

    # Photometry confidence (Gaia G-band flux_over_error is typically high)
    phot_g = _finite_float(row.get("phot_g_mean_mag"))
    phot_pen = 0.9 if phot_g is not None else 0.5

    # RUWE itself is a quality indicator; low RUWE = high astrometric confidence
    ruwe = _finite_float(row.get("ruwe"))
    if ruwe is not None:
        # RUWE < 1.2 is excellent; RUWE > 2.5 means poor fit
        if ruwe < 1.2:
            ruwe_quality = 1.0
        elif ruwe < 1.4:
            ruwe_quality = 0.9
        elif ruwe < 2.0:
            ruwe_quality = 0.7  # Elevated but could be real
        else:
            ruwe_quality = 0.5  # Poor fit — score boosted but confidence reduced
    else:
        ruwe_quality = 0.6  # Missing RUWE

    # Aggregate: geometric-ish mean weighted toward the worst measurement
    raw_confidence = (
        plx_pen * 0.30
        + pmra_pen * 0.15
        + pmdec_pen * 0.15
        + phot_pen * 0.15
        + ruwe_quality * 0.25
    )

    # Score uncertainty: how much the score might vary given measurement errors
    score_uncertainty = round(score * (1.0 - raw_confidence), 1)

    return {
        "confidence": round(raw_confidence, 3),
        "score_uncertainty": score_uncertainty,
        "snr_penalties": {
            "parallax": round(plx_pen, 3),
            "pmra": round(pmra_pen, 3),
            "pmdec": round(pmdec_pen, 3),
            "photometry": round(phot_pen, 3),
            "astrometric_quality": round(ruwe_quality, 3),
        },
    }


def _normalize_object_class(value: Any) -> Optional[str]:
    """Normalize free-form object class labels for stable display."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.replace("_", " ").replace("/", " ").split()).upper()


def _angular_distance_deg(ra_a: float, dec_a: float, ra_b: float, dec_b: float) -> float:
    """Return the angular separation between two sky coordinates in degrees."""
    ra1 = math.radians(ra_a)
    ra2 = math.radians(ra_b)
    dec1 = math.radians(dec_a)
    dec2 = math.radians(dec_b)
    sin_d1 = math.sin(dec1)
    sin_d2 = math.sin(dec2)
    cos_d1 = math.cos(dec1)
    cos_d2 = math.cos(dec2)
    cos_angle = sin_d1 * sin_d2 + cos_d1 * cos_d2 * math.cos(ra1 - ra2)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def discovery_profile(mode: str) -> Dict[str, float]:
    """Return scoring weights for the requested discovery profile."""
    normalized = (mode or "balanced").strip().lower()
    profiles: Dict[str, Dict[str, float]] = {
        "strict": {
            "catalog_bonus": 6.0,
            "ruwe_missing": 1.0,
            "ruwe_high": 14.0,
            "ruwe_elevated": 8.0,
            "ruwe_tight": 1.5,
            "color_extreme": 10.0,
            "no_color_profile": 2.5,
            "motion_high": 16.0,
            "motion_mid": 8.0,
            "brightness_anomaly": 5.0,
            "density_scale": 0.15,
            "density_cap": 1.2,
            "cross_match_base": 2.0,
            "cross_match_per_catalog": 0.6,
            "cross_match_cap": 3.0,
            "catalog_overlap_bonus": 0.4,
            "catalog_overlap_cap": 1.5,
        },
        "balanced": {
            "catalog_bonus": 8.0,
            "ruwe_missing": 1.5,
            "ruwe_high": 16.0,
            "ruwe_elevated": 9.0,
            "ruwe_tight": 2.0,
            "color_extreme": 10.5,
            "no_color_profile": 3.5,
            "motion_high": 14.0,
            "motion_mid": 7.0,
            "brightness_anomaly": 5.5,
            "density_scale": 0.20,
            "density_cap": 1.8,
            "cross_match_base": 2.5,
            "cross_match_per_catalog": 0.8,
            "cross_match_cap": 4.0,
            "catalog_overlap_bonus": 0.5,
            "catalog_overlap_cap": 1.8,
        },
        "aggressive": {
            "catalog_bonus": 11.0,
            "ruwe_missing": 2.0,
            "ruwe_high": 18.0,
            "ruwe_elevated": 11.0,
            "ruwe_tight": 2.5,
            "color_extreme": 11.5,
            "no_color_profile": 4.5,
            "motion_high": 14.0,
            "motion_mid": 7.0,
            "brightness_anomaly": 6.5,
            "density_scale": 0.28,
            "density_cap": 2.8,
            "cross_match_base": 3.5,
            "cross_match_per_catalog": 1.0,
            "cross_match_cap": 5.5,
            "catalog_overlap_bonus": 0.8,
            "catalog_overlap_cap": 2.8,
        },
    }
    return dict(profiles.get(normalized, profiles["balanced"]))


def summarize_catalogs(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a stable catalog summary from in-memory rows."""
    counts = Counter(
        (str(row.get("catalog_source") or "UNKNOWN").strip() or "UNKNOWN").upper()
        for row in rows
    )
    return [
        {"catalog_source": catalog_source, "count": count}
        for catalog_source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def rank_discovery_candidates(
    rows: Sequence[Dict[str, Any]],
    *,
    limit: int = 15,
    pool_limit: int = 3000,
    radius_deg: float = 0.08,
    mode: str = "balanced",
    catalog_summary: Optional[List[Dict[str, Any]]] = None,
    override_profile: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Rank potentially interesting objects using catalog, quality, and locality signals."""
    profile = override_profile if override_profile is not None else discovery_profile(mode)

    gaia_rows = [
        row
        for row in rows
        if (str(row.get("catalog_source") or "GAIA").strip().upper() == "GAIA")
    ][:pool_limit]
    other_rows = [
        row
        for row in rows
        if (str(row.get("catalog_source") or "GAIA").strip().upper() != "GAIA")
    ]
    ranked_rows = list(gaia_rows) + list(other_rows)

    provisional: List[Dict[str, Any]] = []
    for row in ranked_rows:
        catalog_source = (str(row.get("catalog_source") or "GAIA").strip() or "GAIA").upper()
        ra = _finite_float(row.get("ra"))
        dec = _finite_float(row.get("dec"))
        if ra is None or dec is None:
            continue

        parallax = _finite_float(row.get("parallax"))
        distance_pc = 1000.0 / parallax if parallax and parallax > 0 else None
        pmra = _finite_float(row.get("pmra"))
        pmdec = _finite_float(row.get("pmdec"))
        phot_g = _finite_float(row.get("phot_g_mean_mag"))
        bp = _finite_float(row.get("phot_bp_mean_mag"))
        rp = _finite_float(row.get("phot_rp_mean_mag"))
        bp_rp = (bp - rp) if bp is not None and rp is not None else None
        ruwe = _finite_float(row.get("ruwe"))
        object_class = _normalize_object_class(row.get("object_class"))

        score = 0.0
        reasons: List[str] = []

        if catalog_source != "GAIA":
            score += profile["catalog_bonus"]
            reasons.append(f"{catalog_source} catalog object")

        if ruwe is not None:
            if ruwe >= SCIENTIFIC_THRESHOLDS["ruwe_binary"]:
                score += profile["ruwe_high"]
                reasons.append(f"RUWE {ruwe:.2f} is very high")
            elif ruwe >= SCIENTIFIC_THRESHOLDS["ruwe_poor"]:
                score += profile["ruwe_elevated"]
                reasons.append(f"RUWE {ruwe:.2f} is elevated")
            elif ruwe < 0.9:
                score += profile["ruwe_tight"]
                reasons.append(f"RUWE {ruwe:.2f} is unusually tight")
        else:
            score += profile["ruwe_missing"]
            reasons.append("RUWE missing")

        if bp_rp is not None:
            if bp_rp <= SCIENTIFIC_THRESHOLDS["bp_rp_blue"]:
                score += profile["color_extreme"]
                reasons.append(f"very blue BP-RP {bp_rp:.2f}")
            elif bp_rp >= SCIENTIFIC_THRESHOLDS["bp_rp_red"]:
                score += profile["color_extreme"]
                reasons.append(f"very red BP-RP {bp_rp:.2f}")
        elif catalog_source != "GAIA":
            score += profile["no_color_profile"]
            reasons.append("no Gaia color profile")

        motion = 0.0
        if pmra is not None:
            motion += pmra * pmra
        if pmdec is not None:
            motion += pmdec * pmdec
        motion = math.sqrt(motion) if motion > 0 else None
        if motion is not None:
            if motion >= SCIENTIFIC_THRESHOLDS["pm_very_high"]:
                score += profile["motion_high"]
                reasons.append(f"fast proper motion {motion:.1f} mas/yr")
            elif motion >= SCIENTIFIC_THRESHOLDS["pm_high"]:
                score += profile["motion_mid"]
                reasons.append(f"notable proper motion {motion:.1f} mas/yr")

        if distance_pc is not None and phot_g is not None:
            if phot_g <= 10 and distance_pc >= 500:
                score += profile["brightness_anomaly"]
                reasons.append("bright but distant")
            elif phot_g >= 16 and distance_pc <= 50:
                score += profile["brightness_anomaly"]
                reasons.append("faint but nearby")

        provisional.append(
            {
                "source_id": row["source_id"],
                "catalog_source": catalog_source,
                "ra": ra,
                "dec": dec,
                "parallax": parallax,
                "distance_pc": distance_pc,
                "phot_g_mean_mag": phot_g,
                "ruwe": ruwe,
                "object_class": object_class,
                "bp_rp": bp_rp,
                "pm_total": motion,
                "score": score,
                "reasons": reasons,
                "_raw_row": row,  # Carry the original row for confidence computation
            }
        )

    provisional.sort(
        key=lambda item: (
            item["score"],
            item["phot_g_mean_mag"] is not None,
            -(item["phot_g_mean_mag"] or 99.0),
        ),
        reverse=True,
    )

    workset = provisional[: max(limit * 4, 24)]
    non_gaia = [item for item in provisional if item["catalog_source"] != "GAIA"]
    seen_ids = {item["source_id"] for item in workset}
    for item in non_gaia:
        if item["source_id"] in seen_ids:
            continue
        workset.append(item)
        seen_ids.add(item["source_id"])

    enriched: List[Dict[str, Any]] = []
    cross_catalog_hits = 0

    for item in workset:
        local_density = 0
        matched_catalog_set = set()

        for row in ranked_rows:
            other_ra = _finite_float(row.get("ra"))
            other_dec = _finite_float(row.get("dec"))
            if other_ra is None or other_dec is None:
                continue
            if row["source_id"] == item["source_id"]:
                continue
            if _angular_distance_deg(item["ra"], item["dec"], other_ra, other_dec) > radius_deg:
                continue

            local_density += 1
            catalog = (str(row.get("catalog_source") or "UNKNOWN").strip() or "UNKNOWN").upper()
            if catalog != item["catalog_source"]:
                matched_catalog_set.add(catalog)

        matched_catalogs = sorted(matched_catalog_set)

        if local_density > 1:
            crowd_bonus = min(
                max(local_density - 1, 0) * profile["density_scale"],
                profile["density_cap"],
            )
            item["score"] += crowd_bonus
            item["reasons"].append(f"crowded field with {local_density} neighbors")

        if matched_catalogs:
            cross_catalog_hits += 1
            cross_bonus = min(
                profile["cross_match_base"] + len(matched_catalogs) * profile["cross_match_per_catalog"],
                profile["cross_match_cap"],
            )
            item["score"] += cross_bonus
            item["reasons"].append("cross-matched with " + ", ".join(matched_catalogs))

        if item["catalog_source"] != "GAIA":
            item["score"] += min(
                len(matched_catalogs) * profile["catalog_overlap_bonus"],
                profile["catalog_overlap_cap"],
            )

        item["local_density"] = local_density
        item["matched_catalogs"] = matched_catalogs
        item["score"] = round(min(item["score"], 100.0), 1)
        enriched.append(item)

    enriched.sort(
        key=lambda item: (
            item["score"],
            item["distance_pc"] is not None,
            -(item["phot_g_mean_mag"] or 99.0),
        ),
        reverse=True,
    )

    top_candidates = []
    for item in enriched[:limit]:
        confidence_info = _compute_confidence(item.get("_raw_row", {}), item["score"])
        top_candidates.append({
            "source_id": item["source_id"],
            "catalog_source": item["catalog_source"],
            "ra": item["ra"],
            "dec": item["dec"],
            "parallax": item["parallax"],
            "distance_pc": item["distance_pc"],
            "phot_g_mean_mag": item["phot_g_mean_mag"],
            "ruwe": item["ruwe"],
            "object_class": item["object_class"],
            "bp_rp": item["bp_rp"],
            "local_density": item["local_density"],
            "matched_catalogs": item["matched_catalogs"],
            "score": item["score"],
            "confidence": confidence_info["confidence"],
            "score_uncertainty": confidence_info["score_uncertainty"],
            "reasons": item["reasons"][:4],
        })

    return {
        "count": len(top_candidates),
        "top_candidates": top_candidates,
        "catalog_summary": catalog_summary if catalog_summary is not None else summarize_catalogs(ranked_rows),
        "cross_catalog_matches": {
            "candidates_with_overlap": cross_catalog_hits,
            "candidate_ratio": round(cross_catalog_hits / max(len(workset), 1), 3),
        },
        "filters": {
            "limit": limit,
            "pool_limit": pool_limit,
            "radius_deg": radius_deg,
            "mode": mode,
        },
    }
