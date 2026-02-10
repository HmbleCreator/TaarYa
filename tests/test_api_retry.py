"""Retry the 3 failed API endpoints with longer timeout."""
import httpx

client = httpx.Client(timeout=60)

print("=== Retrying failed endpoints ===\n")

# 1. Papers semantic search
print("1. Papers Search (semantic)...")
try:
    r = client.get("http://localhost:8000/api/papers/search", params={"q": "stellar evolution"})
    print(f"   Status: {r.status_code}")
    print(f"   Response: {r.text[:300]}")
except Exception as e:
    print(f"   ERROR: {e}")

# 2. Hybrid text search
print("\n2. Hybrid Search (text)...")
try:
    r = client.get("http://localhost:8000/api/search/hybrid", params={"q": "red giant stars", "limit": 3})
    print(f"   Status: {r.status_code}")
    print(f"   Response: {r.text[:300]}")
except Exception as e:
    print(f"   ERROR: {e}")

# 3. Cone with context
print("\n3. Cone with Context...")
try:
    r = client.get("http://localhost:8000/api/search/cone-with-context", params={"ra": 45, "dec": 0.5, "radius": 0.5, "limit": 3})
    print(f"   Status: {r.status_code}")
    print(f"   Response: {r.text[:400]}")
except Exception as e:
    print(f"   ERROR: {e}")

client.close()
print("\nDone!")
