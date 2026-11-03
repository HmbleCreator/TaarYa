"""Manual retry helper for previously flaky API endpoints.

This file is intentionally import-safe under pytest collection.
Run it directly if you want the old ad hoc retry behavior:

    python tests/test_api_retry.py
"""

from __future__ import annotations

import httpx


def main() -> None:
    """Retry selected endpoints with a longer timeout."""
    with httpx.Client(timeout=60, verify=False) as client:
        print("=== Retrying failed endpoints ===\n")

        print("1. Papers Search (semantic)...")
        try:
            r = client.get("http://localhost:8000/api/papers/search", params={"q": "stellar evolution"})
            print(f"   Status: {r.status_code}")
            print(f"   Response: {r.text[:300]}")
        except Exception as exc:  # pragma: no cover - manual helper
            print(f"   ERROR: {exc}")

        print("\n2. Hybrid Search (text)...")
        try:
            r = client.get("http://localhost:8000/api/search/hybrid", params={"q": "red giant stars", "limit": 3})
            print(f"   Status: {r.status_code}")
            print(f"   Response: {r.text[:300]}")
        except Exception as exc:  # pragma: no cover - manual helper
            print(f"   ERROR: {exc}")

        print("\n3. Cone with Context...")
        try:
            r = client.get(
                "http://localhost:8000/api/search/cone-with-context",
                params={"ra": 45, "dec": 0.5, "radius": 0.5, "limit": 3},
            )
            print(f"   Status: {r.status_code}")
            print(f"   Response: {r.text[:400]}")
        except Exception as exc:  # pragma: no cover - manual helper
            print(f"   ERROR: {exc}")

        print("\nDone!")


if __name__ == "__main__":
    main()
