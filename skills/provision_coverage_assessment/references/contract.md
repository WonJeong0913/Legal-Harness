# S2 contract

## Canonical normalized output

This section describes the post-normalization record used by the canonical validator; the prompt's raw compact transport schema controls model emission.

- `evidence_links[]`: smallest operational item-to-candidate links;
- `coverage_assessments[]`: exactly one assessment per evidence item;
- `missing_evidence_items[]`: exactly the non-covered assessments;
- `evidence_conflicts[]`: exactly the conflicting assessments.

Use only supplied evidence, requirement, and short candidate IDs. After normalization, every link uses
`quoted_text: "[FULL_TEXT]"`; the harness supplies the immutable source text.

## Coverage mapping

| Situation | `legal_status` | `applicability_status` | `gap_type` | Legacy result |
| --- | --- | --- | --- | --- |
| Complete rule and application | `covered` | `direct` | `none` | `covered` |
| Complete rule, selector fact missing | `covered` | `conditional` | `missing_fact` | `partially_covered` / `factual_condition` |
| Some legal requirements unsupported | `partially_covered` | `not_assessed` | `missing_statute` | `partially_covered` / `legal_support_gap` |
| No legal requirement supported | `uncovered` | `not_assessed` | `missing_statute` | `uncovered` |
| Incompatible rules for established facts | `conflicting` | `not_assessed` | `conflict` | `conflicting` |

Alternative rules selected only by a missing fact are conditional, not
conflicting. Reserve `scope_excess` for supplied non-critical context outside the
requested answer; never use it to excuse unsupported critical legal evidence or
to downgrade an otherwise supported requested proposition.

For `covered` + `conditional` + `missing_fact`, cite the provisions that fully
establish the legal rule, put only the affected supplied requirement IDs in
`missing_aspects`, and mark those criterion results `partially_satisfied`, not
`unsatisfied`. This records application uncertainty without inventing a statute
gap.

## Consistency

Emit one `criterion_result` for every supplied completion requirement. Aspect
arrays contain only requirement IDs; prose belongs in `rationale`. A covered or
partial assessment must link supporting candidates, an uncovered assessment must
not, and a conflicting assessment must have a conflict object.

Judge each requirement at its own proposition scope. Do not mark it missing just
because its supporting provision does not independently resolve another
requirement or the final answer. Conversely, do not promote a merely related
provision to support unless its text establishes the supplied proposition.

The harness derives `accepted_provision_ids` and the next action. On invalid input,
use the schema error envelope with `INVALID_INPUT`,
`MISSING_REQUIRED_EVIDENCE`, or `CONTRACT_UNSATISFIABLE`; never emit `ABSTAIN`.

## Direct entailment and audit boundary

For each explicit answer target and supplied completion requirement, use the smallest directly entailing provision set.
A provision belongs in `evidence_links[]` or `linked_provision_ids` only when it is necessary to establish the requirement's proposition.
Audit-only helpful context must remain unlinked: do not create an `evidence_link`, add its ID to `linked_provision_ids`, or count it as satisfied support.
Because this contract has no audit-context output field, do not invent one; leave such candidates among the supplied candidates and, if needed, describe their non-support role concisely in `rationale`.
Related, background, neighboring, procedural, or general rules are not accepted evidence unless they directly entail a supplied requirement.
Do not infer requirements from outside evaluation knowledge; the supplied targets and requirements are the complete assessment scope.

## Deterministic applicability scope

Do not mark a candidate direct or a criterion satisfied when its own text limits the same law to an article range but a directly linked root provision for another evidence item under the same answer target lies outside that range. This includes a no-prefix range bound to the candidate's statute label.
Likewise, do not treat `base(subtype)` text in a candidate as direct or satisfied support for a general base entity unless the supplied question or requirement states that subtype; a parenthetical only in a statute label is not candidate-text scope.

## Compact audit transport

Keep every legal/status decision, criterion requirement ID, criterion linked candidate IDs, chosen support/conflict relation, and one concise rationale for each evidence link, coverage assessment, and criterion result. Omit link IDs, `[FULL_TEXT]`, assessment-level duplicate link/aspect arrays, and duplicate missing/conflict arrays; the harness reconstructs only those deterministic fields before unchanged validation.
