# Paired Study Harness

The harness separates public task manifests, private relevance labels, system
outputs, and scored reports. It does not fetch benchmark data, operate TOPCAT,
or claim that any system is superior. Current fixtures test software behavior;
they are not research evidence.

## Study Artifacts

The public manifest records the dataset source/release/retrieval time, a local
snapshot path and SHA-256, plus stable scenario IDs, prompts, objectives, data
release, and evidence sources. Snapshot paths must resolve inside the manifest
directory. Keep `labels.private.json` in a separate access-controlled location;
never place labels or label-derived hints in task assignments or system inputs.

Each run record is one participant × scenario × system trial and contains:
`participant_id`, unique `trial_order`, `scenario_id`, `system`, exact system
version/commit, ordered returned IDs, provenance, the dataset hash actually
used, human task time in seconds, and tool latency in seconds. Participant IDs
must be anonymous. Each participant must complete every system for every
scenario; a missing trial invalidates the paired block instead of silently
changing the denominator.

## Preparation and Collection

Create a study manifest and frozen snapshot first. Independently establish each
scenario's relevant IDs from documented sources; use at least two independent
labelers and adjudicate disagreements before scoring. The generator below reads
only the public manifest and emits scenario/system assignments, never labels:

```powershell
python -m eval.prepare_study `
  --study eval/studies/gaia/study.json `
  --participants P001,P002,P003 `
  --systems TaarYa,TOPCAT,PyVO `
  --seed 20261028 `
  --output eval/studies/gaia/assignments.json
```

The seed is required for reproducibility. Scenario order is shuffled per
participant; system order is counterbalanced with a cyclic Latin square. This
reduces order effects but does not eliminate learning/carryover in a crossover.
Record deviations and do not let one participant's outputs become another's
task hints. Record task time from first interaction until the declared objective
is complete; tool latency is measured separately by the system. Preserve failed
tasks and timeouts as outcomes rather than dropping them.

Before recruiting participants, preregister scenarios, exclusions, metrics,
analysis, sample-size rationale, task-time definition, stopping rules, and system
versions. Obtain institutional/ethics approval and informed consent if required
by the institution or jurisdiction. A small pilot is for protocol debugging,
not a superiority claim. The minimum of two participants only makes a bootstrap
interval computable; it is not an adequate powered study by itself.

## Scoring

The report includes precision@k, recall@k, reciprocal rank, nDCG@k, provenance
completeness, dataset match, task time, and tool latency. Per-participant metric
means are resampled for seeded percentile bootstrap intervals; paired differences
are calculated within participants before resampling. With fewer than two
participants, interval endpoints are `null`. These intervals do not replace a
preregistered power analysis or a model appropriate to the study design.

Tool latency is not human task time. A dataset hash mismatch stays visible and
must be investigated before interpreting paired comparisons. TOPCAT, PyVO, and
TaarYa must use the same frozen catalog release and equivalent query scope. A
live archive query is not equivalent to a local snapshot unless the data state is
frozen and recorded. Record versions, settings, query text, result limits,
timeouts, and provenance requirements for every system.

```powershell
python eval/study_harness.py `
  --study eval/studies/gaia/study.json `
  --labels private/gaia/labels.private.json `
  --runs eval/studies/gaia/runs.json `
  --output eval/studies/gaia/report.json `
  --k 10 --seed 20261028
```

Use `eval/templates/` only as an artifact-shape reference. There are
intentionally no real Gaia labels, system runs, or benchmark results in this
repository. The output is limited to measured scenarios and cannot establish
general superiority.
