"""SAMP (Simple Application Messaging Protocol) Client for astronomical tool interoperability."""

import logging
import time
from astropy.samp import SAMPHubProxy
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class TaarYaSAMPClient:
    """
    Connects TaarYa to the local SAMP hub (TOPCAT, Aladin, DS9).
    Enables 'Discovery-to-Desktop' workflows.
    """

    def __init__(self):
        self.proxy = SAMPHubProxy()
        self._connected = False
        self._private_key = None

    def connect(self) -> bool:
        """Attempt to connect to a running SAMP hub."""
        try:
            self.proxy.connect()
            self._connected = True
            logger.info("Connected to SAMP Hub.")
            return True
        except Exception as e:
            logger.warning(f"Could not connect to SAMP Hub: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._connected:
            self.proxy.disconnect()
            self._connected = False

    def broadcast_star(self, ra: float, dec: float, name: str = "TaarYa Candidate"):
        """Send a single point to Aladin/DS9."""
        if not self._connected and not self.connect():
            return {"error": "No SAMP Hub found (is Aladin or TOPCAT open?)"}

        try:
            # Point-at-sky message
            message = {
                "samp.mtype": "coord.pointAtSky",
                "samp.params": {
                    "ra": str(ra),
                    "dec": str(dec),
                    "name": name
                }
            }
            self.proxy.broadcast_message(message)
            return {"status": "Broadcasted coordinates to SAMP Hub."}
        except Exception as e:
            return {"error": f"SAMP broadcast failed: {e}"}

    def broadcast_table(self, stars: List[Dict[str, Any]], table_name: str = "TaarYa_Discoveries"):
        """Send a whole table to TOPCAT using a temporary VOTable."""
        if not self._connected and not self.connect():
            return {"error": "No SAMP Hub found."}

        import tempfile
        import os
        from src.utils.scientific_output import export_to_votable

        try:
            # 1. Create temporary VOTable file
            votable_xml = export_to_votable(stars)
            with tempfile.NamedTemporaryFile(suffix=".vot", mode='w', delete=False) as tmp:
                tmp.write(votable_xml)
                tmp_path = tmp.name

            # 2. In professional environments, SAMP Hubs expect a URL.
            # For local use, a file:// URL works for TOPCAT.
            file_url = "file://" + os.path.abspath(tmp_path).replace("\\", "/")

            # 3. Broadcast 'table.load.votable'
            message = {
                "samp.mtype": "table.load.votable",
                "samp.params": {
                    "url": file_url,
                    "table-id": table_name,
                    "name": table_name
                }
            }
            self.proxy.broadcast_message(message)
            
            # Note: We don't delete the temp file immediately as the Hub 
            # might take a few seconds to read it.
            return {"status": f"Broadcasted {len(stars)} stars as a VOTable to SAMP Hub."}
        except Exception as e:
            return {"error": f"SAMP table broadcast failed: {e}"}
