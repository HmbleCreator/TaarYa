"""Test all API endpoints against the running server."""
import httpx
import sys
import json

BASE = "http://localhost:8000"

def p(label, resp):
    """Print result concisely."""
    status = "✅" if resp.status_code == 200 else "❌"
    data = resp.json()
    # Truncate large responses
    text = json.dumps(data, indent=2)
    if len(text) > 500:
        text = text[:500] + "\n  ... (truncated)"
    print(f"\n{status} {label}  [{resp.status_code}]")
    print(text)
    return resp.status_code == 200

def main():
    client = httpx.Client(timeout=30)
    passed = 0
    failed = 0
    
    tests = [
        ("GET /", f"{BASE}/"),
        ("GET /health", f"{BASE}/health"),
        ("Cone Search (RA=45, Dec=0.5, r=1)", f"{BASE}/api/stars/cone-search?ra=45&dec=0.5&radius=1&limit=5"),
        ("Cone Search + mag filter", f"{BASE}/api/stars/cone-search?ra=45&dec=0.5&radius=1&mag_limit=18&limit=5"),
        ("Star Lookup", None),  # Dynamic - needs source_id from cone search
        ("Nearby Stars", None),  # Dynamic
        ("Star Count", f"{BASE}/api/stars/count?ra=45&dec=0.5&radius=1"),
        ("Papers Search (semantic)", f"{BASE}/api/papers/search?q=stellar+evolution+milky+way"),
        ("Papers by Star", None),  # Dynamic
        ("Papers by Topic", f"{BASE}/api/papers/topic?keyword=stellar"),
        ("Hybrid Search (spatial)", f"{BASE}/api/search/hybrid?ra=45&dec=0.5&radius=1&limit=3"),
        ("Hybrid Search (text)", f"{BASE}/api/search/hybrid?q=red+giant+stars&limit=3"),
        ("Cone with Context", f"{BASE}/api/search/cone-with-context?ra=45&dec=0.5&radius=0.5&limit=3"),
        ("System Stats", f"{BASE}/api/stats"),
    ]
    
    source_id = None
    
    for label, url in tests:
        try:
            # Handle dynamic tests
            if label == "Star Lookup":
                if source_id:
                    url = f"{BASE}/api/stars/lookup/{source_id}"
                else:
                    print(f"\n⏭ {label}  [SKIPPED - no source_id]")
                    continue
            elif label == "Nearby Stars":
                if source_id:
                    url = f"{BASE}/api/stars/nearby/{source_id}?radius=0.5&limit=3"
                else:
                    print(f"\n⏭ {label}  [SKIPPED - no source_id]")
                    continue
            elif label == "Papers by Star":
                if source_id:
                    url = f"{BASE}/api/papers/by-star/{source_id}"
                else:
                    print(f"\n⏭ {label}  [SKIPPED - no source_id]")
                    continue
            
            resp = client.get(url)
            ok = p(label, resp)
            
            # Capture source_id from first cone search for subsequent tests
            if label.startswith("Cone Search (") and ok:
                data = resp.json()
                if data.get("stars"):
                    source_id = data["stars"][0]["source_id"]
            
            if ok:
                passed += 1
            else:
                failed += 1
                
        except Exception as e:
            print(f"\n❌ {label}  [ERROR: {e}]")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
    print(f"{'='*50}")
    
    client.close()
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
