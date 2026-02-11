<div align="center">

# TaarYa 

![Project Status](https://img.shields.io/badge/status-implementation--orange.svg) 
![Python](https://img.shields.io/badge/python-3.9+-blue.svg) 
![License](https://img.shields.io/badge/license-MIT-green.svg)

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

-   **Agentic Autonomy:** An LLM-powered controller that plans multi-step research strategies using tools.
-   **Interactive Dashboard:** A modern, glassmorphism UI with Chat, Explore (Q3C Cone Search), and System Analysis tabs.
-   **Local & Private:** Runs entirely offline using local LLMs (Ollama) and Dockerized databases.
-   **Hybrid Indexing:** Combines Dense Vectors (Semantics), Q3C (Spatial Geometry), and BM25 for maximum retrieval accuracy.
-   **In-Flight Analysis:** capable of generating Python code to analyze data on the fly.
-   **Anti-Hallucination:** Cross-references LLM claims against raw database values.

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

-   [x] **Phase 1:** Ingestion Pipeline (Gaia/SIMBAD)
-   [x] **Phase 2:** Knowledge Graph Construction (Partial)
-   [x] **Phase 3:** Agentic Core Implementation
-   [x] **Phase 4:** Web Interface (Interactive Dashboard)
-   [ ] **Phase 5:** Public Beta Release

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
```
