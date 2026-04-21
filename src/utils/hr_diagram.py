"""Hertzsprung-Russell (HR) diagram generation for stellar analysis.

The HR diagram is a fundamental tool in stellar astrophysics plotting
luminosity vs. temperature (or color index). This module generates
publication-quality HR diagrams from TaarYa stellar data.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def estimate_absolute_magnitude(g_mag: float, parallax_mas: float) -> Optional[float]:
    """Estimate absolute magnitude from apparent magnitude and parallax.

    Args:
        g_mag: Gaia G-band apparent magnitude
        parallax_mas: Parallax in milliarcseconds

    Returns:
        Absolute magnitude or None if parallax is invalid
    """
    if g_mag is None or parallax_mas is None or parallax_mas <= 0:
        return None

    distance_pc = 1000.0 / parallax_mas
    absolute_mag = g_mag - 5 * math.log10(distance_pc) + 5
    return absolute_mag


def compute_bp_rp(bp_mag: Optional[float], rp_mag: Optional[float]) -> Optional[float]:
    """Compute BP-RP color index.

    Args:
        bp_mag: Gaia BP magnitude
        rp_mag: Gaia RP magnitude

    Returns:
        BP-RP color or None if inputs invalid
    """
    if bp_mag is None or rp_mag is None:
        return None
    return bp_mag - rp_mag


def classify_stellar_population(
    bp_rp: Optional[float],
    absolute_mag: Optional[float],
    ruwe: Optional[float] = None
) -> str:
    """Classify stellar population based on HR diagram position.

    Args:
        bp_rp: BP-RP color index
        absolute_mag: Absolute G magnitude
        ruwe: RUWE value (optional, for binarity indication)

    Returns:
        Population classification string
    """
    if bp_rp is None or absolute_mag is None:
        return "Unknown"

    # Very blue stars (hot)
    if bp_rp < -0.2:
        if absolute_mag < 2:
            return "Blue Supergiant"
        elif absolute_mag < 5:
            return "Blue Straggler"
        else:
            return "Hot Subdwarf"

    # Blue stars
    if bp_rp < 0.5:
        if absolute_mag < 4:
            return "Main Sequence (O-B)"
        else:
            return "White Dwarf Candidate"

    # Yellow stars
    if bp_rp < 1.6:
        if absolute_mag < 4:
            return "Giant/Subgiant"
        elif absolute_mag < 6:
            return "Main Sequence (A-F)"
        else:
            return "Main Sequence (G)"

    # Orange stars
    if bp_rp < 2.7:
        if absolute_mag < 5:
            return "K Giant"
        elif absolute_mag < 9:
            return "Main Sequence (K)"
        else:
            return "K Dwarf"

    # Red stars (M type)
    if bp_rp >= 2.7:
        if absolute_mag < 5:
            return "M Giant"
        elif absolute_mag < 10:
            return "M Dwarf"
        else:
            return "Brown Dwarf Candidate"

    return "Unknown"


def generate_hr_diagram_data(stars: List[Dict], min_snr: float = 5.0) -> Dict[str, Any]:
    """Generate HR diagram data from stellar list with quality filtering.

    Args:
        stars: List of star dictionaries with photometry
        min_snr: Minimum parallax SNR (parallax/parallax_err) for inclusion

    Returns:
        Dictionary with HR diagram data and statistics
    """
    hr_points = []
    population_counts = {}

    for star in stars:
        g_mag = star.get("phot_g_mean_mag")
        bp_mag = star.get("phot_bp_mean_mag")
        rp_mag = star.get("phot_rp_mean_mag")
        parallax = star.get("parallax")
        parallax_err = star.get("parallax_error")
        ruwe = star.get("ruwe")

        # Scientific Quality Cut: Parallax SNR
        if parallax and parallax_err and parallax_err > 0:
            snr = parallax / parallax_err
            if snr < min_snr:
                continue
        elif parallax is None or parallax <= 0:
            continue

        bp_rp = compute_bp_rp(bp_mag, rp_mag)
        abs_mag = estimate_absolute_magnitude(g_mag, parallax)
        population = classify_stellar_population(bp_rp, abs_mag, ruwe)

        if bp_rp is not None and abs_mag is not None:
            hr_points.append({
                "source_id": star.get("source_id"),
                "bp_rp": bp_rp,
                "absolute_mag": abs_mag,
                "apparent_mag": g_mag,
                "parallax": parallax,
                "parallax_snr": parallax / parallax_err if parallax_err else None,
                "ruwe": ruwe,
                "population": population,
                "discovery_score": star.get("discovery_score", 0),
                "discovery_reasons": star.get("discovery_reasons", []),
            })

            population_counts[population] = population_counts.get(population, 0) + 1

    return {
        "points": hr_points,
        "total_stars": len(hr_points),
        "population_distribution": population_counts,
        "color_range": [
            min(p["bp_rp"] for p in hr_points) if hr_points else 0,
            max(p["bp_rp"] for p in hr_points) if hr_points else 0,
        ],
        "magnitude_range": [
            min(p["absolute_mag"] for p in hr_points) if hr_points else 0,
            max(p["absolute_mag"] for p in hr_points) if hr_points else 0,
        ],
    }


def generate_ascii_hr_diagram(hr_data: Dict, width: int = 80, height: int = 40) -> str:
    """Generate ASCII art HR diagram for quick visualization.

    Args:
        hr_data: Output from generate_hr_diagram_data
        width: Width of diagram in characters
        height: Height of diagram in characters

    Returns:
        ASCII HR diagram string
    """
    points = hr_data.get("points", [])
    if not points:
        return "No valid data for HR diagram"

    color_min, color_max = hr_data["color_range"]
    mag_min, mag_max = hr_data["magnitude_range"]

    if mag_min > mag_max:
        mag_min, mag_max = mag_max, mag_min

    grid = [[" "] * width for _ in range(height)]

    for point in points:
        bp_rp = point["bp_rp"]
        abs_mag = point["absolute_mag"]

        col = int((bp_rp - color_min) / (color_max - color_min + 0.001) * (width - 1))
        row = int((abs_mag - mag_min) / (mag_max - mag_min + 0.001) * (height - 1))
        row = height - 1 - row

        col = max(0, min(width - 1, col))
        row = max(0, min(height - 1, row))

        score = point.get("discovery_score", 0)
        if score > 10:
            grid[row][col] = "*"
        elif score > 5:
            grid[row][col] = "+"
        else:
            grid[row][col] = "."

    header = f"{'BP-RP (Color Index)':^{width}}\n"
    header += f"{'Blue':<10}{'Yellow':^20}{'Red':>10}\n"
    header += f"{'+' + '-' * (width-2) + '+'}\n"

    footer = f"{'-' * width}\n"
    footer += f"{'Magnitude':^{width}}\n"
    footer += f"{f'Mag {mag_min:.1f}':.<30}{f'Mag {mag_max:.1f}':.>30}\n"

    diagram = header + "\n".join("|" + "".join(row) + "|" for row in grid) + "\n" + footer

    return diagram


def format_hr_diagram_for_plotly(hr_data: Dict) -> Dict[str, Any]:
    """Format HR diagram data for Plotly visualization.

    Returns a dictionary ready for Plotly.scatter with marker properties.

    Args:
        hr_data: Output from generate_hr_diagram_data

    Returns:
        Dictionary with Plotly trace data
    """
    points = hr_data.get("points", [])

    return {
        "x": [p["bp_rp"] for p in points],
        "y": [p["absolute_mag"] for p in points],
        "mode": "markers",
        "type": "scatter",
        "text": [
            f"ID: {p['source_id']}<br>"
            f"BP-RP: {p['bp_rp']:.3f}<br>"
            f"M_G: {p['absolute_mag']:.2f}<br>"
            f"Population: {p['population']}<br>"
            f"Discovery: {p['discovery_score']:.1f}"
            for p in points
        ],
        "hoverinfo": "text",
        "marker": {
            "size": [4 + p["discovery_score"] for p in points],
            "colorscale": "Viridis",
            "color": [p["discovery_score"] for p in points],
            "cauto": True,
        },
        "xaxis": "BP-RP (Color Index) -->",
        "yaxis": "Absolute Magnitude --> (inverted)",
    }


# Standard stellar evolution tracks for reference (approximate)
STELLAR_TRACKS = {
    "zero_age_main_sequence": [
        (-0.3, 6.5), (0.0, 4.5), (0.3, 3.5), (0.5, 2.8),
        (0.7, 2.2), (1.0, 1.5), (1.5, 0.5), (2.0, -0.5),
    ],
    "red_giant_branch": [
        (0.5, 2.8), (0.8, 2.5), (1.0, 2.0), (1.2, 1.2),
        (1.4, 0.5), (1.6, 0.0), (1.8, -0.5), (2.0, -0.8),
    ],
    "white_dwarf_cooling": [
        (0.0, 10), (0.2, 10.5), (0.3, 11), (0.4, 11.5),
        (0.5, 12), (0.6, 12.5), (0.7, 13), (0.8, 13.5),
    ],
}


def annotate_evolutionary_tracks() -> List[Dict]:
    """Return evolutionary track annotations for HR diagram.

    Returns:
        List of track annotation dictionaries
    """
    tracks = []
    for name, points in STELLAR_TRACKS.items():
        tracks.append({
            "name": name.replace("_", " ").title(),
            "points": points,
        })
    return tracks
