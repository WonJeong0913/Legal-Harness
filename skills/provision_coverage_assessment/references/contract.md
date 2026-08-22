# S2 contract

## Output

- `evidence_links[]`: smallest operational item-to-candidate links;
- `coverage_assessments[]`: exactly one assessment per evidence item;
- `missing_evidence_items[]`: exactly the non-covered assessments;
- `evidence_conflicts[]`: exactly the conflicting assessments.

Use only supplied evidence, requirement, and short candidate IDs. Every link uses
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
