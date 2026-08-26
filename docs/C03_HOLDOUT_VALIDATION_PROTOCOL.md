# C03 holdout validation protocol

This document preregisters the decision rule for the c03 combined KURE
candidate.  It is a freeze artifact, not a result report.  It must be read
with the four `frozen_manifests/v2_{kure,bm25_reference}_{smoke3,full226}.json`
manifests at the c03 source commit.

## Partition and freeze

- Full-manifest ordinals 1--20 are the development partition.  They may inform
  the already-frozen c03 implementation, but are not holdout quality evidence.
- Full-manifest ordinals 21--40 are the quality-blinded holdout.  Their IDs,
  hops, and execution order are fixed only by the c03 full226 manifest.  The
  c02 session, operational logs, and run-state may be monitored, but before
  the c03 freeze do not inspect c02 answers, statuses, accepted provisions,
  quality scores, evidence, or gold for these ordinals.
- Both holdout runs use the frozen Qwen3.8 Q8 KURE configuration: offline,
  seed 0, three retrieval rounds, nine retrieval requests, and final top 10.
  The c03 `single_issue_fusion_top_k` round-merge mode is part of that frozen
  configuration.  They use separate, fresh output roots.
- BM25 remains a reference-only manifest and must never be executed.  LF-Eval,
  ParSeR execution, speed measurement, latency measurement, and speed or
  latency reporting are excluded.  Any ParSeR comparison uses only an already
  available comparable evaluation record; it does not authorize execution.
- Start the two c03 holdout runs only after the active c02 run no longer
  conflicts.  Operational monitoring of its session/log availability is
  allowed; do not overwrite its live output or inspect its quality results.

## Prespecified acceptance gates

Each c03 run must have zero source or validation errors, zero execution
failures, and 100% citation integrity among answered items.  After both runs,
evaluate with gold only as a post-run metric; gold must never be available to
runtime code, candidate selection, prompts, or branching.

Against the paired c02 run on the same 20 holdout ordinals, c03 must satisfy
all of the following:

- Macro provision F1 and complete-evidence count are each non-decreasing, with
  at least one strictly improved.
- Exact-match count and two-hop provision recall are non-decreasing.
- No c02-complete one-hop or three-hop item becomes incomplete.
- The comparable fixed ParSeR reference remains dominated on provision
  precision, recall, F1, complete-evidence count, and exact-match count.

A strong C5 claim is permitted only when c03 macro provision F1 and
complete-evidence count are each at least the deterministic C5 values, with at
least one strictly improved.  Otherwise no C5 claim is made.

## Repeat stability and promotion

The two c03 holdout runs are randomness-resistant only if their aggregate
macro provision F1 differs by at most 2 percentage points, complete-evidence
and exact-match counts each differ by at most one, and status plus accepted
provision IDs are identical for at least 18 of 20 items.  If any of those
conditions fails, do not label the result randomness-resistant and do not
promote it.

Promote c03 to a full226 run only if every acceptance and repeat-stability gate
passes.  Preserve both holdout records and the post-run evaluator outputs with
the frozen manifest and source hashes.
