# S1 contract

## `INITIAL_PLAN`

Return:

- `answer_targets[]`: only results explicitly requested by the question;
- `legal_issues[]`: legal decision questions needed for those targets;
- `required_evidence_items[]`: independently necessary evidence obligations;
- `retrieval_requests[]`: issue- and evidence-linked searches.

Each critical evidence item must link to an answer target, state why it is
necessary, and contain the minimum independently checkable completion
requirements needed for the requested legal conclusion. A question fact is not
statutory evidence and must not become a completion requirement.

Compactness applies to prose, not coverage. Do not create one requirement per
expected provision: one provision may satisfy several requirements, and one
requirement may need several provisions. Keep distinct outcome-determinative
rules, exceptions, cross-references, and legal effects searchable. Definitions,
background, procedure, and generic completeness are `supporting_context` unless
explicitly requested or outcome-changing. Every critical item needs at least one
retrieval request.

## `GAP_QUERY_PLAN`

Return only new requests for supplied unresolved statute evidence. Preserve the
evidence item's answer-target scope, center each request on an unsatisfied atomic
completion requirement, vary a material legal relation rather than paraphrasing
`query_history`, and respect `remaining_request_budget`. A missing question fact
is not a search target.

## Retrieval query fields

- `query_text`: the backward-compatible focused query.
- `query_terms`: 2-6 unique exact legal nouns or phrases.
- `statute_hints`: tentative statute or article names supported by the question.
- `first_stage_query_text`: optional broad first-stage wording.
- `rerank_query_text`: optional answer target plus one atomic requirement for BGE.

Keep each field focused on its linked legal proposition. Do not copy the whole
question, necessity reason, or rationale into multiple query fields.

The experiment harness, not this skill, fixes which field the configured
retriever consumes. Do not change that field precedence inside a skill-only
ablation.

Use only the allowed query channels. A hint is not retrieved evidence.

## Integrity

Use schema-valid `T`, `I`, `E`, requirement, and request IDs. Keep all references
internal to the result, every request linked to an existing issue/evidence pair,
and all normalized queries and terms unique. The harness may canonicalize
transport IDs without changing the plan.

On invalid input, use the schema error envelope with `INVALID_INPUT`,
`BUDGET_EXHAUSTED`, or `CONTRACT_UNSATISFIABLE`. An S1 error is not a policy
action.

## Epistemic neutrality

Describe the statutory evidence needed to determine each explicit result while separating evidence obligations from retrieval hypotheses. Do not present a legal answer, article, paragraph, condition, deadline, threshold, or extra legal theory absent from the question as established fact; a court, agency, actor, or procedure name alone is not a statute hint. Split only explicit independent requested outputs or genuinely distinct outcome-determinative rules, exceptions, cross-references, or effects. In GAP planning, a candidate cross-reference proves provenance, not relevance, for a numeric pinpoint. Use that pinpoint only when its supplied excerpt matches every material component stated in the unresolved completion requirement, including subject/actor, act, trigger/qualifier, and legal effect as applicable. A partial component overlap is insufficient; do not promote a literal range that excludes the requirement's relevant root. Otherwise query the unresolved statutory proposition neutrally. Preserve a supplied cross-reference pinpoint when that direct match is present. Candidate anchors identify the target statute and article (and paragraph where applicable), are extracted only from outbound provision-text references, and retain source candidate IDs with exact excerpts and spans.
