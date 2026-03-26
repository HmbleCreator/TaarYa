"""Spatial search using PostgreSQL Q3C extension."""
import math
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import text

from src.database import postgres_conn
from src.models import Star

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
    
    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Find all stars within a cone around given coordinates.
        
        Args:
            ra: Right Ascension in degrees (0-360)
            dec: Declination in degrees (-90 to 90)
            radius_deg: Search radius in degrees
            limit: Maximum number of results
            
        Returns:
            List of star records as dictionaries
        """
        logger.info(f"Cone search: RA={ra}, Dec={dec}, radius={radius_deg}°")
        
        postgres_conn.connect()
        
        fetch_limit = max(limit, min(limit * 5, 2000))

        query = text("""
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
                   catalog_source,
                   q3c_dist(ra, dec, :center_ra, :center_dec) AS angular_distance
            FROM stars
            WHERE q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)
            ORDER BY angular_distance
            LIMIT :fetch_limit
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {
                "center_ra": ra,
                "center_dec": dec,
                "radius": radius_deg,
                "fetch_limit": fetch_limit
            })
            
            rows = result.mappings().all()
            stars = self._dedupe_stars([dict(row) for row in rows], limit=limit)
            
        logger.info(f"Found {len(stars)} stars in cone")
        return [self._sanitize_star(star) for star in stars]
    
    def radial_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        mag_limit: Optional[float] = None,
        min_parallax: Optional[float] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Cone search with optional magnitude and parallax filters.
        
        Args:
            ra: Right Ascension in degrees
            dec: Declination in degrees
            radius_deg: Search radius in degrees
            mag_limit: Maximum G-band magnitude (fainter limit)
            min_parallax: Minimum parallax in mas (distance filter)
            limit: Maximum results
            
        Returns:
            Filtered list of star records
        """
        conditions = ["q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)"]
        params = {
            "center_ra": ra,
            "center_dec": dec,
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
                   catalog_source,
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
            radius_deg=radius_deg,
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
                catalog_source
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
                   catalog_source
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
                       catalog_source
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

    def _sanitize_star(self, star: Dict[str, Any]) -> Dict[str, Any]:
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
