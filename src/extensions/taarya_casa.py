"""CASA-compatible connector for TaarYa retrieval."""

import json
import urllib.request
import urllib.parse

class TaarYaCASA:
    """
    A lightweight connector that can be imported directly into a CASA shell.
    Uses only standard libraries to ensure compatibility with CASA's Python env.
    """

    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url

    def search_candidates(self, ra, dec, radius=0.1):
        """
        Query TaarYa for discovery candidates from within CASA.
        """
        params = urllib.parse.urlencode({
            'ra': ra,
            'dec': dec,
            'radius': radius,
            'unit': 'deg',
            'include_discovery': 'true'
        })
        url = f"{self.base_url}/api/stars/cone-search?{params}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())
                stars = data.get("stars", [])
                print(f"TaarYa found {len(stars)} stars in the region.")
                for s in stars[:5]:
                    score = s.get("discovery_score", 0)
                    print(f"  - {s['source_id']} [Score: {score}]")
                return stars
        except Exception as e:
            print(f"Failed to connect to TaarYa API: {e}")
            return []

    def broadcast_to_aladin(self, ra, dec, name="CASA Discovery"):
        """Trigger Aladin to point at sky from CASA."""
        # This calls the TaarYa API which then uses SAMP
        pass

if __name__ == "__main__":
    # Example usage in CASA:
    # from taarya_casa import TaarYaCASA
    # ty = TaarYaCASA()
    # stars = ty.search_candidates(ra=56.75, dec=24.12)
    pass
