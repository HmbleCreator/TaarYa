"""SAMP (Simple Application Messaging Protocol) Client for astronomical tool interoperability."""

import logging
import time
import os
import tempfile
from astropy.samp import SAMPHubProxy, SAMPClient
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class TaarYaSAMPClient:
    """
    Connects TaarYa to the local SAMP hub (TOPCAT, Aladin, DS9).
    Enables 'Discovery-to-Desktop' workflows with two-way communication.
    """

    def __init__(self, agent_service=None):
        self.client = SAMPClient(SAMPHubProxy())
        self.agent_service = agent_service
        self._connected = False
        self._metadata = {
            "samp.name": "TaarYa",
            "samp.description.text": "Hybrid Retrieval Extension for Cross-Catalog Astronomical Discovery",
            "samp.icon.url": "https://raw.githubusercontent.com/HmbleCreator/TaarYa/main/static/TaarYaLogo.png",
            "taarya.version": "1.0.0",
            "author.name": "Amit Kumar",
            "author.affiliation": "Indian Institute of Science"
        }

    def connect(self) -> bool:
        """Attempt to connect to a running SAMP hub and register metadata."""
        try:
            if not self.client.hub.is_connected:
                self.client.connect()
            
            # Register metadata so it shows up in TOPCAT/Aladin interop menus
            self.client.hub.declare_metadata(self._metadata)
            
            # Subscribe to common MTypes for two-way communication
            self.client.bind_receive_call("table.highlight.row", self._on_row_highlight)
            self.client.bind_receive_notification("table.highlight.row", self._on_row_highlight)
            self.client.bind_receive_call("coord.pointAtSky", self._on_point_at_sky)
            self.client.bind_receive_notification("coord.pointAtSky", self._on_point_at_sky)
            
            self._connected = True
            logger.info("Connected to SAMP Hub and registered metadata.")
            return True
        except Exception as e:
            logger.warning(f"Could not connect to SAMP Hub: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._connected:
            try:
                self.client.disconnect()
            except:
                pass
            self._connected = False

    def _ensure_connected(self) -> bool:
        """Check connection and attempt auto-reconnect if needed."""
        if not self._connected or not self.client.hub.is_connected:
            return self.connect()
        return True

    def _on_row_highlight(self, private_key, sender_id, msg_id, mtype, params, extra):
        """Handle row highlight from TOPCAT/Aladin."""
        table_id = params.get("table-id")
        row_index = params.get("row")
        logger.info(f"SAMP: Row {row_index} highlighted in table {table_id} by {sender_id}")
        
        # In a real implementation, we would use the row index to look up the star
        # and trigger a research briefing in the UI.
        if self.agent_service:
            # Placeholder for triggering UI update or research briefing
            pass
        
        if msg_id:
            self.client.hub.reply(msg_id, {"samp.status": "samp.ok", "samp.result": {}})

    def _on_point_at_sky(self, private_key, sender_id, msg_id, mtype, params, extra):
        """Handle coordinate selection from Aladin/DS9."""
        ra = params.get("ra")
        dec = params.get("dec")
        logger.info(f"SAMP: Coordinate selected RA={ra}, Dec={dec} by {sender_id}")
        
        if msg_id:
            self.client.hub.reply(msg_id, {"samp.status": "samp.ok", "samp.result": {}})

    def broadcast_star(self, ra: float, dec: float, name: str = "TaarYa Candidate"):
        """Send a single point to Aladin/DS9."""
        if not self._ensure_connected():
            return {"error": "No SAMP Hub found."}

        try:
            message = {
                "samp.mtype": "coord.pointAtSky",
                "samp.params": {
                    "ra": str(ra),
                    "dec": str(dec),
                    "name": name
                }
            }
            self.client.hub.broadcast_notification(message)
            return {"status": "Broadcasted coordinates to SAMP Hub."}
        except Exception as e:
            self._connected = False # Might be a broken pipe
            return {"error": f"SAMP broadcast failed: {e}"}

    def broadcast_table(self, stars: List[Dict[str, Any]], table_name: str = "TaarYa_Discoveries"):
        """Send a whole table to TOPCAT using a temporary compliant VOTable."""
        if not self._ensure_connected():
            return {"error": "No SAMP Hub found."}

        from src.utils.scientific_output import export_to_votable

        try:
            votable_xml = export_to_votable(stars)
            with tempfile.NamedTemporaryFile(suffix=".vot", mode='w', delete=False) as tmp:
                tmp.write(votable_xml)
                tmp_path = tmp.name

            # Convert to absolute path and handle Windows separators for file:// URL
            abs_path = os.path.abspath(tmp_path).replace("\\", "/")
            if not abs_path.startswith("/"):
                abs_path = "/" + abs_path
            file_url = "file://" + abs_path

            message = {
                "samp.mtype": "table.load.votable",
                "samp.params": {
                    "url": file_url,
                    "table-id": table_name,
                    "name": table_name
                }
            }
            self.client.hub.broadcast_notification(message)
            return {"status": f"Broadcasted {len(stars)} stars as a compliant VOTable to SAMP Hub."}
        except Exception as e:
            self._connected = False
            return {"error": f"SAMP table broadcast failed: {e}"}

