from queue import Queue

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
