"""Generate all interop demo files for testing with TOPCAT, DS9, MESA, and Aladin."""

import random
from src.extensions.taarya_ds9 import TaarYaDS9
from src.extensions.taarya_mesa import TaarYaMESA

random.seed(42)
stars = []
for i in range(25):
    bp_rp = random.uniform(-0.1, 2.5)
    g_mag = random.uniform(3.0, 14.0)
    plx = 20.0 + random.gauss(0, 2.0)
    score = random.uniform(0, 25)
    stars.append({
        "source_id": str(5853498713190525696 + i),
        "ra": 66.5 + random.uniform(0, 1.5),
        "dec": 15.5 + random.uniform(0, 1.5),
        "parallax": round(plx, 4),
        "phot_g_mean_mag": round(g_mag, 3),
        "phot_bp_mean_mag": round(g_mag + bp_rp * 0.6, 3),
        "phot_rp_mean_mag": round(g_mag - bp_rp * 0.4, 3),
        "discovery_score": round(score, 2),
        "catalog_source": "GAIA_DR3",
    })

# 1. DS9 Region File
ds9 = TaarYaDS9()
reg = ds9.render_region_file(stars)
with open("taarya_hyades_demo.reg", "w") as f:
    f.write(reg)
print("[DONE] DS9 region file -> taarya_hyades_demo.reg")
print("  Color coding: RED (score>=15), YELLOW (score>=10), GREEN (score<10)")

# 2. MESA Inlist for highest-score star
best = max(stars, key=lambda s: s["discovery_score"])
inlist = TaarYaMESA.build_inlist(best)
with open("taarya_star.inlist", "w") as f:
    f.write(inlist)
params = TaarYaMESA.estimate_physical_params(best)
sid = best["source_id"]
mass = params["initial_mass"]
teff = params["teff_K"]
z = params["initial_z"]
print(f"[DONE] MESA inlist -> taarya_star.inlist")
print(f"  Star: {sid} | M={mass} Msun | Teff={teff}K | Z={z}")

# 3. MESA cluster inlist
cluster_inlist = TaarYaMESA.build_cluster_inlist(stars, "Hyades")
with open("taarya_hyades_cluster.inlist", "w") as f:
    f.write(cluster_inlist)
print("[DONE] MESA cluster inlist -> taarya_hyades_cluster.inlist")

# 4. Aladin Lite URL
url = "https://aladin.u-strasbg.fr/AladinLite/?target=66.75+15.96&fov=2.0&survey=P/DSS2/color"
print(f"[DONE] Aladin Lite URL:")
print(f"  {url}")

# Print MESA inlist content for inspection
print()
print("=" * 60)
print("  MESA INLIST PREVIEW")
print("=" * 60)
print(inlist)

print()
print("=" * 60)
print("  DS9 REGION FILE PREVIEW (first 10 lines)")
print("=" * 60)
for line in reg.split("\n")[:10]:
    print(line)

print()
print("=" * 60)
print("  ALL FILES GENERATED — ready for testing!")
print("=" * 60)
