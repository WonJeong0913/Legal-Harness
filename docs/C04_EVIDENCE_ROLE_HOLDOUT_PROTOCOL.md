# C04 evidence-role holdout protocol

This is a preregistration and source-freeze artifact for the c04 evidence-role
runtime candidate. It is not a quality report.

## Development boundary and quality blinding

- Development and diagnostic work may use only c02 ordinals 1--40.
- The fixed quality-blinded holdout is full-manifest ordinals 81--100. Their
  IDs, hops, and order remain fixed by the frozen full manifest.
- Before the c04 source freeze, do not inspect c02, c03, or c04 answer,
  status, accepted-provision, evidence, quality, or gold-based results for
  ordinals 81--100. Operational run/session state and log availability may be
  monitored without inspecting those quality fields.
- Run the frozen c04 holdout twice, each time with a separate fresh output
  root. Gold is post-run evaluation input only and must never reach runtime
  code, prompts, candidate selection, or branching.

## Required acceptance gates

Each run must have zero source or validation errors, zero execution failures,
and 100% citation integrity among answered items. Against c02 on the same
20-item holdout, c04 must have non-decreasing core macro provision F1,
core-complete-evidence count, core exact-match count, and two-hop core recall;
macro F1 or complete-evidence count must improve strictly. No c02-complete core
case may become incomplete.

The anti-gaming audit is mandatory: it must find zero public conclusions
supported only by supplemental, qualifying, or alternative evidence; zero
auxiliary provisions counted as core coverage or criterion support; and exact
consistency between every accepted-provision role list, the candidate set, and
the authorized union. The comparable fixed ParSeR reference must remain
dominated on same-block F1 and complete-evidence count; this comparison does
not authorize ParSeR execution.

Auxiliary role/status stability must be identical for at least 18 of 20 items
across the two c04 runs. Their aggregate macro F1 may differ by at most 2
percentage points, and complete-evidence and exact-match counts may each differ
by at most one. Any failed stability or anti-gaming gate prevents promotion.

## Claims and promotion

A strong C5 claim is permitted only if c04 F1 and complete-evidence count are
each at least deterministic C5 on the comparable block, with at least one
strictly improved. Otherwise no strong C5 claim is made.

Promote to a broader c04 run only if every quality, citation, anti-gaming,
ParSeR-comparison, and repeat-stability gate passes. Preserve both fresh run
records, role audits, and post-run evaluator outputs with the frozen source and
manifest hashes.
