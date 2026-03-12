import json
from queue import Queue

from src.agent.agent import build_system_prompt_sync
from src.agent.tools import cone_search
from src.agent.streaming import StreamingCallbackHandler
from src.retrieval.spatial_search import SpatialSearch


class DummyAction:
    def __init__(self, tool, tool_input, log=""):
        self.tool = tool
        self.tool_input = tool_input
        self.log = log


def test_streaming_handler_hides_scratchpad_events():
    queue = Queue()
    handler = StreamingCallbackHandler(queue)

    handler.on_agent_action(DummyAction("cone_search", {"ra": 1}, "Thought: search"))
    handler.on_text("Observation: hidden from user")

    assert queue.empty(), "Scratchpad events should not be streamed to the frontend"


def test_streaming_handler_keeps_clean_final_answer_fallback():
    queue = Queue()
    handler = StreamingCallbackHandler(queue)

    handler.on_agent_action(DummyAction("Final Answer", "A clean answer for the user."))

    assert handler.final_answer_candidate == "A clean answer for the user."


def test_spatial_search_dedupes_identical_measurements():
    search = SpatialSearch()
    stars = [
        {
            "source_id": "1",
            "ra": 83.634,
            "dec": -5.423,
            "parallax": 7.364,
            "phot_g_mean_mag": 17.82,
            "phot_bp_mean_mag": 18.11,
            "phot_rp_mean_mag": 17.01,
            "catalog_source": "GAIA",
        },
        {
            "source_id": "2",
            "ra": 83.634,
            "dec": -5.423,
            "parallax": 7.364,
            "phot_g_mean_mag": 17.82,
            "phot_bp_mean_mag": 18.11,
            "phot_rp_mean_mag": 17.01,
            "catalog_source": "GAIA",
        },
        {
            "source_id": "3",
            "ra": 83.700,
            "dec": -5.500,
            "parallax": 4.100,
            "phot_g_mean_mag": 15.01,
            "phot_bp_mean_mag": 15.60,
            "phot_rp_mean_mag": 14.42,
            "catalog_source": "GAIA",
        },
    ]

    deduped = search._dedupe_stars(stars, limit=10)

    assert [star["source_id"] for star in deduped] == ["1", "3"]


def test_cone_search_returns_out_of_coverage_without_hitting_spatial_search(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.get_catalog_coverage_raw",
        lambda: {
            "total_stars": 1000,
            "ra_min": 43.65,
            "ra_max": 46.36,
            "dec_min": 0.02,
            "dec_max": 2.19,
            "suggested_search_center": {"ra": 45.01, "dec": 1.11},
        },
    )

    def fail_if_called(**kwargs):
        raise AssertionError("Spatial cone search should not run for out-of-coverage coordinates")

    monkeypatch.setattr("src.agent.tools._spatial.cone_search", fail_if_called)

    result = cone_search.invoke({"ra": 83.82, "dec": -5.39, "radius_deg": 0.5, "limit": 20})
    payload = json.loads(result)

    assert payload["status"] == "OUT_OF_COVERAGE"
    assert payload["count"] == 0


def test_build_system_prompt_sync_injects_live_coverage(monkeypatch):
    monkeypatch.setattr(
        "src.agent.agent.get_catalog_coverage_raw",
        lambda: {
            "total_stars": 1000,
            "ra_min": 43.65,
            "ra_max": 46.36,
            "dec_min": 0.02,
            "dec_max": 2.19,
            "suggested_search_center": {"ra": 45.01, "dec": 1.11},
        },
    )

    prompt = build_system_prompt_sync()

    assert "CURRENT DATABASE STATE" in prompt
    assert "Stars loaded: 1000" in prompt
    assert "RA range: 43.65° to 46.36°" in prompt
    assert "Suggested search center: RA 45.01°, Dec 1.11°" in prompt
