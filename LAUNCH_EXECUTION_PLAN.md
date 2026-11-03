# TaarYa Launch Execution Plan

> Updated 2026-04-21 after completing all execution phases. All milestones verified.
> Scientific hardening complete — ready for ADASS XXXVI / A&C submission.

---

## Vision

TaarYa is a **cross-catalog astronomical discovery support system**, not a chatbot with RAG.
Every feature, endpoint, and workflow exists to help a researcher answer:

> "What is unusual in this part of the sky, and what does the literature say about it?"

The system must be defensible at **ADASS XXXVI** and **Astronomy and Computing**.

---

## Completed Phases (All Verified)

### Three-Day Launch ✅

All 6 launch-readiness criteria met. Server boots cleanly, isolated modules import without backends, `taarya-readiness` passes 5/5 checks.

### Week 1 — Reliability Closure ✅

All call-signature bugs fixed. 6/6 eval scripts pass. 7/7 unit tests pass. Deployment manifests corrected.

### Week 2 — Scientific & Graph Expansion ✅

200+ star NER, local coordinate resolver, `find_star_by_name`, provenance bundle export.

### Weeks 3-4 — Advanced Workflow Integrations ✅

MESA HR-diagram estimation, cluster inlists, CASA helper, physical params API.

### Month 2 — Regression & Entry Points ✅

Automated regression harness, verified pip entry points.

---

## Current Execution: Scientific Tool Excellence

### Phase A: Evaluation Infrastructure ✅

**Goal:** Make every scientific claim in the paper defensible with numbers.

#### A1. Ground-Truth Labeled Benchmark ✅

**File:** `eval/benchmark_queries.json` — 50 queries with ground truth

Completed:
- 50 labeled queries (Q01–Q50) across 12 categories
- `ground_truth_source_ids`, `expected_anomaly_types`, `expected_paper_keywords` fields
- IR metrics scoring via `eval/metrics.py` (precision@k, recall@k, MRR, nDCG, F1)
- Full unit test coverage (18/18 tests passing)

#### A2. Formal Ablation Study ✅

**File:** `eval/ablation_formal.py`

Completed:
- 4 configurations × 5 sky regions
- Metrics: precision@10, recall@10, F1@10, MRR, nDCG@10
- Full Hybrid F1@10 vs Spatial-Only: +24.4% improvement
- Offline run completed; LaTeX table generated (`eval/ablation_table.tex`)
- Results: `eval/ablation_results.json`

#### A3. Discovery Precision Validation ✅

**File:** `eval/validate_discovery.py`

Completed:
- 6 anomaly types × 5 validation regions
- Overall discovery precision: 0.387 (offline synthetic)
- Results: `eval/discovery_validation.json`
- Live validation available via `--top-k` and SIMBAD cross-check

---

### Phase B: Provenance & Reproducibility ✅

**Goal:** Every result can be traced to exact parameters, code version, and data.

#### B1. Wire Provenance into Scientific API ✅

**Files:** `src/api/scientific.py`, `src/utils/research_logger.py`

Completed:
- Request-scoped provenance logger injected into each export endpoint
- Every endpoint writes: endpoint, parameters, result count, timestamp, session_id
- `X-TaarYa-Session-Id` response header on all export responses
- Provenance metadata embedded in VOTable/JSON/TOPCAT export templates

#### B2. Versioned Benchmark Data ✅

**File:** `data/benchmark/` (new directory)

Completed:
- Seeded region snapshots documented with exact row counts and column checksums
- `eval/benchmark_corpus_info.json` pins corpus version

---

### Phase C: Paper-Ready Scientific Capabilities (Partially Complete)

**Goal:** Add the capabilities that differentiate TaarYa from a generic cone search tool.

#### C1. Uncertainty-Aware Discovery Scoring ✅

**File:** `src/retrieval/discovery.py`

Completed:
- Parallax SNR penalty: candidates with $\parallax/\sigma_\parallax < 5$ receive a `low_parallax_snr` flag and are downweighted
- Confidence field added to each discovery candidate (`high` / `medium` / `low`)
- Uncertainty propagation formula ($\sigma_{M_G}$) documented in paper

#### C2. Interactive HR Diagram with Evolutionary Track Overlays ✅

**File:** `src/utils/hr_diagram.py`, `src/api/scientific.py`

Completed:
- Publication-grade fiducial sequences: ZAMS (Pecaut & Mamajek 2013), RGB (PARSEC/Bressan+ 2012), WD cooling (Bergeron+ 2011), Horizontal Branch (Catelan+ 2009)
- Plotly trace generator (`format_evolutionary_tracks_for_plotly()`)
- HR diagram API returns: star scatter + track overlays + inverted y-axis layout + track metadata with literature references

#### C3. Cross-Catalog Overlap Analysis ✅

**Endpoint:** `GET /api/catalog/overlap`

Completed:
- Per-catalog star counts in a sky region
- Pair-wise positional cross-match with configurable match radius
- Unique-per-catalog counts (sources without counterpart in any other catalog)
- Multi-catalog detection rate
- Provenance logging integrated

---

### Phase D: CI/CD and Distribution

**Goal:** Automated quality gates.

#### D1. GitHub Actions CI ✅

**File:** `.github/workflows/regression.yml`

Completed:
- 2-tier pipeline: `unit-tests` → `eval-offline`
- Triggers on push/PR to main
- Uploads test results and evaluation artifacts
- Verifies ablation output integrity
- Local runner: `scripts/run_regression.py` (--fast, --live flags)

#### D2. PyPI Distribution ⏳

Tasks:
- Clean up `pyproject.toml` metadata
- Add `CHANGELOG.md`
- Test `pip install` in clean venv
- Publish to PyPI after ADASS submission

---

## Execution Priority

```
Priority 1 (This Week):     A1 → A2 → A3             [Evaluation infrastructure]
Priority 2 (Next Week):   B1 ✅ B2 ✅ C1 ✅           [Provenance ✅ + uncertainty ✅ COMPLETE]
Priority 3 (Week After):   C2 → C3                    [Publication figures]
Priority 4 (Before ADASS): D1 → D2                    [CI + distribution]
```

| # | Item | Category | Effort |
|---|---|---|---|
| 1 | **Reproducible evaluation corpus** | Evaluation | ✅ 50 queries with ground truth (Q01–Q50) |
| 2 | **Formal ablation study** — 4 configs, P@10/R@10/MRR/nDCG | Evaluation | ✅ +24.4% F1 improvement demonstrated |
| 3 | **External expert-catalog validation** — SIMBAD cross-match | Scientific | ✅ Framework running (offline + online modes) |
| 4 | **Freeze primary experimental claim** | Paper | Low — data ready |
| 5 | **Broader sky coverage** | Data | ✅ 8 clusters seeded |
| 6 | **Provenance capture wired into all export endpoints** | Traceability | ✅ Done |
| 7 | **Expanded semantic paper corpus** | Data | Medium |
| 8 | **CI/CD pipeline** — GitHub Actions YAML | DevOps | ✅ Done |
| 9 | **Time-domain alert ingestion** | Ingestion | Medium |
| 10 | **Multi-wavelength cross-match** | Scientific | ✅ /catalog/overlap endpoint |

---

## Three-Day Cutline (Historical — Completed)

The following items were part of the long-term full app target, but they must not block the three-day launch window if incomplete:

- full LLM-based named entity recognition *(deferred — deterministic NER in production)*
- unsupported benchmark prompt families *(35 queries now in place)*
- full external SIMBAD/VizieR availability in offline deployments *(graceful fallback working)*
- broad-sky ingestion beyond the seeded launch dataset *(still 3 regions)*
- advanced time-domain ingestion beyond already implemented alert paths *(deferred)*
- production-grade CASA-native cross-matching logic inside CASA itself *(helper working)*
- full MESA physical parameter inference beyond export of a validated starter inlist *(HR-diagram estimation now working)*

---

## Risks

### Missing baselines before submission

Risk:
Without formal ablation numbers, ADASS/A&C reviewers will reject the contribution claim.

Mitigation:
- Phase A is the highest priority
- Ablation framework exists (`eval/ablation.py`); needs formal extension
- Ground-truth labels are the blocking dependency

### Evaluation corpus too small

Risk:
1,475 papers and 3 seeded regions may not be enough for robust retrieval evaluation.

Mitigation:
- Expand paper corpus with targeted arXiv ingestion
- Add 2-3 additional seeded regions (Coma Ber, Praesepe, NGC 2516)
- Document corpus limitations honestly in paper

### Environment fragility

Risk:
The current local Python environment already shows permission and binary-loading issues.

Mitigation:
- avoid eager imports *(done)*
- keep validation commands narrow and diagnostic *(done)*
- use first-party readiness scripts instead of assuming global pytest health *(done)*

---

## Definition of Scientific Tool Ready

TaarYa is ready for publication when all of the following are true:

1. **Evaluation:** Formal ablation shows hybrid retrieval improvement over single-backend baselines with precision@k and MRR metrics.
2. **Discovery:** Discovery precision against expert catalogs is reported as a quantitative metric.
3. **Reproducibility:** Every result can be reproduced with one command from a versioned data snapshot.
4. **Provenance:** Every exported file contains metadata tracing it to exact parameters and session.
5. **Interoperability:** DS9, MESA, CASA, Aladin, and SAMP workflows function end-to-end or fail gracefully with explicit diagnostics.
6. **Readiness:** `taarya-readiness` passes all checks on the deployment environment.
7. **Figures:** Paper figures (HR diagram, ablation table, discovery precision) can be generated programmatically.
