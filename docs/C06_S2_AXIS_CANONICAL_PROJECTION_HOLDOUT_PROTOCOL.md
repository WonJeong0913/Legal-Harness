# C06 S2 axis-canonical projection holdout protocol

This is a preregistration and source-freeze artifact for the C06 S2
axis-canonical projection repair.  It precedes all implementation and is not
a quality report.

## Development boundary and disclosed failure evidence

- Development evidence is limited to c03 ordinal 21, `qa_140_1hop_257`, run
  `b8b8daa1-f80a-4ed0-b782-d990551a25d9`.  Both S2 attempts ended in
  `INVALID_SKILL_OUTPUT`; the terminal error reported a conflict between the
  legacy status and coverage axes, an invalid partial kind for E1, and a
  missing-evidence ledger inconsistent with the axes.
- The immutable c03 evidence is pinned as follows: `batch.stderr`
  `7df057ec91137efe86c4cdfc2556f79c75335b929a1efeb8d1abf0aab45bd0ae`,
  `batch.stdout`
  `955eddc7e1325f373a64c1baeb8e40ee0f1076efce068093517eec6e68581e5f`,
  `preflight.stdout`
  `a980ae1d5c9cc5e4fc22e8199210755b348de7377c27410e540ddcbea4c7d866`,
  empty `summary` SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
  question log
  `c7e4ba504d14b99bee08e404f7c48a3935055924cf63f6bc3c38c49987a20d34`,
  result
  `046f4b2e94bb16f7ef0fbd4cc237352c2b406d7e4f55b6bc585c7d96ad092345`,
  skill attempts
  `7fb630f21c36cf8c4d53f07be2d2111a0cf9a1754fb90c7effda9e171589f9c5`,
  and events
  `7242e83abb1cdc24ab8748d1f52a0c3f70b71b50afc4666520f6e459e85ce67b`.
- No gold answer, evaluator decision, per-question score, or post-hoc quality
  field from this disclosed regression may guide implementation.  Unit
  fixtures may model only the disclosed schema/state failure.
- c04 and c05 retain the same S2 legacy-first normalizer and strict
  legacy-versus-axes validator.  Their evidence-role additions and c05 S1
  repair-collision fail-safe do not remove this vulnerability.

## Fixed skill order and semantic authority

Exactly three skills remain in the fixed order **S1 -> S2 -> S3**.  Retrieval
and state transitions are harness operations, not an additional skill.  This
protocol does not authorize a retriever, model, prompt-order, or answer-policy
change.

For each S2 coverage assessment, the model-authored semantic source is the
complete atomic tuple
`legal_status`, `applicability_status`, and `gap_type`, together with the
criterion results and the link/relation/role decisions that establish them.
The validator continues to require valid candidate IDs, accepted CORE link
provenance where coverage is claimed, direct-entailment support, criterion
semantics, and all evidence-role restrictions.  Auxiliary roles remain
audit-only and cannot clear coverage.

The compact model transport will remove assessment-level legacy `status`,
`partial_kind`, and `governing_legal_regime`, plus model-authored
`missing_evidence_items` and `evidence_conflicts` ledgers.  The harness will
derive their public/state projections only after semantic validation.  In
particular, `governing_legal_regime` is a projection of validated
`legal_status` using the frozen legal-regime mapping; it is not newly inferred
from a question or statute.  Links, role choices, criterion results, and the
atomic axes are not repairable presentation fields.

## Closed projection mapping and fail-closed boundary

The canonical mapping is exactly:

| `legal_status` | `applicability_status` | `gap_type` | derived legacy status | derived `partial_kind` |
| --- | --- | --- | --- | --- |
| `covered` | `direct` | `none` | `covered` | `not_applicable` |
| `covered` | `conditional` | `missing_fact` | `partially_covered` | `factual_condition` |
| `partially_covered` | `not_assessed` | `missing_statute` | `partially_covered` | `legal_support_gap` |
| `uncovered` | `not_assessed` | `missing_statute` | `uncovered` | `not_applicable` |
| `conflicting` | `not_assessed` | `conflict` | `conflicting` | `not_applicable` |

`scope_excess` retains its existing non-core boundary meaning.  C06 must
specify and validate its existing permitted tuple explicitly; it must not
silently coerce it to coverage, partial coverage, a factual condition, or a
different gap type.  This is a fail-closed case until its current semantic
contract is represented exactly.

The harness derives the missing ledger from the resulting canonical status:
every assessment other than `covered` appears once, with its validated
criterion-derived missing aspects.  It derives the conflict ledger only for
canonical `conflicting` assessments from validated conflict links.  A derived
projection must not change retrieval results, query history, round count,
request or round budget, coverage meaning, candidate IDs, accepted IDs, or
the CORE/supplemental/qualifying/alternative authorized union.

No repair is allowed for a partial axes tuple, invalid enum, unsupported
tuple, wrong gap type, invalid or incomplete criterion result, invalid link,
non-CORE evidence used for coverage, missing direct-entailment support,
unknown ID, legal-regime semantic error, or any other source/provenance
failure.  Those inputs remain `INVALID_SKILL_OUTPUT`; C06 must not turn a
semantic error into a presentation repair.

For observability, every successful canonicalization emits a
`S2_LEGACY_PROJECTION_DERIVED` event containing the evidence item ID, complete
atomic tuple, derived legacy projection, and whether an omitted or
contradictory legacy transport field was suppressed.  It must contain no gold
data and must not be used by runtime policy to improve a score.

## Required regression and contract gates

Before a holdout is eligible, CPU-only tests must establish all of the
following without a model or retriever invocation:

- a synthetic full matrix covering every listed canonical tuple produces the
  exact legacy status, partial kind, governing-regime projection, and ledgers;
- the disclosed `qa_140`-shaped schema fixture succeeds deterministically on
  at least two independent normalizations, without embedding question text or
  statute IDs;
- partial axes, invalid enums, unsupported tuples, wrong gaps, invalid
  criterion/link/CORE-role/direct-entailment semantics, and legacy-only
  semantic contradictions fail closed;
- the existing c04/c05 evidence-role and citation integrity tests, plus at
  least 91 existing applicable tests, remain green; and
- action traces demonstrate exactly S1 -> S2 -> S3 and show no prohibited
  mutation from projection derivation.

## Quality-blinded preregistered holdout

The full-manifest ordinals 121--140 are preregistered as the new blind
holdout.  Before source freeze and execution, do not inspect their question
text, answers, gold, contexts, accepted state, evaluator output, or existing
per-question quality.  The set is selected only by its fixed ordinal interval,
not by legal topic, error likelihood, or expected outcome.

Run one c05 reference and two fresh c06 repeats on the exact 20 IDs/order,
using KURE with offline Qwen3.8 Q8.  BM25 remains read-only comparison
metadata and must never execute; LF-Eval and ParSeR are forbidden from
execution.  Runtime code, prompts, projection logic, and policies never
receive gold.

Each run must have zero terminal execution/validation/source failures, exact
20-question provenance, and 100% citation integrity among answered items.
Post-run evaluation records citation, core-provision, authorized-role-union,
and token metrics transparently; it must not conceal auxiliary evidence.
The repeat gate records status stability, authorized role-union stability, and
trace/projection-event integrity.  Any comparison with c05 must use only the
same IDs and frozen configuration.  No broader execution is authorized until
all run records, evaluator outputs, trace audit, and manifest/source hashes
are preserved.

## Sequencing

This protocol must be committed before any C06 implementation commit.  It
does not authorize source behavior changes, model execution, GPU use,
retrieval, or opening holdout contents.
