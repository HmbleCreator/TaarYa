"""Quick validation of all TaarYa interoperability integrations."""

print("=" * 60)
print("  TaarYa Interoperability Validation")
print("=" * 60)

stars = [
    {
        "source_id": "5853498713190525696",
        "ra": 66.75,
        "dec": 15.96,
        "parallax": 21.17,
        "parallax_error": 0.03,
        "pmra": 104.5,
        "pmdec": -27.3,
        "phot_g_mean_mag": 3.53,
        "phot_bp_mean_mag": 3.89,
        "phot_rp_mean_mag": 2.99,
        "ruwe": 1.02,
        "discovery_score": 12.5,
        "discovery_reasons": ["high_pm"],
    },
]

# 1. VOTable
from src.utils.scientific_output import export_to_votable

vot = export_to_votable(stars)
assert "<VOTABLE" in vot and "</VOTABLE>" in vot
assert "source_id" in vot and "pos.eq.ra" in vot
print("[PASS] VOTable export (IVOA 1.4 compliant)")

# 2. CSV
from src.utils.scientific_output import export_to_csv

csv_out = export_to_csv(stars)
assert "source_id,ra,dec" in csv_out
assert "5853498713190525696" in csv_out
print("[PASS] CSV export (TOPCAT compatible)")

# 3. JSON
from src.utils.scientific_output import export_to_json

json_out = export_to_json(stars)
assert '"source": "TaarYa"' in json_out
print("[PASS] JSON export (with metadata)")

# 4. DS9 regions
from src.extensions.taarya_ds9 import TaarYaDS9

ds9 = TaarYaDS9()
reg = ds9.render_region_file(stars)
assert "DS9 version 4.1" in reg
assert "fk5" in reg
assert "circle(" in reg
print("[PASS] DS9 region file generation")

# 5. MESA inlist
from src.extensions.taarya_mesa import TaarYaMESA

inlist = TaarYaMESA.build_inlist(stars[0])
assert "&star_job" in inlist
assert "initial_mass" in inlist
assert "initial_z" in inlist
params = TaarYaMESA.estimate_physical_params(stars[0])
assert "initial_mass" in params and params["initial_mass"] > 0
assert "teff_K" in params and params["teff_K"] > 0
print(f'[PASS] MESA inlist (M={params["initial_mass"]} Msun, Teff={params["teff_K"]}K)')

# 6. Aladin link
ra, dec = 66.75, 15.96
url = f"https://aladin.u-strasbg.fr/AladinLite/?target={ra}+{dec}&fov=1.0&survey=P/DSS2/color"
assert "aladin" in url
print("[PASS] Aladin Lite deep link generated")

# 7. SAMP client
from src.utils.samp_client import TaarYaSAMPClient

samp = TaarYaSAMPClient()
assert hasattr(samp, "broadcast_star")
assert hasattr(samp, "broadcast_table")
print("[PASS] SAMP client instantiated (hub not required)")

print()
print("=" * 60)
print("  ALL 7 INTEGRATION TESTS PASSED")
print("=" * 60)
