"""SAOImage DS9 XPA connector for automated image alignment."""

import subprocess
import logging

logger = logging.getLogger(__name__)

class TaarYaDS9:
    """
    Controls SAOImage DS9 via the XPA (X Public Access) messaging system.
    Requires 'xpaset' and 'xpaget' to be in the system PATH.
    """

    @staticmethod
    def is_ds9_running():
        try:
            subprocess.run(["xpaget", "ds9"], capture_output=True, check=True)
            return True
        except:
            return False

    @staticmethod
    def point_at_sky(ra, dec):
        """Move DS9 viewport to specific ICRS coordinates."""
        try:
            cmd = ["xpaset", "-p", "ds9", "pan", "to", str(ra), str(dec), "wcs", "icrs"]
            subprocess.run(cmd, check=True)
            return True
        except Exception as e:
            logger.error(f"DS9 XPA command failed: {e}")
            return False

    @staticmethod
    def load_region(ra, dec, radius_arcsec=10, label="TaarYa"):
        """Draw a discovery region on the DS9 display."""
        region_str = f"fk5; circle({ra}, {dec}, {radius_arcsec}\") # text='{label}'"
        try:
            subprocess.run(["xpaset", "-p", "ds9", "regions"], input=region_str.encode(), check=True)
            return True
        except Exception as e:
            logger.error(f"DS9 Region load failed: {e}")
            return False
