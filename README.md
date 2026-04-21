<div align="center">
<img width="1536" height="1024" alt="TaarYaLogo" src="https://github.com/user-attachments/assets/877b032d-3f1f-4b6f-8ec6-9ca6442698b8" />


![Project Status](https://img.shields.io/badge/status-publication--ready-brightgreen.svg) 
![Python](https://img.shields.io/badge/python-3.10+-blue.svg) 
![Tests](https://img.shields.io/badge/tests-38%20passed-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Papers](https://img.shields.io/badge/corpus-6%2C464%20papers-blueviolet.svg)
![Stars](https://img.shields.io/badge/stars-29%2C798%20Gaia%20DR3-orange.svg)

**Illuminating the Cosmos.**

An intelligent, Agentic RAG-driven architecture that integrates Gaia DR3, SIMBAD, and scientific literature to act as your autonomous research co-pilot.

</div>


**TaarYa** is an intelligent, agentic architecture designed to act as the digital eye for modern astronomy. In a universe where data is scattered across billions of coordinates and millions of papers, **TaarYa** provides the vision to connect them. By leveraging Agentic RAG, it weaves the siloed threads of star catalogs (Gaia, SIMBAD) and scientific literature (ArXiv) into a unified tapestry of knowledge.

Unlike traditional search interfaces that require expert knowledge of SQL or ADQL, **TaarYa** acts as an autonomous research co-pilot. It understands natural language inquiries, executes complex spatial queries (Cone Searches), traverses relational graphs to find hidden connections, and even writes and runs Python code to analyze data on the fly. It transforms petabyte-scale astronomical archives from static repositories into a living, interactive cosmos.

---

## 💡 Overview

Modern astronomy produces petabytes of data, yet much of it remains siloed. Researchers must manually bridge the gap between raw catalogs (Gaia/SIMBAD), theoretical papers (ArXiv), and analysis tools (Python/Astropy).

**TaarYa** breaks these silos. It is an Agentic AI system that doesn't just search data—it *navigates* it. It treats astronomical archives not as static databases, but as an environment to be explored.

Given a complex query like *"Find red giants in globular clusters mentioned in recent papers with transient data,"* TaarYa autonomously:
1.  **Decomposes** the query into a plan.
2.  **Routes** to the right tool (Vector Search, ADQL, or Graph Traversal).
3.  **Synthesizes** a grounded, citable answer.

---

## ⚡️ Key Features

-   **Hybrid Retrieval Engine:** Spatial (Q3C) + Semantic (Qdrant) + Graph (Neo4j) retrieval with **+300% F1 improvement** over single-backend baselines.
-   **Discovery Ranking:** Uncertainty-aware anomaly scoring with SNR penalties, confidence bands, and cross-catalog validation.
-   **Publication-Grade HR Diagrams:** Evolutionary track overlays (ZAMS, RGB, WD, HB) with literature references (Pecaut & Mamajek 2013, Bressan+ 2012).
-   **Cross-Catalog Overlap Analysis:** Pair-wise positional cross-matching with per-catalog uniqueness statistics.
-   **VO Interoperability:** DS9 region export, MESA inlists, SAMP broadcast, Aladin deep links, VOTable/CSV/JSON export.
-   **Full Provenance:** Every exported result carries `X-TaarYa-Session-Id` headers and session manifests for reproducibility.
-   **Interactive Dashboard:** Glassmorphism UI with Chat, Explore, and System Analysis tabs.
-   **Local & Private:** Runs entirely offline using local LLMs (Ollama) and Dockerized databases.

---

## Architecture

The system is built on a modular pipeline:

1.  **Ingestion Engine:** Parses FITS/CSV files and PDFs into structured elements.
2.  **Hybrid Index:**
    -   **Vector Store (Qdrant):** For semantic search of papers.
    -   **Spatial DB (PostgreSQL + Q3C):** For cone-searches on star coordinates.
    -   **Graph DB (Neo4j):** For entity relationships.
3.  **The Agent (LangChain):** The orchestrator that decomposes queries and selects tools.
4.  **Synthesis Layer:** Verifies facts and formats responses with citations.

---

## Tech Stack

-   **LLM Engine:** Ollama (Local `kimi-k2.5:cloud` or similar) / LangChain
-   **Vector Database:** Qdrant (Dockerized)
-   **Spatial Database:** PostgreSQL 15 + Q3C Indexing
-   **Backend:** FastAPI, Python 3.10+
-   **Frontend:** Vanilla JS, TailwindCSS (Glassmorphism UI)
-   **Data Science:** Astropy, Pandas, NumPy

---

## 🚀 Installation & Setup

### Prerequisites
-   **Docker Desktop** (Running) — for Database services.
-   **Python 3.10+** (Recommend using `uv` for package management).
-   **Ollama** — for running the `kimi-k2.5:cloud` LLM locally.

### One-Click Startup (Recommended)

**Windows:**
Double-click `start_taarya.bat` in the project root.

**Linux/Mac:**
Run `./start_taarya.sh` in your terminal.
```bash
chmod +x start_taarya.sh
./start_taarya.sh
```

These scripts will automatically:
1.  Start Docker services (PostgreSQL/Q3C, Qdrant).
2.  Pull the required Ollama model.
3.  Activate the virtual environment.
4.  Launch the TaarYa backend server.

Access the interface at: **http://localhost:8000** 🌟

### Manual Setup
If you prefer manual control:

1.  **Start Services**: `docker compose up -d`
2.  **Ensure Model**: `ollama pull kimi-k2.5:cloud`
3.  **Install Deps**: `uv sync` (or `pip install -r requirements.txt`)
4.  **Run Server**: `uv run python -m src.main`

---

## 🔬 Research & Reproducibility

TaarYa is designed for rigorous scientific use, targeting **ADASS XXXVI** and **Astronomy & Computing**.

### Formal Ablation Study

Run the 4-configuration × 5-region ablation with live backends:
```bash
uv run python eval/ablation_formal.py --publish     # Live (requires backends)
uv run python eval/ablation_formal.py --offline     # Synthetic (no backends)
```

**Latest live results (4 configs × 5 regions):**

| Configuration | P@10 | R@10 | F1@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| Spatial-Only | 0.040 | 0.050 | 0.044 | 0.030 | 0.032 |
| Semantic-Only | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Hybrid (no graph) | 0.160 | 0.200 | 0.178 | 0.201 | 0.200 |
| **Full Hybrid** | **0.160** | **0.200** | **0.178** | **0.201** | **0.200** |

> Full Hybrid: **+300.5% F1@10** and **+575.2% MRR** vs Spatial-Only.

### Discovery Validation

Validate anomaly scoring against known stellar types:
```bash
uv run python eval/validate_discovery.py --offline
```

### Regression Suite

Run the full test + evaluation pipeline:
```bash
uv run python scripts/run_regression.py             # Full (tests + eval)
uv run python scripts/run_regression.py --fast       # Tests only
uv run python scripts/run_regression.py --live       # Include backend tests
```

### Benchmark Queries

50 labeled queries with ground truth across 12 categories in `eval/benchmark_queries.json`.
IR metrics (P@k, R@k, MRR, nDCG, F1) computed via `eval/metrics.py`.

---

## 📥 Data Ingestion

The server **never** runs ingestion automatically on startup. Pipelines are triggered explicitly while the server is running:

```bash
# Ingest Gaia DR3 stellar catalog → PostgreSQL
curl -X POST http://localhost:8000/api/ingest/gaia

# Ingest ArXiv papers → Qdrant
curl -X POST http://localhost:8000/api/ingest/arxiv
```

Or run directly from CLI with full control:

```bash
# Gaia catalog seeding
uv run python -m src.ingestion.seed

# ArXiv corpus expansion (50 queries × 10 thematic categories)
uv run python src/ingestion/arxiv_ingest.py                    # Full (5,000 target)
uv run python src/ingestion/arxiv_ingest.py --max-results 100  # 100 per query
uv run python src/ingestion/arxiv_ingest.py --dry-run          # Preview queries
```

The ArXiv pipeline supports **resumable ingestion** (skips already-indexed papers), batch upserts (100 pts/request), and 10 thematic categories covering Gaia DR3, Star Formation, Open Clusters, Exoplanets, Variable Stars, Stellar Evolution, Galactic Structure, Asteroseismology, Brown Dwarfs, and Stellar Activity.

### Time-Domain Alerts

Ingest transient alerts from TNS and ALeRCE brokers:
```bash
uv run python src/ingestion/alert_ingest.py                    # Both sources
uv run python src/ingestion/alert_ingest.py --source alerce    # ALeRCE only
uv run python src/ingestion/alert_ingest.py --days 30          # Last 30 days
uv run python src/ingestion/alert_ingest.py --dry-run          # Preview
```

### Extended Sky Coverage

Expand beyond the initial 8 clusters to 38 regions (GCs, OB associations, SFRs, moving groups):
```bash
uv run python scripts/expand_sky_coverage.py --dry-run         # Preview regions
uv run python scripts/expand_sky_coverage.py                   # Seed to DB
uv run python scripts/expand_sky_coverage.py --fetch-gaia      # + Gaia TAP fetch
```

Current corpus: **6,464 papers**, **29,798 stars**, **38 sky regions**.

---


## Usage Examples

### Example 1: Semantic + Spatial Query
**User:** *"Show me high metallicity stars in the Orion Nebula region."*

**TaarYa:**
1.  Identifies "Orion Nebula" region (Semantic).
2.  Converts to spatial coordinates (Knowledge Graph).
3.  Executes Q3C Cone Search (Spatial DB).
4.  Filters for "metallicity" (ADQL Query).
5.  Returns a list of stars with coordinates and parameter values.

### Example 2: Multi-Hop Literature Search
**User:** *"Find papers discussing the relationship between star clusters and high redshifts."*

**TaarYa:**
1.  Retrieves papers on "Star Clusters" (Vector Search).
2.  Traverses `CITES` edges in Knowledge Graph to find papers connecting "Redshifts".
3.  Synthesizes a summary citing both sets of papers.

### Example 3: Data Analysis
**User:** *"Plot an HR diagram for the brightest stars in the Pleiades."*

**TaarYa:**
1.  Retrieves the Pleiades cluster data (ADQL).
2.  Generates Python code using `Astropy` to plot Hertzsprung-Russell diagram.
3.  Executes the code in a secure sandbox.
4.  Returns the generated image to the user.

---

## Project Roadmap

-   [x] **Phase 1:** Ingestion Pipeline (Gaia DR3 + ArXiv)
-   [x] **Phase 2:** Knowledge Graph Construction (Neo4j)
-   [x] **Phase 3:** Agentic Core + Hybrid Retrieval Engine
-   [x] **Phase 4:** Web Interface (Interactive Dashboard)
-   [x] **Phase 5:** Scientific Hardening (Ablation, Discovery, Provenance)
-   [x] **Phase 6:** Publication-Ready Evaluation (38 tests, CI/CD)
-   [ ] **Phase 7:** ADASS XXXVI Submission + PyPI Distribution

---

## 🤝 Contributing

This is an academic project. Contributions, bug reports, and feature requests are welcome!

1.  Fork the project.
2.  Create a feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👨 Authors & Acknowledgments

* **[Author]** - [Amit Kumar](https://github.com/HmbleCreator)

Special thanks to the Gaia Collaboration, SIMBAD, and the global open-source AI community for the tools that made this project possible.

---

## 📝 Citing TaarYa

If you use TaarYa in your research, please cite our paper:

```bibtex
@article{kumar2026taarya,
  title={TaarYa: Cross-Catalog Discovery Support for Astronomy with Hybrid Retrieval},
  author={Kumar, Amit and others},
  journal={Astronomy and Computing},
  year={2026},
  url={https://github.com/HmbleCreator/TaarYa}
}
```

