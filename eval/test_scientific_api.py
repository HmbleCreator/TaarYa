"""Test script for scientific API endpoints."""

import json
import requests
import time

BASE_URL = "http://localhost:8000"


def test_cone_search_export():
    """Test cone search with different export formats."""
    print("Testing /api/cone-search/export...")

    # Test CSV format
    r = requests.get(f"{BASE_URL}/api/cone-search/export", params={
        "ra": 56.75, "dec": 24.12, "radius_deg": 0.5,
        "limit": 5, "format": "csv"
    })
    print(f"  CSV format: {r.status_code}")
    if r.status_code == 200:
        lines = r.text.strip().split("\n")
        print(f"    Lines returned: {len(lines)}")
        print(f"    Header: {lines[0][:80]}")
    else:
        print(f"    Response: {r.text[:200]}")

    # Test JSON format
    r = requests.get(f"{BASE_URL}/api/cone-search/export", params={
        "ra": 56.75, "dec": 24.12, "radius_deg": 0.5,
        "limit": 5, "format": "json"
    })
    print(f"  JSON format: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Stars returned: {data.get('total_results', len(data.get('stars', [])))}")

    # Test VOTable format
    r = requests.get(f"{BASE_URL}/api/cone-search/export", params={
        "ra": 56.75, "dec": 24.12, "radius_deg": 0.5,
        "limit": 3, "format": "votable"
    })
    print(f"  VOTable format: {r.status_code}")
    if r.status_code == 200:
        print(f"    Content type: {r.headers.get('content-type')}")
        print(f"    Starts with: {r.text[:60]}")


def test_hr_diagram():
    """Test HR diagram generation."""
    print("\nTesting /api/hr-diagram...")

    # Test ASCII format
    r = requests.get(f"{BASE_URL}/api/hr-diagram", params={
        "ra": 66.75, "dec": 15.87, "radius_deg": 1.0,
        "limit": 50, "ascii": "true"
    })
    print(f"  ASCII format: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Format: {data.get('format')}")
        print(f"    Total stars: {data.get('statistics', {}).get('total_stars')}")
        populations = data.get('statistics', {}).get('population_distribution', {})
        print(f"    Populations: {populations}")
    else:
        print(f"    Response: {r.text[:200]}")

    # Test plotly format
    r = requests.get(f"{BASE_URL}/api/hr-diagram", params={
        "ra": 66.75, "dec": 15.87, "radius_deg": 1.0,
        "limit": 50, "ascii": "false"
    })
    print(f"  Plotly format: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Format: {data.get('format')}")
        plotly_data = data.get('data', {})
        print(f"    Points: {len(plotly_data.get('x', []))}")


def test_simbad_validation():
    """Test SIMBAD validation endpoint."""
    print("\nTesting /api/simbad/validate...")

    # First get some stars
    r = requests.get(f"{BASE_URL}/api/cone-search/export", params={
        "ra": 66.75, "dec": 15.87, "radius_deg": 0.5,
        "limit": 5, "format": "json"
    })
    if r.status_code == 200:
        data = r.json()
        stars = data.get("stars", [])

        if stars:
            # Test SIMBAD validation
            r = requests.post(
                f"{BASE_URL}/api/simbad/validate",
                json=stars[:3],
                params={"radius_arcsec": 5.0}
            )
            print(f"  SIMBAD validation: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"    Total: {data.get('total_stars')}")
                print(f"    Validated: {data.get('validated_count')}")
        else:
            print("  No stars found to test SIMBAD")
    else:
        print(f"  Could not get stars: {r.status_code} - {r.text[:100]}")


def test_filter_by_otype():
    """Test filtering by object type."""
    print("\nTesting /api/filter/by-otype...")

    r = requests.get(f"{BASE_URL}/api/filter/by-otype", params={
        "ra": 66.75, "dec": 15.87, "radius_deg": 1.0,
        "include_types": "Star"
    })
    print(f"  Filter by Star type: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Stars returned: {data.get('total_found')}")
    else:
        print(f"    Response: {r.text[:200]}")


def test_health_check():
    """Test basic health check."""
    print("\nTesting /health...")
    r = requests.get(f"{BASE_URL}/health")
    print(f"  Status: {r.status_code} - {r.json()}")


def test_catalog_comparison():
    """Test catalog comparison endpoint."""
    print("\nTesting /api/catalog/comparison...")
    r = requests.get(f"{BASE_URL}/api/catalog/comparison", params={
        "ra": 66.75, "dec": 15.87, "radius_deg": 1.0
    })
    print(f"  Catalog comparison: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Total stars: {data.get('total_stars')}")
        print(f"    With SIMBAD match: {data.get('with_simbad_match')}")
    else:
        print(f"    Response: {r.text[:200]}")


if __name__ == "__main__":
    print("=" * 60)
    print("TAARYA SCIENTIFIC API TESTS")
    print("=" * 60)

    test_health_check()
    test_cone_search_export()
    test_hr_diagram()
    test_filter_by_otype()
    test_catalog_comparison()
    test_simbad_validation()

    print("\n" + "=" * 60)
    print("TESTS COMPLETE")
    print("=" * 60)
