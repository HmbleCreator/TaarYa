# Changelog

All notable changes to TaarYa are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-04-21

### Added

- **Hybrid retrieval engine** combining PostgreSQL/Q3C (spatial), Qdrant (semantic), and Neo4j (graph) backends behind a unified orchestration layer.
- **Discovery ranking** with 3 configurable profiles (`strict`, `balanced`, `aggressive`), 7 signal families, and uncertainty-aware scoring (SNR-based parallax penalties, confidence bands).
- **Formal ablation study** (`eval/ablation_formal.py`): 4 configurations × 5 sky regions with IR metrics (P@k, R@k, MRR, nDCG, F1). Live result: **+300.5% F1@10** and **+575.2% MRR** vs spatial-only baseline.
- **50 benchmark queries** with ground truth labels across 12 task categories (`eval/benchmark_queries.json`).
- **Discovery validation** (`eval/validate_discovery.py`): 6 anomaly types × 5 regions.
- **ArXiv corpus expansion pipeline** (`src/ingestion/arxiv_ingest.py`): 50 queries × 10 thematic categories, batch upserts, resumable ingestion. Current corpus: **6,464 papers**.
- **Time-domain alert ingestion** (`src/ingestion/alert_ingest.py`): TNS and ALeRCE broker support with spatial cross-matching to Gaia stars.
- **Extended sky coverage** (`scripts/expand_sky_coverage.py`): 30 additional regions across 6 types (GC, OB, SFR, MG, OC, CAL) with optional Gaia TAP+ fetching.
- **Publication-grade HR diagrams** with evolutionary track overlays (ZAMS, RGB, WD, HB) citing Pecaut & Mamajek (2013), Bressan+ (2012), Bergeron+ (2011), Catelan+ (2009).
- **Cross-catalog overlap analysis** endpoint (`GET /api/catalog/overlap`).
- **VO interoperability**: DS9 region export, MESA inlists, SAMP broadcast, Aladin deep links, VOTable/CSV/JSON export.
- **Provenance logging**: `X-TaarYa-Session-Id` headers, session manifests, `.zip` bundle export.
- **CI/CD pipeline**: GitHub Actions 2-tier workflow (unit-tests → eval-offline), local regression harness (`scripts/run_regression.py`).
- **CLI entry points**: `taarya-server`, `taarya-ingest`, `taarya-readiness`, `taarya-ablation`, `taarya-corpus`.
- **Graph entity linking**: Multi-strategy NER (Gaia DR3 prefix matching, catalog ID resolution, common star name lookup, SIMBAD fallback).
- **Uncertainty propagation**: First-order δ-method for derived absolute magnitudes with formal SNR gating.

### Fixed

- `SpatialSearch.nearby_stars()` API signature mismatch (`radius_deg` → `radius`).
- `datetime.utcnow()` deprecation (Python 3.12) replaced with `datetime.now(timezone.utc)` across 7 files.
- `ALIASED_CLUSTERS` moved from function scope to module level in `graph_ingest.py`.
- Corrupt import ordering and duplicate logger line in `graph_ingest.py`.
- `transformers` dependency pinned to `>=4.40,<5` to prevent circular import crashes.
- Embedding model loading probe in test skip guards to prevent CI-time import failures.

### Changed

- Benchmark queries expanded from 35 to 50 with full ground truth labels.
- NER extractor expanded to 200+ common star names and 40+ local coordinate entries.
- Paper corpus expanded from 1,475 to 6,464 papers.
- Sky coverage expanded from 8 to 38 regions.
- Test suite: **38 passed, 0 failed**.

## [0.1.0] — 2026-04-01

### Added

- Initial TaarYa implementation with FastAPI backend.
- PostgreSQL/Q3C spatial search, Qdrant vector search, Neo4j graph search.
- LangChain-based agentic query routing.
- Glassmorphism web dashboard (Chat, Explore, Settings tabs).
- Basic NER extractor and SIMBAD validation.
- Gaia DR3 catalog ingestion pipeline.
