# TaarYa Glossary

Canonical terms. If code, docs and papers disagree with this file, fix the disagreement.

## Workspace domain

| Term | Definition |
|---|---|
| **Workspace** | The interactive research environment spanning projects, catalog queries, visualization, and sessions. |
| **Project** | A named research investigation (`research_projects` table) that groups saved items (`project_items`: stars, papers, searches, regions) and associated `chat_sessions`. |
| **ChatSession** | An individual conversation thread (`chat_sessions` table) between a researcher and the agent, linked optionally to a Project. |
| **ResearchTrace** | The structured JSONB execution log (`chat_messages.tool_trace`) recording what the agent did for a turn: tools called, inputs, raw outputs, execution time, and status. |
| **Provenance bundle** | The `.zip` written by `ResearchProvenanceLogger`: `manifest.json` plus result files. Records versions, models, hosts and query parameters. |

## Data domain

| Term | Definition |
|---|---|
| **Real data** | Rows derived from an archive query (e.g. Gaia DR3) whose `source_id` is a genuine archive identifier. |
| **Synthetic fixture** | Rows invented for software tests. Their `source_id` may exceed 2^63-1 (impossible for Gaia). Must never be mixed into real data or into any reported scientific result. |
| **Source ID** | A Gaia `source_id`. Always handled as an exact integer; never through floating point (float64 corrupts ~99.7% of Gaia-range ids). |
| **Cone** | A region defined by a centre and radius. Seeded stars are those returned by one cone query (members **and** field stars). |
| **Seeding** | Loading a cone's stars into the catalogue. Seeding by itself says nothing about membership. |
| **Member** | A star listed in a *published* membership catalogue (e.g. Hunt & Reffert 2023) with probability at or above a stated threshold. |
| **MEMBER_OF edge** | Graph relation between a Star and a Cluster. Must be created from a published membership list; an edge created because a star fell inside a cone is **not** a membership claim. |
| **Gold / labels** | Ground truth used only for scoring, never visible to the method being evaluated. |
| **Label provenance** | Where labels come from: *independent* (not derived from the features used) or *circular* (derived from them). Circular labels must not be used to score the feature that defines them. |

## Evaluation domain

| Term | Definition |
|---|---|
| **Workflow** | A discovery pipeline implementing the common contract in `taarya_workflows.core`: independent ground truth, a baseline an astronomer could run, a unit of replication, confidence intervals, a claim ceiling. |
| **Baseline** | The strongest realistic non-TaarYa method for the same task (e.g. TOPCAT column filters, plain BLS, a PM/parallax window around known members). A weak baseline is a bug. |
| **Unit of replication** | The independent thing resampled and split: a field, cluster, star (TIC) or paper, never an individual row. |
| **Held-out** | Data not used to fit, tune or choose anything. Splits are by unit of replication. |
| **Leak guard** (`DataVault`) | Protected data that raises an error when read before a prediction is hash-committed. |
| **Commit (prediction)** | A SHA-256 hash of the ephemeris and predicted times, recorded before the held-out data is opened. |
| **Claim ladder** | `NOISE < SIGNAL < CANDIDATE < VETTED_CANDIDATE`. The strongest label the system may emit. Nothing above is automatable; "confirmed" and "discovered" require human follow-up. |
| **Claim gate** (`claim_from_evidence`) | The function that maps evidence to a claim level. Claim level depends on evidence only, never on the user's wording. |
| **Signal** | A statistically significant excess above a threshold calibrated on independent null data. |
| **Candidate** | A Signal that passes the full vetting battery. |
| **Vetted candidate** | A Candidate whose committed, testable prediction on held-out data succeeded. |
| **Untestable** | A prediction with too few independent windows to reach the stated significance. Reported as such, never counted as a pass. |
| **Null calibration** | Choosing a detection threshold on one null set and measuring the false-alarm rate on an independent null set. |
| **Injection-recovery** | Injecting known signals into real or synthetic data and measuring how often the pipeline recovers them (completeness). |
| **Practical threshold** | A pre-declared smallest effect worth caring about (e.g. delta AUC 0.02). A significant effect below it is reported as negligible. |
| **Frozen analysis spec** | The recorded model, cross-validation and bootstrap choices fixed before looking at results. Changes count as a new analysis. |
| **Manifest** | Machine-readable record of an evaluation input: service URL, exact queries, cuts, retrieval date, row counts, truncation flags, file hashes. |

