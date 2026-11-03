import json
import unittest
from pathlib import Path

from harness.contracts import (
    AnswerMode,
    AnswerTarget,
    ApplicabilityStatus,
    CandidateProvision,
    CompletionRequirement,
    CoverageAssessment,
    CoverageStatus,
    CriterionResult,
    CriterionStatus,
    EvidenceLink,
    GapType,
    LegalIssue,
    LegalStatus,
    RequiredEvidenceItem,
    SupportSpan,
)
from harness.run_state import RunState
from harness.runner import HarnessRunner
from runtime.local_ollama_executor import (
    S2_COMPACT_AUDIT_INVARIANT,
    S3_COMPACT_TRANSPORT_INVARIANT,
    LocalOllamaSkillExecutor,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CompactSkillTransportTests(unittest.TestCase):
    def _state(self):
        state = RunState(
            question="손해배상 책임은 무엇인가?",
            normalized_question="손해배상 책임은 무엇인가?",
            run_id="run-compact",
        )
        state.legal_issues = [LegalIssue("I1", "손해배상 책임")]
        state.answer_targets = [
            AnswerTarget("T1", "손해배상 책임은 무엇인가?", "책임 근거", "legal_rule")
        ]
        state.required_evidence_items = [
            RequiredEvidenceItem(
                "E1",
                "I1",
                "rule",
                "손해배상 책임 조문",
                True,
                completion_criteria="책임 근거 조문",
                answer_target_ids=["T1"],
                completion_requirements=[
                    CompletionRequirement("E1-R1", "책임 근거 조문")
                ],
            )
        ]
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="P1",
                statute_name="예시법 제1조",
                provision_text="고의 또는 과실로 타인에게 손해를 입힌 자는 배상한다.",
                issue_id="I1",
                source_request_id="RQ1",
                retrieval_round=1,
                first_stage_score=0.9,
                fusion_rank=1,
                rerank_score=0.8,
                target_evidence_item_ids=["E1"],
            )
        ]
        state.coverage_assessments = [
            CoverageAssessment(
                evidence_item_id="E1",
                status=CoverageStatus.COVERED,
                linked_provision_ids=["P1"],
                rationale="예시법 제1조가 책임 근거를 직접 규정한다.",
                legal_status=LegalStatus.COVERED,
                applicability_status=ApplicabilityStatus.DIRECT,
                gap_type=GapType.NONE,
                criterion_results=[
                    CriterionResult(
                        requirement_id="E1-R1",
                        status=CriterionStatus.SATISFIED,
                        linked_provision_ids=["P1"],
                        rationale="책임 근거가 명시되어 있다.",
                    )
                ],
            )
        ]
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P1", [SupportSpan(0, 10)])
        ]
        state.accepted_provision_ids = {"P1"}
        state.answer_mode = AnswerMode.FULL
        state.answered_target_ids = ["T1"]
        return state

    def test_runner_omits_replay_only_audit_prose_but_preserves_decisions(self):
        runner = HarnessRunner(None, None, None)
        state = self._state()

        coverage_payload = runner._coverage_payload(state)
        prior = coverage_payload["prior_coverage_assessments"][0]
        self.assertEqual(
            coverage_payload["candidate_provisions"],
            [
                {
                    "provision_id": "P1",
                    "statute_name": "예시법 제1조",
                    "provision_text": "고의 또는 과실로 타인에게 손해를 입힌 자는 배상한다.",
                }
            ],
        )
        self.assertNotIn("rerank_score", coverage_payload["candidate_provisions"][0])
        self.assertEqual(prior["evidence_item_id"], "E1")
        self.assertEqual(prior["status"], "covered")
        self.assertEqual(prior["linked_provision_ids"], ["P1"])
        self.assertEqual(
            prior["criterion_results"],
            [
                {
                    "requirement_id": "E1-R1",
                    "status": "satisfied",
                    "linked_provision_ids": ["P1"],
                }
            ],
        )
        self.assertNotIn("rationale", prior)
        self.assertNotIn("rationale", prior["criterion_results"][0])

        gap_payload = runner._gap_payload(state)
        self.assertNotIn("rationale", gap_payload["coverage_assessments"][0])
        self.assertEqual(
            gap_payload["coverage_assessments"][0]["criterion_results"][0]["status"],
            "satisfied",
        )

        answer_payload = runner._answer_payload(state)
        answer_coverage = answer_payload["coverage_assessments"][0]
        self.assertEqual(answer_coverage["status"], "covered")
        self.assertEqual(answer_coverage["legal_status"], "covered")
        self.assertNotIn("rationale", answer_coverage)
        self.assertEqual(answer_coverage["linked_provision_ids"], ["P1"])
        self.assertEqual(
            answer_coverage["criterion_results"][0]["status"], "satisfied"
        )
        self.assertNotIn("rationale", answer_coverage["criterion_results"][0])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", generator=lambda prompt: "{}"
        )
        s2_input = executor._build_skill_input(
            "provision_coverage_assessment", "ASSESS_COVERAGE", coverage_payload
        )
        self.assertNotIn("retrieval_metadata", s2_input["candidate_provisions"][0])
        self.assertEqual(
            state.coverage_assessments[0].rationale,
            "예시법 제1조가 책임 근거를 직접 규정한다.",
        )

    def test_compact_claim_transport_is_normalized_before_unchanged_validation(self):
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", generator=lambda prompt: "{}"
        )
        payload = {
            "run_id": "run-compact",
            "normalized_question": "손해배상 책임은 무엇인가?",
            "legal_issues": [{"issue_id": "I1", "description": "손해배상 책임"}],
            "answer_targets": [
                {
                    "answer_target_id": "T1",
                    "question_anchor": "손해배상 책임은 무엇인가?",
                    "requested_output": "책임 근거",
                    "answer_type": "legal_rule",
                }
            ],
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "evidence_type": "rule",
                    "description": "손해배상 책임 조문",
                    "critical": True,
                    "completion_criteria": "책임 근거 조문",
                    "answer_target_ids": ["T1"],
                }
            ],
            "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered"}],
            "accepted_provisions": [
                {
                    "provision_id": "P1",
                    "statute_name": "예시법 제1조",
                    "provision_text": "고의 또는 과실로 타인에게 손해를 입힌 자는 배상한다.",
                    "supported_evidence_item_ids": ["E1"],
                }
            ],
            "answer_mode": "full",
            "answered_target_ids": ["T1"],
            "deferred_target_ids": [],
            "state_version": 1,
        }
        skill_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", payload
        )
        compact_raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "model-owned",
            "claims": [
                {
                    "claim_id": "temporary",
                    "text": "손해를 배상해야 합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "direct",
                    "answer_target_ids": ["T1"],
                    "citation_required": True,
                    "public_role": "conclusion",
                }
            ],
            "claim_citations": [
                {
                    "claim_id": "temporary",
                    "provision_id": "P1",
                    "support_description": "배상 의무를 정한다.",
                }
            ],
            "assumptions": [],
            "limitations": [],
        }

        normalized = executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            compact_raw,
        )

        self.assertEqual(executor._validators["grounded_legal_answer_generation"](normalized, skill_input), [])
        self.assertEqual(normalized["answer"], "손해를 배상해야 합니다.[CT1]")
        self.assertEqual(normalized["claim_citations"][0]["citation_id"], "CT1")
        self.assertEqual(normalized["claim_citations"][0]["answer_marker"], "[CT1]")
        self.assertEqual(
            normalized["claim_citations"][0]["quoted_text"],
            "고의 또는 과실로 타인에게 손해를 입힌 자는 배상한다.",
        )
        executor.generator = lambda prompt: json.dumps(compact_raw, ensure_ascii=False)
        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", payload
        )
        self.assertEqual(result["answer"], "손해를 배상해야 합니다.[CT1]")
        self.assertEqual(
            result["claim_citations"][0]["quoted_text"],
            "고의 또는 과실로 타인에게 손해를 입힌 자는 배상한다.",
        )
        prompt = executor._prompt(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", skill_input, ""
        )
        self.assertIn(S3_COMPACT_TRANSPORT_INVARIANT, prompt)

    def test_s2_prompt_and_contract_require_compact_audit_prose(self):
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", generator=lambda prompt: "{}"
        )
        state = self._state()
        skill_input = executor._build_skill_input(
            "provision_coverage_assessment",
            "ASSESS_COVERAGE",
            HarnessRunner(None, None, None)._coverage_payload(state),
        )
        prompt = executor._prompt(
            "provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, ""
        )
        contract = (
            PROJECT_ROOT
            / "skills"
            / "provision_coverage_assessment"
            / "references"
            / "contract.md"
        ).read_text(encoding="utf-8")
        self.assertIn(S2_COMPACT_AUDIT_INVARIANT, prompt)
        self.assertIn("## Compact audit transport", contract)


    def test_gap_provenance_uses_outbound_and_relative_references_not_heading(self):
        state = self._state()
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="형법 334조 2항#sample",
                statute_name="형법 334조 2항",
                provision_text="제334조 제2항 전조의 죄 및 전항의 경우에는 전 2조를 적용한다. 「형법」 제329조부터 제331조까지를 따른다. 제333조에 따른다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            ),
            CandidateProvision(
                provision_id="특별법 10조#sample",
                statute_name="특별법 제10조",
                provision_text="제10조 「형법」 제329조에 따른다. 제333조에 따른다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=2, rerank_score=1.0,
            ),
            CandidateProvision(
                provision_id="형법 335조#invalid-ranges",
                statute_name="형법 제335조",
                provision_text="제335조 「형법」 제400조부터 제420조까지, 「형법」 제350조부터 제349조까지, 「형법」 제340조부터 제X조까지를 언급한다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=3, rerank_score=1.0,
            ),
        ]
        references = HarnessRunner._candidate_cross_references(state)
        pairs = {(item["target_statute_name"], item["target_article"], item.get("target_paragraph")) for item in references}
        self.assertTrue({
            ("형법", "제333조", None),
            ("형법", "제334조", "제1항"),
            ("형법", "제332조", None),
            ("형법", "제329조", None),
            ("형법", "제330조", None),
            ("형법", "제331조", None),
            ("특별법", "제333조", None),
        }.issubset(pairs))
        self.assertNotIn(("형법", "제334조", None), pairs)
        self.assertNotIn(("특별법", "제10조", None), pairs)
        self.assertFalse(any(article in {"제400조", "제350조", "제340조"} for _, article, _ in pairs))
        relative = next(item for item in references if item["target_statute_name"] == "형법" and item["target_article"] == "제333조" and item["excerpt"] == "전조")
        self.assertEqual(relative["source_candidate_id"], "형법 334조 2항#sample")
        self.assertLess(relative["start_char"], relative["end_char"])
        cross_law = next(item for item in references if item["source_candidate_id"] == "특별법 10조#sample" and item["target_statute_name"] == "형법")
        self.assertEqual(cross_law["target_article"], "제329조")

    def test_outbound_statute_suffix_and_same_statute_range_are_precise(self):
        state = self._state()
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="민법 500조#suffix-range",
                statute_name="민법 500조",
                provision_text=(
                    "이 경우 형법 제333조에 따르고 제329조부터 제331조까지를 "
                    "함께 본다. 제400조부터 제420조까지와 제350조부터 제349조까지는 제외한다."
                ),
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            )
        ]
        references = HarnessRunner._candidate_cross_references(state)
        pairs = {
            (item["target_statute_name"], item["target_article"], item.get("target_paragraph"))
            for item in references
        }
        self.assertIn(("형법", "제333조", None), pairs)
        self.assertTrue({
            ("민법", "제329조", None),
            ("민법", "제330조", None),
            ("민법", "제331조", None),
        }.issubset(pairs))
        self.assertFalse(any(
            statute == "민법" and article in {"제400조", "제420조", "제350조", "제349조"}
            for statute, article, _ in pairs
        ))

    def test_compound_subordinate_statute_is_preserved_as_target(self):
        state = self._state()
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="민법 500조#compound-target",
                statute_name="민법 500조",
                provision_text="관련 의로기기법 시행규칙 제48조 제2항을 따른다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            )
        ]
        pairs = {
            (item["target_statute_name"], item["target_article"], item.get("target_paragraph"))
            for item in HarnessRunner._candidate_cross_references(state)
        }
        self.assertIn(("의로기기법 시행규칙", "제48조", "제2항"), pairs)

    def test_range_is_skipped_when_earlier_references_leave_no_room_for_all_members(self):
        state = self._state()
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="민법 500조#atomic-range",
                statute_name="민법 500조",
                provision_text="관련 규정상 제1조 및 제2조와 제100조부터 제111조까지를 본다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            ),
            CandidateProvision(
                provision_id="민법 501조#atomic-qualified-range",
                statute_name="민법 501조",
                provision_text="이 경우 형법 제1조, 형법 제2조 및 형법 제100조부터 제111조까지를 본다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=2, rerank_score=1.0,
            ),
        ]
        references = HarnessRunner._candidate_cross_references(state)
        by_candidate = {}
        for item in references:
            by_candidate.setdefault(item["source_candidate_id"], set()).add(
                (item["target_statute_name"], item["target_article"])
            )
        self.assertEqual(
            by_candidate["민법 500조#atomic-range"],
            {("민법", "제1조"), ("민법", "제2조")},
        )
        self.assertEqual(
            by_candidate["민법 501조#atomic-qualified-range"],
            {("형법", "제1조"), ("형법", "제2조")},
        )

    def test_metadata_only_relative_references_use_real_koblex_shape(self):
        state = self._state()
        state.candidate_provisions = [
            CandidateProvision(
                provision_id="형법 334조  특수강도#KOBLEX-193377",
                statute_name="형법 334조  특수강도 2항",
                provision_text="②흉기를 휴대하거나 2인 이상이 합동하여 전조의 죄를 범한 자도 전항의 형과 같다.",
                issue_id="I1", source_request_id="RQ1", retrieval_round=2,
                first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            )
        ]
        references = HarnessRunner._candidate_cross_references(state)
        pairs = {(item["target_statute_name"], item["target_article"], item.get("target_paragraph")) for item in references}
        self.assertIn(("형법", "제333조", None), pairs)
        self.assertIn(("형법", "제334조", "제1항"), pairs)
        self.assertNotIn(("형법", "제334조", "제2항"), pairs)
        self.assertEqual({item["target_statute_name"] for item in references}, {"형법"})
        subarticle_state = self._state()
        subarticle_state.candidate_provisions = [CandidateProvision(
            provision_id="형법 227조 2 공전자기록등불실기재#sample",
            statute_name="형법 227조 2 공전자기록등불실기재",
            provision_text="제227조의2 제2항 전항의 죄",
            issue_id="I1", source_request_id="RQ1", retrieval_round=2,
            first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
        )]
        subarticle_references = HarnessRunner._candidate_cross_references(subarticle_state)
        self.assertIn(
            ("형법", "제227조의2", "제1항"),
            {(item["target_statute_name"], item["target_article"], item.get("target_paragraph")) for item in subarticle_references},
        )
        body_refined_state = self._state()
        body_refined_state.candidate_provisions = [CandidateProvision(
            provision_id="형법 227조 공전자기록등불실기재#base",
            statute_name="형법 227조 공전자기록등불실기재",
            provision_text="제227조의2 제2항 전항의 죄",
            issue_id="I1", source_request_id="RQ1", retrieval_round=2,
            first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
        )]
        body_refined_references = HarnessRunner._candidate_cross_references(body_refined_state)
        self.assertIn(
            ("형법", "제227조의2", "제1항"),
            {(item["target_statute_name"], item["target_article"], item.get("target_paragraph")) for item in body_refined_references},
        )

    def test_ambiguous_or_conflicting_metadata_emits_no_inherited_relative_anchor(self):
        def references_for(provision_id, statute_name, provision_text):
            state = self._state()
            state.candidate_provisions = [CandidateProvision(
                provision_id=provision_id, statute_name=statute_name,
                provision_text=provision_text, issue_id="I1", source_request_id="RQ1",
                retrieval_round=2, first_stage_score=1.0, fusion_rank=1, rerank_score=1.0,
            )]
            return HarnessRunner._candidate_cross_references(state)

        self.assertEqual(
            references_for("형법 334조#one", "형법 335조", "전조의 죄"),
            [],
        )
        self.assertEqual(
            references_for("형법 334조#two", "형법 334조", "제335조 전조의 죄"),
            [],
        )
        self.assertEqual(
            references_for("식별불가#three", "식별불가", "전조의 죄"),
            [],
        )

if __name__ == "__main__":
    unittest.main()
