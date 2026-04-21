"""Spatial search using PostgreSQL Q3C extension."""
import math
import logging
from collections import Counter
from typing import List, Optional, Dict, Any, Tuple

import numpy as np
from sqlalchemy import text

from src.database import postgres_conn
from src.models import Star, Region
from src.utils.scientific_orchestrator import ScientificOrchestrator

logger = logging.getLogger(__name__)


def _finite_float(value: Any) -> Optional[float]:
    """Convert database values to finite floats or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_object_class(value: Any) -> Optional[str]:
    """Normalize optional object class labels for display and scoring."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.replace("_", " ").replace("/", " ").split()).upper()


def _percentile(values: List[float], fraction: float) -> Optional[float]:
    """Return a simple linear-interpolated percentile for a sorted numeric list."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    clamped = min(max(fraction, 0.0), 1.0)
    ordered = sorted(float(v) for v in values)
    index = clamped * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _vector_to_radec(x: float, y: float, z: float) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Convert a Cartesian vector back to RA/Dec plus radial distance."""
    distance = math.sqrt(x * x + y * y + z * z)
    if distance <= 0:
        return None, None, None
    ra = (math.degrees(math.atan2(z, x)) + 360.0) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, y / distance))))
    return ra, dec, distance


def _angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Return angular separation on the celestial sphere in degrees."""
    ra1_rad = math.radians(ra1)
    dec1_rad = math.radians(dec1)
    ra2_rad = math.radians(ra2)
    dec2_rad = math.radians(dec2)
    cos_sep = (
        math.sin(dec1_rad) * math.sin(dec2_rad)
        + math.cos(dec1_rad) * math.cos(dec2_rad) * math.cos(ra1_rad - ra2_rad)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def _discovery_profile(mode: str) -> Dict[str, float]:
    """Return scoring weights for the requested discovery mode."""
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
            "motion_high": 14.0,
            "motion_mid": 7.0,
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
            "motion_high": 12.0,
            "motion_mid": 6.0,
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


class SpatialSearch:
    """Q3C-powered spatial queries on the stars catalog."""

    def _dedupe_stars(
        self,
        stars: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Collapse obviously duplicated catalog rows before returning them."""
        unique_stars: List[Dict[str, Any]] = []
        seen = set()
        duplicate_count = 0

        for star in stars:
            key = (
                round(_finite_float(star.get("ra")) or 0.0, 8),
                round(_finite_float(star.get("dec")) or 0.0, 8),
                round(_finite_float(star.get("parallax")) or 0.0, 6) if _finite_float(star.get("parallax")) is not None else None,
                round(_finite_float(star.get("phot_g_mean_mag")) or 0.0, 6) if _finite_float(star.get("phot_g_mean_mag")) is not None else None,
                round(_finite_float(star.get("phot_bp_mean_mag")) or 0.0, 6) if _finite_float(star.get("phot_bp_mean_mag")) is not None else None,
                round(_finite_float(star.get("phot_rp_mean_mag")) or 0.0, 6) if _finite_float(star.get("phot_rp_mean_mag")) is not None else None,
                star.get("catalog_source"),
            )
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            unique_stars.append(star)
            if len(unique_stars) >= limit:
                break

        if duplicate_count > 0:
            logger.warning(f"Deduplicated {duplicate_count} repeated star rows from query results")

        return unique_stars

    def _apply_display_projection(
        self,
        points: List[Dict[str, Any]],
        bounds: Dict[str, Optional[float]],
    ) -> None:
        """Compress radial depth for visualization so distant outliers do not form false spikes."""
        distances = [
            _finite_float(point.get("distance_pc"))
            for point in points
            if _finite_float(point.get("distance_pc")) is not None
        ]
        if not distances:
            bounds["plot_x_min"] = bounds["x_min"]
            bounds["plot_x_max"] = bounds["x_max"]
            bounds["plot_y_min"] = bounds["y_min"]
            bounds["plot_y_max"] = bounds["y_max"]
            bounds["plot_z_min"] = bounds["z_min"]
            bounds["plot_z_max"] = bounds["z_max"]
            bounds["plot_distance_pc_min"] = bounds["distance_pc_min"]
            bounds["plot_distance_pc_max"] = bounds["distance_pc_max"]
            return

        far_cap = max(_percentile(distances, 0.96) or max(distances), min(distances))
        anchor = max(_percentile(distances, 0.55) or far_cap, 25.0)
        denom = math.log1p(max(far_cap / anchor, 1.0))

        plot_bounds = {
            "plot_x_min": None,
            "plot_x_max": None,
            "plot_y_min": None,
            "plot_y_max": None,
            "plot_z_min": None,
            "plot_z_max": None,
            "plot_distance_pc_min": None,
            "plot_distance_pc_max": None,
        }

        for point in points:
            x_pc = _finite_float(point.get("x_pc")) or 0.0
            y_pc = _finite_float(point.get("y_pc")) or 0.0
            z_pc = _finite_float(point.get("z_pc")) or 0.0
            distance_pc = _finite_float(point.get("distance_pc")) or math.sqrt(x_pc * x_pc + y_pc * y_pc + z_pc * z_pc)
            if distance_pc <= 0:
                point["display_x_pc"] = 0.0
                point["display_y_pc"] = 0.0
                point["display_z_pc"] = 0.0
                point["display_distance_pc"] = 0.0
                continue

            capped = min(distance_pc, far_cap)
            compressed_ratio = math.log1p(capped / anchor) / denom if denom > 0 else 1.0
            display_distance = compressed_ratio * far_cap
            factor = display_distance / distance_pc if distance_pc > 0 else 0.0
            display_x = x_pc * factor
            display_y = y_pc * factor
            display_z = z_pc * factor
            point["display_x_pc"] = display_x
            point["display_y_pc"] = display_y
            point["display_z_pc"] = display_z
            point["display_distance_pc"] = display_distance

            plot_bounds["plot_x_min"] = display_x if plot_bounds["plot_x_min"] is None else min(plot_bounds["plot_x_min"], display_x)
            plot_bounds["plot_x_max"] = display_x if plot_bounds["plot_x_max"] is None else max(plot_bounds["plot_x_max"], display_x)
            plot_bounds["plot_y_min"] = display_y if plot_bounds["plot_y_min"] is None else min(plot_bounds["plot_y_min"], display_y)
            plot_bounds["plot_y_max"] = display_y if plot_bounds["plot_y_max"] is None else max(plot_bounds["plot_y_max"], display_y)
            plot_bounds["plot_z_min"] = display_z if plot_bounds["plot_z_min"] is None else min(plot_bounds["plot_z_min"], display_z)
            plot_bounds["plot_z_max"] = display_z if plot_bounds["plot_z_max"] is None else max(plot_bounds["plot_z_max"], display_z)
            plot_bounds["plot_distance_pc_min"] = display_distance if plot_bounds["plot_distance_pc_min"] is None else min(plot_bounds["plot_distance_pc_min"], display_distance)
            plot_bounds["plot_distance_pc_max"] = display_distance if plot_bounds["plot_distance_pc_max"] is None else max(plot_bounds["plot_distance_pc_max"], display_distance)

        bounds.update(plot_bounds)

    def _nearest_region_label(self, ra: Optional[float], dec: Optional[float]) -> Tuple[str, str]:
        """Map a data-driven cluster to a known named region when the centroid is close enough."""
        if ra is None or dec is None:
            return "ML Cluster", "inferred"

        postgres_conn.connect()
        with postgres_conn.session() as session:
            regions = session.query(Region).all()

        best_name = "ML Cluster"
        best_source = "inferred"
        best_sep = None
        for region in regions:
            sep = _angular_separation_deg(ra, dec, float(region.ra), float(region.dec))
            threshold = max(float(region.radius_deg or 0.0) * 1.9, 4.0)
            if sep <= threshold and (best_sep is None or sep < best_sep):
                best_sep = sep
                best_name = region.name
                best_source = "matched_region"
        return best_name, best_source

    def _cluster_points(
        self,
        points: List[Dict[str, Any]],
        cluster_count: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Create deterministic data-driven clusters for the 3D fog layer."""
        usable = [point for point in points if point.get("display_x_pc") is not None]
        if len(usable) < 3:
            return []

        pm_values = []
        for point in usable:
            pmra = _finite_float(point.get("pmra"))
            pmdec = _finite_float(point.get("pmdec"))
            if pmra is not None:
                pm_values.append(abs(pmra))
            if pmdec is not None:
                pm_values.append(abs(pmdec))
        pm_scale = max(_percentile(pm_values, 0.75) or 1.0, 1.0)

        X = np.array([
            [
                float(point.get("display_x_pc") or 0.0),
                float(point.get("display_y_pc") or 0.0),
                float(point.get("display_z_pc") or 0.0),
                ((_finite_float(point.get("pmra")) or 0.0) / pm_scale) * 0.18,
                ((_finite_float(point.get("pmdec")) or 0.0) / pm_scale) * 0.18,
            ]
            for point in usable
        ], dtype=float)

        postgres_conn.connect()
        with postgres_conn.session() as session:
            named_regions = session.query(Region).all()

        n_points = X.shape[0]
        k = cluster_count or 3
        k = max(1, min(k, n_points))

        centroid_indices: List[int] = [int(np.argmax(np.linalg.norm(X[:, :3], axis=1)))]
        while len(centroid_indices) < k:
            chosen = X[centroid_indices]
            dist2 = np.min(np.sum((X[:, None, :] - chosen[None, :, :]) ** 2, axis=2), axis=1)
            next_index = int(np.argmax(dist2))
            if next_index in centroid_indices:
                break
            centroid_indices.append(next_index)

        centroids = X[centroid_indices].copy()
        assignments = np.zeros(n_points, dtype=int)
        for _ in range(12):
            dist2 = np.sum((X[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
            new_assignments = np.argmin(dist2, axis=1)
            if np.array_equal(new_assignments, assignments):
                break
            assignments = new_assignments
            for idx in range(len(centroids)):
                members = X[assignments == idx]
                if len(members):
                    centroids[idx] = members.mean(axis=0)

        clusters: List[Dict[str, Any]] = []
        min_cluster_size = max(18, int(len(usable) * 0.025))
        for cluster_idx in range(len(centroids)):
            member_indices = np.where(assignments == cluster_idx)[0]
            if len(member_indices) < min_cluster_size:
                continue

            members = [usable[int(idx)] for idx in member_indices]
            centroid_x = float(np.mean([float(point.get("x_pc") or 0.0) for point in members]))
            centroid_y = float(np.mean([float(point.get("y_pc") or 0.0) for point in members]))
            centroid_z = float(np.mean([float(point.get("z_pc") or 0.0) for point in members]))
            display_x = float(np.mean([float(point.get("display_x_pc") or 0.0) for point in members]))
            display_y = float(np.mean([float(point.get("display_y_pc") or 0.0) for point in members]))
            display_z = float(np.mean([float(point.get("display_z_pc") or 0.0) for point in members]))
            unit_vectors = []
            for point in members:
                ra_value = _finite_float(point.get("ra"))
                dec_value = _finite_float(point.get("dec"))
                if ra_value is None or dec_value is None:
                    continue
                ra_rad = math.radians(ra_value)
                dec_rad = math.radians(dec_value)
                cos_dec = math.cos(dec_rad)
                unit_vectors.append((
                    cos_dec * math.cos(ra_rad),
                    math.sin(dec_rad),
                    cos_dec * math.sin(ra_rad),
                ))
            if unit_vectors:
                mean_unit_x = float(np.mean([vector[0] for vector in unit_vectors]))
                mean_unit_y = float(np.mean([vector[1] for vector in unit_vectors]))
                mean_unit_z = float(np.mean([vector[2] for vector in unit_vectors]))
                ra, dec, _ = _vector_to_radec(mean_unit_x, mean_unit_y, mean_unit_z)
            else:
                ra, dec, _ = _vector_to_radec(centroid_x, centroid_y, centroid_z)
            _, _, centroid_distance = _vector_to_radec(centroid_x, centroid_y, centroid_z)

            spreads = [
                math.sqrt(
                    (float(point.get("display_x_pc") or 0.0) - display_x) ** 2
                    + (float(point.get("display_y_pc") or 0.0) - display_y) ** 2
                    + (float(point.get("display_z_pc") or 0.0) - display_z) ** 2
                )
                for point in members
            ]
            spread = sum(spreads) / len(spreads) if spreads else 0.0
            fog_radius = max(spread * 1.65, 6.0)
            suggested_zoom = max(1.6, min(18.0, 10.5 / max(spread, 0.8)))

            dominant_catalogs = [
                catalog
                for catalog, _ in Counter(
                    (str(point.get("catalog_source") or "UNKNOWN").strip().upper() for point in members)
                ).most_common(3)
            ]
            dominant_classes = [
                label
                for label, _ in Counter(
                    _normalize_object_class(point.get("object_class")) or "UNCLASSIFIED"
                    for point in members
                ).most_common(3)
            ]

            clusters.append({
                "count": len(members),
                "ra": ra,
                "dec": dec,
                "distance_pc": centroid_distance,
                "centroid_x_pc": centroid_x,
                "centroid_y_pc": centroid_y,
                "centroid_z_pc": centroid_z,
                "display_x_pc": display_x,
                "display_y_pc": display_y,
                "display_z_pc": display_z,
                "fog_radius": fog_radius,
                "suggested_zoom": suggested_zoom,
                "dominant_catalogs": dominant_catalogs,
                "dominant_object_classes": dominant_classes,
                "_region_scores": {
                    region.name: sum(
                        1
                        for point in members
                        if _angular_separation_deg(
                            float(point.get("ra") or 0.0),
                            float(point.get("dec") or 0.0),
                            float(region.ra),
                            float(region.dec),
                        ) <= max(float(region.radius_deg or 0.0) * 1.7, 3.0)
                    )
                    for region in named_regions
                },
            })

        clusters.sort(key=lambda item: -item["count"])
        used_region_names = set()
        finalized: List[Dict[str, Any]] = []
        for index, cluster in enumerate(clusters, start=1):
            region_scores = cluster.pop("_region_scores", {})
            matched_name = None
            matched_score = 0
            for region_name, score in sorted(region_scores.items(), key=lambda item: (-item[1], item[0])):
                if region_name in used_region_names:
                    continue
                if score >= max(12, int(cluster["count"] * 0.24)):
                    matched_name = region_name
                    matched_score = score
                    break

            label_source = "matched_region" if matched_name else "inferred"
            cluster["id"] = f"cluster-{index}"
            cluster["name"] = matched_name or f"ML Cluster {index}"
            cluster["label_source"] = label_source
            if matched_name:
                used_region_names.add(matched_name)
            cluster["match_score"] = matched_score
            finalized.append(cluster)

        return finalized

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius: float,
        unit: str = "deg",
        frame: str = "icrs",
        limit: int = 100,
        include_discovery: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Find all stars within a cone around given coordinates (multi-frame support).
        
        Args:
            ra: Right Ascension or Longitude
            dec: Declination or Latitude
            radius: Search radius
            unit: Radius unit ('deg', 'arcmin', 'arcsec')
            frame: Coordinate frame ('icrs', 'galactic', 'fk5')
            limit: Maximum number of results
            include_discovery: Whether to include discovery scoring
            
        Returns:
            List of star records as dictionaries
        """
        # Scientific preprocessing
        ra_icrs, dec_icrs = ScientificOrchestrator.parse_coordinates(ra, dec, frame)
        radius_deg = ScientificOrchestrator.parse_radius(radius, unit)

        logger.info(f"Cone search: {ra} {dec} ({frame}), radius={radius} {unit}")
        
        postgres_conn.connect()
        
        fetch_limit = max(limit, min(limit * 5, 2000))

        query_str = """
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                   catalog_source, object_class,
                   q3c_dist(ra, dec, :center_ra, :center_dec) AS angular_distance
            FROM stars
            WHERE q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)
            ORDER BY angular_distance
            LIMIT :fetch_limit
        """
        query = text(query_str)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {
                "center_ra": ra_icrs,
                "center_dec": dec_icrs,
                "radius": radius_deg,
                "fetch_limit": fetch_limit
            })
            
            rows = result.mappings().all()
            stars = self._dedupe_stars([dict(row) for row in rows], limit=limit)

        # Attach provenance
        provenance = ScientificOrchestrator.create_provenance(
            "cone_search", 
            {"ra": ra, "dec": dec, "radius": radius, "unit": unit, "frame": frame},
            query_str
        )
        
        for s in stars:
            s["_provenance"] = provenance
            ScientificOrchestrator.format_star_with_units(s)

        if include_discovery:
            # Simple local scoring for cone search results
            profile = _discovery_profile("balanced")
            for star in stars:
                score = 0.0
                reasons = []
                
                # Transient bonus
                if star.get("is_transient"):
                    score += 15.0 # High priority for transients
                    reasons.append(f"Active Transient Alert ({star.get('alert_name')})")

                ruwe = _finite_float(star.get("ruwe"))
                if ruwe and ruwe >= 1.4:
                    score += profile["ruwe_elevated"]
                    reasons.append(f"Elevated RUWE ({ruwe:.2f})")
                
                bp = _finite_float(star.get("phot_bp_mean_mag"))
                rp = _finite_float(star.get("phot_rp_mean_mag"))
                if bp and rp:
                    bp_rp = bp - rp
                    if bp_rp <= -0.1 or bp_rp >= 2.8:
                        score += profile["color_extreme"]
                        reasons.append(f"Extreme color (BP-RP={bp_rp:.2f})")
                
                star["discovery_score"] = round(score, 1)
                star["discovery_reasons"] = reasons
            
            # Sort by discovery score if requested
            stars.sort(key=lambda x: x.get("discovery_score", 0), reverse=True)
            
        logger.info(f"Found {len(stars)} stars in cone")
        return [self._sanitize_star(star) for star in stars]
    
    def radial_search(
        self,
        ra: float,
        dec: float,
        radius: float,
        unit: str = "deg",
        frame: str = "icrs",
        mag_limit: Optional[float] = None,
        min_parallax: Optional[float] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Cone search with optional magnitude and parallax filters (multi-frame).
        
        Args:
            ra: Right Ascension or Longitude
            dec: Declination or Latitude
            radius: Search radius
            unit: Radius unit ('deg', 'arcmin', 'arcsec')
            frame: Coordinate frame ('icrs', 'galactic', 'fk5')
            mag_limit: Maximum G-band magnitude (fainter limit)
            min_parallax: Minimum parallax in mas (distance filter)
            limit: Maximum results
            
        Returns:
            Filtered list of star records
        """
        # Scientific preprocessing
        ra_icrs, dec_icrs = ScientificOrchestrator.parse_coordinates(ra, dec, frame)
        radius_deg = ScientificOrchestrator.parse_radius(radius, unit)

        conditions = ["q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)"]
        params = {
            "center_ra": ra_icrs,
            "center_dec": dec_icrs,
            "radius": radius_deg,
            "fetch_limit": max(limit, min(limit * 5, 2000))
        }
        
        if mag_limit is not None:
            conditions.append("phot_g_mean_mag <= :mag_limit")
            params["mag_limit"] = mag_limit
        
        if min_parallax is not None:
            conditions.append("parallax >= :min_parallax")
            params["min_parallax"] = min_parallax
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                   catalog_source, object_class,
                   q3c_dist(ra, dec, :center_ra, :center_dec) AS angular_distance
            FROM stars
            WHERE {where_clause}
            ORDER BY angular_distance
            LIMIT :fetch_limit
        """)
        
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            result = session.execute(query, params)
            rows = result.mappings().all()
            stars = self._dedupe_stars([dict(row) for row in rows], limit=limit)
        
        # Attach provenance
        provenance = ScientificOrchestrator.create_provenance(
            "radial_search", 
            {"ra": ra, "dec": dec, "radius": radius, "unit": unit, "frame": frame, "mag_limit": mag_limit, "min_parallax": min_parallax},
            str(query)
        )
        
        for s in stars:
            s["_provenance"] = provenance
            ScientificOrchestrator.format_star_with_units(s)
            
        logger.info(f"Radial search: {len(stars)} stars (mag<={mag_limit}, plx>={min_parallax})")
        return [self._sanitize_star(star) for star in stars]
    
    def coordinate_lookup(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single star by its Gaia source ID.
        
        Args:
            source_id: Gaia DR3 source identifier
            
        Returns:
            Star record or None if not found
        """
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            star = session.query(Star).filter(
                Star.source_id == source_id
            ).first()
            
            if star is None:
                return None
            
            return {
                "source_id": star.source_id,
                "ra": _finite_float(star.ra),
                "dec": _finite_float(star.dec),
                "parallax": _finite_float(star.parallax),
                "pmra": _finite_float(star.pmra),
                "pmdec": _finite_float(star.pmdec),
                "phot_g_mean_mag": _finite_float(star.phot_g_mean_mag),
                "phot_bp_mean_mag": _finite_float(star.phot_bp_mean_mag),
                "phot_rp_mean_mag": _finite_float(star.phot_rp_mean_mag),
                "ruwe": _finite_float(star.ruwe),
                "catalog_source": star.catalog_source,
                "object_class": _normalize_object_class(getattr(star, "object_class", None)),
            }
    
    def nearby_stars(
        self,
        source_id: str,
        radius_deg: float = 0.1,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find stars near a known star.
        
        Args:
            source_id: Source star's Gaia ID
            radius_deg: Search radius in degrees
            limit: Maximum results
            
        Returns:
            List of nearby stars (excluding the source star)
        """
        star = self.coordinate_lookup(source_id)
        if star is None:
            logger.warning(f"Star {source_id} not found")
            return []
        
        results = self.cone_search(
            ra=star["ra"],
            dec=star["dec"],
            radius=radius_deg,
            limit=limit + 1  # +1 to exclude self
        )
        
        # Remove the source star from results
        return [s for s in results if s["source_id"] != source_id][:limit]
    
    def count_in_region(self, ra: float, dec: float, radius_deg: float) -> int:
        """Count stars in a region without returning data."""
        postgres_conn.connect()
        
        query = text("""
            SELECT COUNT(*) as cnt
            FROM stars
            WHERE q3c_radial_query(ra, dec, :ra, :dec, :radius)
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {
                "ra": ra, "dec": dec, "radius": radius_deg
            })
            return result.scalar()

    def space_volume(
        self,
        limit: int = 8000,
        min_parallax: Optional[float] = None,
        mag_limit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Return stars projected into Cartesian space for 3D visualization.

        Uses Gaia parallax to estimate distance in parsecs and converts
        spherical coordinates to a centered 3D point cloud.
        """
        postgres_conn.connect()

        filters = ["parallax > 0"]
        params: Dict[str, Any] = {"limit": limit}

        if min_parallax is not None:
            filters.append("parallax >= :min_parallax")
            params["min_parallax"] = min_parallax

        if mag_limit is not None:
            filters.append("phot_g_mean_mag <= :mag_limit")
            params["mag_limit"] = mag_limit

        where_clause = " AND ".join(filters)
        query = text(f"""
            SELECT
                source_id, ra, dec, parallax, pmra, pmdec,
                phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                catalog_source, object_class
            FROM stars
            WHERE {where_clause}
            ORDER BY COALESCE(phot_g_mean_mag, 99.0), parallax DESC, source_id
            LIMIT :limit
        """)

        with postgres_conn.session() as session:
            rows = session.execute(query, params).mappings().all()

        points: List[Dict[str, Any]] = []
        bounds = {
            "x_min": None,
            "x_max": None,
            "y_min": None,
            "y_max": None,
            "z_min": None,
            "z_max": None,
            "distance_pc_min": None,
            "distance_pc_max": None,
        }

        for row in rows:
            parallax = _finite_float(row.get("parallax"))
            if parallax is None or parallax <= 0:
                continue

            ra = _finite_float(row.get("ra"))
            dec = _finite_float(row.get("dec"))
            if ra is None or dec is None:
                continue

            distance_pc = 1000.0 / parallax
            ra_rad = math.radians(ra)
            dec_rad = math.radians(dec)
            cos_dec = math.cos(dec_rad)
            x_pc = distance_pc * cos_dec * math.cos(ra_rad)
            y_pc = distance_pc * math.sin(dec_rad)
            z_pc = distance_pc * cos_dec * math.sin(ra_rad)

            bp = _finite_float(row.get("phot_bp_mean_mag"))
            rp = _finite_float(row.get("phot_rp_mean_mag"))
            bp_rp = (bp - rp) if bp is not None and rp is not None else None

            point = {
                "source_id": row["source_id"],
                "ra": ra,
                "dec": dec,
                "parallax": parallax,
                "pmra": _finite_float(row.get("pmra")),
                "pmdec": _finite_float(row.get("pmdec")),
                "distance_pc": distance_pc,
                "distance_ly": distance_pc * 3.26156,
                "x_pc": x_pc,
                "y_pc": y_pc,
                "z_pc": z_pc,
                "phot_g_mean_mag": _finite_float(row.get("phot_g_mean_mag")),
                "phot_bp_mean_mag": bp,
                "phot_rp_mean_mag": rp,
                "bp_rp": bp_rp,
                "ruwe": _finite_float(row.get("ruwe")),
                "catalog_source": row.get("catalog_source"),
                "object_class": _normalize_object_class(row.get("object_class")),
            }
            points.append(point)

            bounds["x_min"] = x_pc if bounds["x_min"] is None else min(bounds["x_min"], x_pc)
            bounds["x_max"] = x_pc if bounds["x_max"] is None else max(bounds["x_max"], x_pc)
            bounds["y_min"] = y_pc if bounds["y_min"] is None else min(bounds["y_min"], y_pc)
            bounds["y_max"] = y_pc if bounds["y_max"] is None else max(bounds["y_max"], y_pc)
            bounds["z_min"] = z_pc if bounds["z_min"] is None else min(bounds["z_min"], z_pc)
            bounds["z_max"] = z_pc if bounds["z_max"] is None else max(bounds["z_max"], z_pc)
            bounds["distance_pc_min"] = distance_pc if bounds["distance_pc_min"] is None else min(bounds["distance_pc_min"], distance_pc)
            bounds["distance_pc_max"] = distance_pc if bounds["distance_pc_max"] is None else max(bounds["distance_pc_max"], distance_pc)

        self._apply_display_projection(points, bounds)

        return {
            "count": len(points),
            "points": points,
            "bounds": bounds,
            "filters": {
                "limit": limit,
                "min_parallax": min_parallax,
                "mag_limit": mag_limit,
            },
        }

    def ml_clusters(
        self,
        limit: int = 4000,
        min_parallax: Optional[float] = None,
        mag_limit: Optional[float] = None,
        cluster_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return data-driven clusters derived from the current 3D volume sample."""
        volume = self.space_volume(
            limit=limit,
            min_parallax=min_parallax,
            mag_limit=mag_limit,
        )
        clusters = self._cluster_points(volume["points"], cluster_count=cluster_count)
        return {
            "count": len(clusters),
            "clusters": clusters,
            "filters": {
                "limit": limit,
                "min_parallax": min_parallax,
                "mag_limit": mag_limit,
                "cluster_count": cluster_count,
            },
        }

    def catalog_summary(self) -> List[Dict[str, Any]]:
        """Return counts per catalog for discovery and comparison views."""
        postgres_conn.connect()

        query = text("""
            SELECT COALESCE(NULLIF(TRIM(catalog_source), ''), 'UNKNOWN') AS catalog_source,
                   COUNT(*) AS count
            FROM stars
            GROUP BY COALESCE(NULLIF(TRIM(catalog_source), ''), 'UNKNOWN')
            ORDER BY COUNT(*) DESC, catalog_source
        """)

        with postgres_conn.session() as session:
            rows = session.execute(query).mappings().all()

        return [
            {"catalog_source": row["catalog_source"], "count": int(row["count"])}
            for row in rows
        ]

    def discovery_candidates(
        self,
        limit: int = 15,
        pool_limit: int = 3000,
        radius_deg: float = 0.08,
        mode: str = "balanced",
    ) -> Dict[str, Any]:
        """Score potentially unusual objects for the Discovery Mode panel."""
        postgres_conn.connect()
        profile = _discovery_profile(mode)

        gaia_query = text("""
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                   catalog_source, object_class
            FROM stars
            WHERE ra IS NOT NULL AND dec IS NOT NULL
              AND UPPER(COALESCE(catalog_source, 'GAIA')) = 'GAIA'
            ORDER BY
                COALESCE(phot_g_mean_mag, 99.0),
                CASE WHEN parallax IS NULL THEN -1 ELSE parallax END DESC,
                source_id
            LIMIT :gaia_limit
        """)

        with postgres_conn.session() as session:
            gaia_rows = session.execute(
                gaia_query,
                {"gaia_limit": pool_limit},
            ).mappings().all()

            other_query = text("""
                SELECT source_id, ra, dec, parallax, pmra, pmdec,
                       phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                       catalog_source, object_class
                FROM stars
                WHERE ra IS NOT NULL AND dec IS NOT NULL
                  AND UPPER(COALESCE(catalog_source, 'GAIA')) <> 'GAIA'
                ORDER BY
                    COALESCE(phot_g_mean_mag, 99.0),
                    CASE WHEN parallax IS NULL THEN -1 ELSE parallax END DESC,
                    source_id
            """)
            other_rows = session.execute(other_query).mappings().all()

        rows = list(gaia_rows) + list(other_rows)

        provisional: List[Dict[str, Any]] = []

        for row in rows:
            catalog_source = (row.get("catalog_source") or "GAIA").strip().upper()
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
                if ruwe >= 2.0:
                    score += profile["ruwe_high"]
                    reasons.append(f"RUWE {ruwe:.2f} is very high")
                elif ruwe >= 1.4:
                    score += profile["ruwe_elevated"]
                    reasons.append(f"RUWE {ruwe:.2f} is elevated")
                elif ruwe < 0.9:
                    score += profile["ruwe_tight"]
                    reasons.append(f"RUWE {ruwe:.2f} is unusually tight")
            else:
                score += profile["ruwe_missing"]
                reasons.append("RUWE missing")

            if bp_rp is not None:
                if bp_rp <= -0.1:
                    score += profile["color_extreme"]
                    reasons.append(f"very blue BP-RP {bp_rp:.2f}")
                elif bp_rp >= 2.8:
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
                if motion >= 80:
                    score += profile["motion_high"]
                    reasons.append(f"fast proper motion {motion:.1f} mas/yr")
                elif motion >= 40:
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
                }
            )

        provisional.sort(key=lambda item: (item["score"], item["phot_g_mean_mag"] is not None, -(item["phot_g_mean_mag"] or 99.0)), reverse=True)
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

        def _angular_distance_deg(ra_a: float, dec_a: float, ra_b: float, dec_b: float) -> float:
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

        for item in workset:
            local_density = 0
            matched_catalogs: List[str] = []
            matched_catalog_set = set()
            for row in rows:
                other_ra = _finite_float(row.get("ra"))
                other_dec = _finite_float(row.get("dec"))
                if other_ra is None or other_dec is None:
                    continue

                if row["source_id"] == item["source_id"]:
                    continue

                if _angular_distance_deg(item["ra"], item["dec"], other_ra, other_dec) > radius_deg:
                    continue

                local_density += 1
                catalog = (row.get("catalog_source") or "UNKNOWN").strip().upper()
                if catalog != item["catalog_source"]:
                    matched_catalog_set.add(catalog)

            matched_catalogs = sorted(matched_catalog_set)

            if local_density > 1:
                crowd_bonus = min(max(local_density - 1, 0) * profile["density_scale"], profile["density_cap"])
                item["score"] += crowd_bonus
                item["reasons"].append(f"crowded field with {local_density} neighbors")

            if matched_catalogs:
                cross_catalog_hits += 1
                cross_bonus = min(
                    profile["cross_match_base"] + len(matched_catalogs) * profile["cross_match_per_catalog"],
                    profile["cross_match_cap"],
                )
                item["score"] += cross_bonus
                item["reasons"].append(
                    "cross-matched with " + ", ".join(sorted(set(matched_catalogs)))
                )

            if item["catalog_source"] != "GAIA":
                item["score"] += min(
                    len(matched_catalogs) * profile["catalog_overlap_bonus"],
                    profile["catalog_overlap_cap"],
                )

            item["local_density"] = local_density
            item["matched_catalogs"] = sorted(set(matched_catalogs))
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

        top_candidates = [
            {
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
                "reasons": item["reasons"][:4],
            }
            for item in enriched[:limit]
        ]

        return {
            "count": len(top_candidates),
            "top_candidates": top_candidates,
            "catalog_summary": self.catalog_summary(),
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

    def compute_local_density(self, ra: float, dec: float, radius: float = 0.5) -> float:
        """
        Estimate local stellar surface density in stars/deg^2.
        """
        stars = self.cone_search(ra, dec, radius, limit=1000)
        area = math.pi * (radius ** 2)
        return len(stars) / area if area > 0 else 0.0

    def is_density_anomaly(self, star: Dict[str, Any], neighborhood_radius: float = 1.0) -> Dict[str, Any]:
        """
        Check if a star resides in a significant density peak relative to its neighborhood.
        """
        ra, dec = star.get('ra'), star.get('dec')
        local_d = self.compute_local_density(ra, dec, 0.1) # Small aperture
        neighborhood_d = self.compute_local_density(ra, dec, neighborhood_radius) # Large aperture
        
        ratio = local_d / neighborhood_d if neighborhood_d > 0 else 1.0
        
        return {
            "local_density": round(local_d, 1),
            "neighborhood_density": round(neighborhood_d, 1),
            "density_ratio": round(ratio, 2),
            "is_peak": ratio > 3.0 # >3x denser than surroundings
        }

    def _sanitize_star(self, star: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of a star row with NaN values converted to null-friendly None."""
        cleaned = dict(star)
        for key, val in cleaned.items():
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                cleaned[key] = None
        return cleaned
        """Return a copy of a star row with NaN values converted to null-friendly None."""
        cleaned = dict(star)
        for key in (
            "ra",
            "dec",
            "parallax",
            "pmra",
            "pmdec",
            "phot_g_mean_mag",
            "phot_bp_mean_mag",
            "phot_rp_mean_mag",
            "ruwe",
            "angular_distance",
        ):
            if key in cleaned:
                cleaned[key] = _finite_float(cleaned.get(key))
        return cleaned
