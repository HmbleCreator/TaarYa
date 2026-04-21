"""Real-time Gaia Photometric Science Alerts ingestion."""

import logging
import requests
from typing import List, Dict, Any
from io import StringIO
import pandas as pd

logger = logging.getLogger(__name__)

class GaiaAlertsIngestor:
    """
    Ingests transient event data from the Gaia Science Alerts stream.
    Used for discovering supernovae, microlensing, and variable stars.
    """
    
    ALERTS_URL = "http://gsaweb.ast.cam.ac.uk/alerts/alerts.csv"

    def fetch_latest_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch the most recent alerts from the Cambridge stream."""
        try:
            logger.info("Fetching latest Gaia alerts...")
            response = requests.get(self.ALERTS_URL)
            response.raise_for_status()
            
            df = pd.read_csv(StringIO(response.text))
            # Alerts are sorted by date desc usually
            latest = df.head(limit)
            
            alerts = []
            for _, row in latest.iterrows():
                alerts.append({
                    "alert_name": row.get("name"),
                    "date": row.get("jd"),
                    "ra": row.get("ra"),
                    "dec": row.get("dec"),
                    "alert_mag": row.get("mag"),
                    "class": row.get("class"),
                    "discovery_mag": row.get("disc_mag")
                })
            return alerts
        except Exception as e:
            logger.error(f"Failed to fetch Gaia alerts: {e}")
            return []

    def get_alert_details(self, alert_name: str) -> Dict[str, Any]:
        """Fetch lightcurve and detail for a specific alert."""
        # Cambridge GSA provides specific URLs for lightcurves
        url = f"http://gsaweb.ast.cam.ac.uk/alerts/alert/{alert_name}/lightcurve.csv"
        try:
            res = requests.get(url)
            if res.status_code == 200:
                return {"alert": alert_name, "lightcurve_available": True, "url": url}
            return {"alert": alert_name, "lightcurve_available": False}
        except:
            return {"error": "Connection failed"}
