"""Real-time Gaia Photometric Science Alerts ingestion."""

import logging
import requests
from typing import List, Dict, Any
from io import StringIO
import pandas as pd
from sqlalchemy import text
from src.database import postgres_conn

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

    def ingest_alerts(self, limit: int = 100) -> int:
        """Fetch alerts and ingest them into the PostgreSQL database."""
        alerts = self.fetch_latest_alerts(limit)
        if not alerts:
            return 0
        
        postgres_conn.connect()
        ingested = 0
        
        insert_query = text("""
            INSERT INTO stars (
                source_id, alert_name, ra, dec, phot_g_mean_mag, 
                object_class, is_transient, catalog_source
            )
            VALUES (
                :source_id, :alert_name, :ra, :dec, :mag, 
                :class, 1, 'GAIA_ALERTS'
            )
            ON CONFLICT (source_id) DO UPDATE SET
                is_transient = 1,
                alert_name = EXCLUDED.alert_name,
                object_class = COALESCE(stars.object_class, EXCLUDED.object_class)
        """)
        
        with postgres_conn.session() as session:
            for a in alerts:
                # GSA alerts don't always have Gaia Source IDs, so we use alert name as source_id 
                # if needed, or better, we prefix it.
                source_id = f"GSA_{a['alert_name']}"
                
                try:
                    session.execute(insert_query, {
                        "source_id": source_id,
                        "alert_name": a["alert_name"],
                        "ra": a["ra"],
                        "dec": a["dec"],
                        "mag": a["alert_mag"],
                        "class": a["class"]
                    })
                    ingested += 1
                except Exception as e:
                    logger.warning(f"Failed to ingest alert {a['alert_name']}: {e}")
            
            session.commit()
            
        logger.info(f"Ingested {ingested} Gaia alerts into PostgreSQL.")
        return ingested

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
