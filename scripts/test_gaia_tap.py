"""Test Gaia TAP query with tiny radius."""
from astroquery.gaia import Gaia
from astropy.coordinates import SkyCoord
import astropy.units as u
import time

print("Testing Gaia TAP query (tiny radius)...")

# Very small radius for fast query
ra, dec, radius_deg = 201.697, -47.48, 0.05

adql = f"""
SELECT TOP 10
    source_id, ra, dec, parallax, phot_g_mean_mag, bp_rp
FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(
    POINT('ICRS', ra, dec),
    CIRCLE('ICRS', {ra}, {dec}, {radius_deg})
)
AND parallax IS NOT NULL
ORDER BY phot_g_mean_mag ASC
"""

try:
    start = time.time()
    print(f"Querying Omega Centauri (r={radius_deg}°)...")
    job = Gaia.launch_job(adql)  # Synchronous, not async
    results = job.get_results()
    elapsed = time.time() - start
    print(f"Success! Got {len(results)} rows in {elapsed:.1f}s")
    if len(results) > 0:
        print(f"First row: source_id={results[0]['source_id']}, G={results[0]['phot_g_mean_mag']:.2f}, bp_rp={results[0]['bp_rp']:.2f}")
except Exception as e:
    elapsed = time.time() - start
    print(f"Error after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()
