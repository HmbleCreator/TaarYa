"""Test single Gaia TAP query with timeout."""
from astroquery.gaia import Gaia
import time

print("Testing Omega Centauri query (r=0.3 deg, TOP 50)...")

adql = """SELECT TOP 50
    source_id, ra, dec, parallax, phot_g_mean_mag,
    phot_bp_mean_mag, phot_rp_mean_mag, bp_rp, ruwe, radial_velocity
FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(
    POINT('ICRS', ra, dec),
    CIRCLE('ICRS', 201.697, -47.48, 0.3))
AND parallax IS NOT NULL
ORDER BY phot_g_mean_mag ASC"""

try:
    start = time.time()
    # Use synchronous launch_job
    job = Gaia.launch_job(adql)
    results = job.get_results()
    elapsed = time.time() - start
    print(f"Success! Got {len(results)} rows in {elapsed:.1f}s")
    if len(results) > 0:
        r = results[0]
        print(f"Sample: source_id={r['source_id']}, G={r['phot_g_mean_mag']:.2f}, bp_rp={r['bp_rp']:.2f}")
except Exception as e:
    elapsed = time.time() - start
    print(f"Error after {elapsed:.1f}s: {e}")
