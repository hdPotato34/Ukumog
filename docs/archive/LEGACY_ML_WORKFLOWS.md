# Legacy ML Workflows

This note archives ML workflows that are no longer the primary documented path, while preserving them for baseline comparison and checkpoint compatibility.

## Still Supported For Compatibility

These assets and code paths remain intentionally usable:

* legacy policy/value checkpoints in `checkpoints/`
* `phase7_baseline.pt` as the current baseline comparison model
* legacy checkpoint loading through `TorchPolicyValueEvaluator`
* quiet-value dataset generation and training through:
  * `python -m ukumog_engine.ml.generate_data`
  * `python -m ukumog_engine.ml.train`

## No Longer The Primary Workflow

These are archived from the main README and day-to-day guidance:

* old phase7 policy-first training as the main development direction
* quiet-value as the default recommended runtime model
* deterministic repeated batches from `Position.initial()` as the main strength benchmark
* append-heavy quiet-value datasets as the primary active training corpus

## Current Recommended Path

The active ML direction is now:

1. build `root_policy_v1` data with `python -m ukumog_engine.ml.generate_root_policy_data`
2. train with `python -m ukumog_engine.ml.train_root_policy`
3. evaluate with `python tools/ml_match_suite.py`

## Near-Term ML Stance

Even within the active ML direction, ML is currently a follow-up priority rather than the immediate next engine task.

Current recommended sequencing:

1. stabilize search and q-search behavior first
2. re-run root-policy experiments only after the search baseline stops moving
3. keep quiet-value and heavier evaluator ideas archived until search is no longer the main limiter

Practical reading:

* root-policy remains the only ML path that still fits the repo's search-first direction cleanly
* learned evaluation should not be the next major project while tactical-chain search remains the dominant hotspot

## Why These Legacy Assets Stay

They remain useful for:

* baseline-vs-new-model testing
* reproducing older experiments
* ensuring client/runtime compatibility with already-produced checkpoints
* regression comparisons when a new model appears stronger
