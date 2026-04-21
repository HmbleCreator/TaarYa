"""Unit tests for the standalone discovery-ranking module."""

from src.retrieval.discovery import rank_discovery_candidates, summarize_catalogs


def test_rank_discovery_candidates_prioritizes_cross_catalog_anomaly():
    rows = [
        {
            "source_id": "GAIA-1",
            "ra": 10.0,
            "dec": 20.0,
            "parallax": 10.0,
            "pmra": 5.0,
            "pmdec": 4.0,
            "phot_g_mean_mag": 12.0,
            "phot_bp_mean_mag": 12.3,
            "phot_rp_mean_mag": 11.9,
            "ruwe": 1.0,
            "catalog_source": "GAIA",
            "object_class": "star",
        },
        {
            "source_id": "WISE-1",
            "ra": 10.01,
            "dec": 20.01,
            "parallax": 5.0,
            "pmra": 90.0,
            "pmdec": 15.0,
            "phot_g_mean_mag": 9.0,
            "phot_bp_mean_mag": None,
            "phot_rp_mean_mag": None,
            "ruwe": 2.3,
            "catalog_source": "WISE",
            "object_class": "infrared_source",
        },
        {
            "source_id": "GAIA-2",
            "ra": 50.0,
            "dec": -10.0,
            "parallax": 4.0,
            "pmra": 1.0,
            "pmdec": 1.0,
            "phot_g_mean_mag": 16.0,
            "phot_bp_mean_mag": 16.2,
            "phot_rp_mean_mag": 15.9,
            "ruwe": 1.1,
            "catalog_source": "GAIA",
            "object_class": "star",
        },
    ]

    result = rank_discovery_candidates(rows, limit=2, pool_limit=2, radius_deg=0.05)

    assert result["top_candidates"][0]["source_id"] == "WISE-1"
    assert "GAIA" in result["top_candidates"][0]["matched_catalogs"]
    assert result["top_candidates"][0]["score"] > result["top_candidates"][1]["score"]


def test_rank_discovery_candidates_keeps_non_gaia_rows_even_with_small_gaia_pool():
    rows = [
        {
            "source_id": "GAIA-1",
            "ra": 10.0,
            "dec": 10.0,
            "parallax": 12.0,
            "pmra": 1.0,
            "pmdec": 1.0,
            "phot_g_mean_mag": 10.0,
            "phot_bp_mean_mag": 10.2,
            "phot_rp_mean_mag": 9.9,
            "ruwe": 1.0,
            "catalog_source": "GAIA",
            "object_class": "star",
        },
        {
            "source_id": "GAIA-2",
            "ra": 30.0,
            "dec": 10.0,
            "parallax": 10.0,
            "pmra": 1.0,
            "pmdec": 1.0,
            "phot_g_mean_mag": 11.0,
            "phot_bp_mean_mag": 11.2,
            "phot_rp_mean_mag": 10.9,
            "ruwe": 1.0,
            "catalog_source": "GAIA",
            "object_class": "star",
        },
        {
            "source_id": "2MASS-1",
            "ra": 30.01,
            "dec": 10.01,
            "parallax": 6.0,
            "pmra": 60.0,
            "pmdec": 10.0,
            "phot_g_mean_mag": 17.0,
            "phot_bp_mean_mag": None,
            "phot_rp_mean_mag": None,
            "ruwe": None,
            "catalog_source": "2MASS",
            "object_class": "red_source",
        },
    ]

    result = rank_discovery_candidates(rows, limit=3, pool_limit=1, radius_deg=0.05)
    candidate_ids = [item["source_id"] for item in result["top_candidates"]]

    assert "2MASS-1" in candidate_ids
    assert result["count"] >= 2


def test_summarize_catalogs_normalizes_case_and_missing_values():
    rows = [
        {"catalog_source": "gaia"},
        {"catalog_source": "GAIA"},
        {"catalog_source": "wise"},
        {"catalog_source": ""},
        {"catalog_source": None},
    ]

    summary = summarize_catalogs(rows)

    assert summary == [
        {"catalog_source": "GAIA", "count": 2},
        {"catalog_source": "UNKNOWN", "count": 2},
        {"catalog_source": "WISE", "count": 1},
    ]
