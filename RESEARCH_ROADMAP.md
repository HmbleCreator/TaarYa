# TaarYa Research Roadmap

## Recommended paper angle

Do **not** position this as "an astronomy chatbot with RAG." That story is too generic and hard to defend as research novelty.

The stronger angle is:

**TaarYa as a cross-catalog astronomical discovery support system** that combines:

1. spatial retrieval over sky coordinates,
2. semantic retrieval over astronomy literature,
3. graph-based entity linking, and
4. a discovery-ranking layer that surfaces potentially unusual objects using astrometric, photometric, and cross-catalog signals.

That last part is the real method. The agent and UI should be framed as the interface around the method, not the contribution by themselves.

## What is publishable here

The current codebase already contains a defensible technical core:

- `src/retrieval/discovery.py`: candidate ranking from RUWE, color extremes, proper motion, brightness-distance anomalies, local density, and cross-catalog overlap.
- `src/retrieval/spatial_search.py`: Q3C-backed cone search, 3D projection, region clustering, and catalog-aware retrieval.
- `src/retrieval/hybrid_search.py`: unified orchestration across spatial, vector, and graph backends.

Possible paper title directions:

- `TaarYa: Cross-Catalog Discovery Support for Astronomy with Spatial, Semantic, and Graph Retrieval`
- `A Discovery-Oriented Retrieval Stack for Astronomical Catalog and Literature Exploration`
- `Hybrid Retrieval and Candidate Ranking for Astronomy Research Assistance`

## What is not enough for a paper

These are useful engineering features, but not sufficient novelty by themselves:

- local LLM integration,
- chat UI,
- "RAG for astronomy",
- Dockerized multi-database deployment,
- packaging alone.

Packaging helps reproducibility. It is not the contribution.

## Minimum work needed before submission

### 1. Freeze the scientific question

Choose one main claim:

- `discovery support`: the system surfaces more useful unusual candidates than a plain cone search or single-catalog lookup.
- `research efficiency`: the system reduces time/steps needed to answer astronomy exploration tasks.
- `hybrid retrieval quality`: combined spatial + semantic + graph retrieval outperforms single-backend retrieval on astronomy tasks.

Pick one primary claim and make the others secondary.

### 2. Build an evaluation set

You need a benchmark, even if small:

- 25-50 astronomy task prompts with expected evidence sources.
- A candidate list with manually reviewed "interesting" and "not interesting" objects.
- Named regions and known object classes for controlled retrieval tests.

### 3. Add baselines

At minimum compare against:

- spatial-only retrieval,
- semantic-only paper search,
- graph-disabled hybrid retrieval,
- discovery scoring without cross-catalog overlap bonuses.

### 4. Report metrics

Depending on claim, use:

- retrieval precision@k / recall@k / MRR,
- task success rate,
- steps-to-answer or time-to-answer,
- candidate precision in top-k,
- ablation deltas for each scoring signal.

### 5. Improve reproducibility

Needed before any serious submission:

- one-command install,
- one-command test run,
- versioned config and documented dataset subsets,
- fixed benchmark inputs,
- stable output logging for experiments.

## Package decision

## Short answer

**Yes for reproducibility, no as the main paper story.**

The new `pyproject.toml` gives you a pip-installable package and CLI entry points:

- `taarya-api`
- `taarya-init-db`
- `taarya-seed`
- `taarya-ingest-gaia`
- `taarya-ingest-arxiv`

This makes the project easier to install, cite, and reproduce. That helps both reviewers and future users.

## Longer-term package refactor

If you later want a true reusable research library, extract the method layer under a real package namespace such as `taarya.discovery` instead of the current internal `src.*` imports. That is worth doing only after the benchmark and paper story are stable.

## Best venue strategy as of 2026-04-15

### Best journal target

**Astronomy and Computing** is the best fit if you want a proper paper on astronomical software and methods.

Why it fits:

- official scope explicitly covers astronomy plus computer science/software,
- it accepts work on astronomical computing, software, visualization, and reports on practice,
- submission is journal-style rather than tied to a single conference deadline.

Official pages:

- https://www.sciencedirect.com/journal/astronomy-and-computing
- https://www.sciencedirect.com/journal/astronomy-and-computing/about/insights

### Best conference target

**ADASS XXXVI** is the best near-term conference fit for a systems/software paper.

Official ADASS site lists:

- conference: `ADASS XXXVI`
- location: `Perth, Australia`
- dates: `November 1-5, 2026`

Official pages:

- https://adass.org/
- https://www.adass.org/futureven.html

As of `2026-04-15`, I did **not** find an official abstract deadline posted yet. Watch the ADASS site rather than assuming last year's timing.

### Software-paper option later

**JOSS** is viable later if you want a software publication, but only after the repository meets their requirements.

Important JOSS requirements from the official docs include:

- open-source software,
- public development workflow,
- packaging and tests,
- obvious research application,
- at least **six months of public history** before submission,
- demonstrated research impact.

Official page:

- https://joss.readthedocs.io/en/latest/submitting.html

Based on the local git history in this repo, development currently appears to start in **February 2026**, so JOSS is probably **not ready yet** unless there is earlier public history elsewhere.

## Suggested submission sequence

1. Submit a conference/demo/proceedings version to `ADASS XXXVI` if your benchmark is ready in time.
2. Expand it into a fuller journal paper for `Astronomy and Computing`.
3. Submit a software-focused version to `JOSS` later, after the public-history requirement is satisfied.

## Immediate next milestones

1. Define one primary experimental claim.
2. Create a benchmark dataset folder with fixed tasks and labels.
3. Add an evaluation script that runs ablations and writes metrics.
4. Clean up documentation around installation and experiment reproduction.
5. Draft the paper around the discovery-ranking method, not the chatbot framing.
