"""Run all HTTP endpoint checks and print a table."""
import json, time, urllib.request, urllib.error, sys

BASE = "http://localhost:8000"

checks = [
    ("GET",  "/health",                  None),
    ("GET",  "/ready",                   None),
    ("GET",  "/api/stats",               None),
    ("GET",  "/api/regions",             None),
    ("GET",  "/api/ingestion/status",    None),
    ("GET",  "/api/stars/cone-search?ra=56.75&dec=24.12&radius=1&limit=5", None),
    ("POST", "/api/stars/cone-search",   {"ra": 56.75, "dec": 24.12, "radius": 1, "limit": 5}),
    ("GET",  "/api/papers/search?q=stellar+evolution&limit=3", None),
    ("POST", "/api/papers/search",       {"q": "stellar evolution", "limit": 3}),
    ("GET",  "/api/search/hybrid?q=Pleiades&ra=56.75&dec=24.12&radius=1&limit=5", None),
    ("POST", "/api/search/hybrid",       {"q": "Pleiades", "ra": 56.75, "dec": 24.12, "radius": 1, "limit": 5}),
    ("GET",  "/api/stars/discovery?limit=3", None),
    ("GET",  "/api/stars/count?ra=56.75&dec=24.12&radius=1", None),
]

print(f"{'Method':<6} {'Endpoint':<55} {'Code':<5} {'Time':>8}  {'Note'}")
print("-" * 100)

passed = 0
failed = 0

for method, path, body in checks:
    url = BASE + path
    t0 = time.time()
    try:
        if body:
            data = json.dumps(body).encode()
            req = urllib.request.Request(url, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
            resp_body = resp.read()
    except urllib.error.HTTPError as e:
        code = e.code
        resp_body = b""
    except Exception as e:
        code = 0
        resp_body = str(e).encode()

    elapsed = time.time() - t0
    note = ""
    if code >= 200 and code < 300:
        note = "OK"
        passed += 1
    elif code == 307 or code == 302:
        note = "REDIRECT"
        passed += 1
    else:
        note = f"FAIL ({resp_body[:80].decode(errors='replace')})"
        failed += 1

    short_path = path.split("?")[0] + ("?..." if "?" in path else "")
    print(f"{method:<6} {short_path:<55} {code:<5} {elapsed*1000:>7.0f}ms  {note}")

print("-" * 100)
print(f"TOTAL: {passed} passed, {failed} failed out of {len(checks)}")
sys.exit(1 if failed else 0)
