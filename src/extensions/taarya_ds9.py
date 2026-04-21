"""SAOImage DS9 XPA connector for automated image alignment."""

import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TaarYaDS9:
    """
    Controls SAOImage DS9 via the XPA (X Public Access) messaging system.
    Requires 'xpaset' and 'xpaget' to be in the system PATH.
    """

    def __init__(self, target="ds9"):
        self.target = target

    def is_ds9_running(self):
        try:
            subprocess.run(["xpaget", self.target], capture_output=True, check=True)
            return True
        except:
            return False

    def point_at_sky(self, ra, dec):
        """Move DS9 viewport to specific ICRS coordinates."""
        try:
            cmd = ["xpaset", "-p", self.target, "pan", "to", str(ra), str(dec), "wcs", "icrs"]
            subprocess.run(cmd, check=True)
            return True
        except Exception as e:
            logger.error(f"DS9 XPA pan failed: {e}")
            return False

    def render_region_file(self, stars: List[Dict[str, Any]], radius_arcsec: float = 10.0) -> str:
        """Render DS9 region text for a list of discovery candidates."""
        lines = [
            "# Region file format: DS9 version 4.1",
            'global color=green dashlist=8 3 width=1 font="helvetica 10 normal roman" '
            "select=1 highlite=1 dash=0 fixed=0 edit=1 move=1 delete=1 include=1 source=1",
            "fk5",
        ]

        for star in stars:
            ra = star.get("ra")
            dec = star.get("dec")
            if ra is None or dec is None:
                continue
            score = float(star.get("discovery_score", star.get("score", 0.0)) or 0.0)
            color = "red" if score >= 15 else "yellow" if score >= 10 else "green"
            label = star.get("source_id", "candidate")
            lines.append(
                f'circle({ra},{dec},{radius_arcsec}") # color={color} text={{{label} | score={score:.1f}}}'
            )

        return "\n".join(lines) + "\n"

    def load_region_text(self, region_text: str) -> bool:
        """Load pre-rendered DS9 region text through XPA."""
        with tempfile.NamedTemporaryFile(suffix=".reg", mode="w", delete=False) as tmp:
            tmp.write(region_text)
            tmp_path = tmp.name

        try:
            subprocess.run(["xpaset", "-p", self.target, "regions", "load", tmp_path], check=True)
            return True
        except Exception as e:
            logger.error(f"DS9 region load failed: {e}")
            return False
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def load_region_file(self, stars: List[Dict[str, Any]]) -> bool:
        """Generate and load a DS9 region file for a list of discovery candidates."""
        return self.load_region_text(self.render_region_file(stars))

    def load_fits_cutout(self, ra, dec, size_deg=0.05):
        """
        Trigger DS9 to load a FITS cutout from a public service (e.g., PanSTARRS).
        """
        # Example URL for PanSTARRS cutout
        url = f"https://ps1images.stsci.edu/cgi-bin/ps1cutouts?ra={ra}&dec={dec}&size=240&format=fits"
        try:
            subprocess.run(["xpaset", "-p", self.target, "file", url], check=True)
            return True
        except Exception as e:
            logger.error(f"DS9 FITS load failed: {e}")
            return False
