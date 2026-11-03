"""Unit tests for deterministic scientific export helpers."""

import unittest

from src.extensions.taarya_ds9 import TaarYaDS9
from src.extensions.taarya_mesa import TaarYaMESA
from src.utils.ner_extractor import NERExtractor


class ScientificExportTests(unittest.TestCase):
    """Verify helper outputs that should work without live backends."""

    def test_ds9_region_render_includes_candidates(self):
        ds9 = TaarYaDS9()
        content = ds9.render_region_file(
            [
                {"source_id": "A", "ra": 12.3, "dec": -4.5, "score": 16.2},
                {"source_id": "B", "ra": 13.0, "dec": -4.0, "score": 9.0},
            ]
        )

        self.assertIn("# Region file format: DS9 version 4.1", content)
        self.assertIn('circle(12.3,-4.5,10.0") # color=red text={A | score=16.2}', content)
        self.assertIn('circle(13.0,-4.0,10.0") # color=green text={B | score=9.0}', content)

    def test_mesa_inlist_builder_uses_star_metadata(self):
        content = TaarYaMESA.build_inlist(
            {
                "source_id": "1234567890123456789",
                "teff_estimated_k": 6400,
                "catalog_source": "GAIA",
            }
        )

        self.assertIn("initial_mass = 1.15", content)
        self.assertIn("initial_z = 0.0200", content)
        self.assertIn("Gaia source_id 1234567890123456789", content)

    def test_ner_extractor_keeps_direct_gaia_ids(self):
        extractor = NERExtractor()
        ids = extractor.process_text("Candidate Gaia DR3 1234567890123456789 near the Pleiades field.")

        self.assertEqual(ids, ["1234567890123456789"])

    def test_ner_extractor_finds_catalog_names_and_clusters(self):
        extractor = NERExtractor()
        names = extractor.extract_names("We compare Sirius, HD 48915, and HIP 32349 against field stars.")
        clusters = extractor.extract_cluster_mentions("Targets in the Pleiades (M45) and Hyades were analysed.")

        self.assertIn("Sirius", names)
        self.assertIn("HD 48915", names)
        self.assertIn("HIP 32349", names)
        self.assertEqual(clusters, ["pleiades", "hyades"])


if __name__ == "__main__":
    unittest.main()
