import json
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import (
    PROMPT_RUN_ID_PLACEHOLDER,
    LocalOllamaSkillExecutor,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalOllamaExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            generator=self._generate,
        )

    @staticmethod
    def _generate(prompt):
        if "ENTRY POINT: INITIAL_PLAN" in prompt:
            return json.dumps(
                {
                    "schema_version": "1.0",
                    "skill_id": "S1",
                    "mode": "INITIAL_PLAN",
                    "status": "ok",
                    "run_id": "run-1",
                    "answer_targets": [
                        {
                            "answer_target_id": "T1",
                            "question_anchor": "손해배상 책임은 무엇인가",
                            "requested_output": "손해배상 책임의 법적 근거",
                            "answer_type": "legal_rule",
                        }
                    ],
                    "legal_issues": [
                        {
                            "issue_id": "I1",
                            "issue_statement": "손해배상 요건",
                            "decision_question": "손해배상 요건은 무엇인가",
                            "importance": "critical",
                        }
                    ],
                    "required_evidence_items": [
                        {
                            "evidence_item_id": "E1",
                            "issue_id": "I1",
                            "evidence_type": "rule",
                            "description": "손해배상 규정",
                            "critical": True,
                            "completion_criteria": "책임의 근거 조문이 있다",
                            "necessity_reason": "책임의 법적 근거를 답하기 위해 필요하다",
                            "answer_target_ids": ["T1"],
                            "scope_source": "explicit_question",
                            "completion_requirements": [
                                {
                                    "requirement_id": "E1-R1",
                                    "text": "책임의 근거 조문",
                                }
                            ],
                        }
                    ],
                    "retrieval_requests": [
                        {
                            "request_id": "RQ1",
                            "issue_id": "I1",
                            "evidence_item_id": "E1",
                            "query_channel": "sparse_keywords",
                            "query_text": "손해배상 책임",
                            "query_terms": ["손해배상"],
                            "statute_hints": [],
                            "rationale": "책임 조문 검색",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "ENTRY POINT: ASSESS_COVERAGE" in prompt:
            return json.dumps(
                {
                    "schema_version": "1.0",
                    "skill_id": "S2",
                    "mode": "ASSESS_COVERAGE",
                    "status": "ok",
                    "run_id": "run-1",
                    "evidence_links": [
                        {
                            "link_id": "L1",
                            "evidence_item_id": "E1",
                            "provision_id": "C001",
                            "relation": "supports",
                            "quoted_text": "[FULL_TEXT]",
                            "rationale": "책임을 정한다",
                        }
                    ],
                    "coverage_assessments": [
                        {
                            "evidence_item_id": "E1",
                            "rationale": "책임 규정이 있다",
                            "legal_status": "covered",
                            "applicability_status": "direct",
                            "gap_type": "none",
                            "criterion_results": [{
                                "requirement_id": "E1-R1",
                                "status": "satisfied",
                                "linked_provision_ids": ["C001"],
                                "rationale": "책임 규정이 있다",
                                "direct_entailment": {
                                    "regulated_subject_or_act": "matched",
                                    "outcome_changing_qualifiers": "matched",
                                    "legal_effect": "matched",
                                    "procedure_or_remedy_path": "not_applicable",
                                    "rationale": "공급된 요건을 직접 충족한다",
                                },
                            }],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "ENTRY POINT: GENERATE_BENCHMARK_CANDIDATE" in prompt:
            if '"candidate_answer_basis":"question_only"' in prompt:
                return json.dumps(
                    {
                        "schema_version": "1.0",
                        "skill_id": "S3",
                        "mode": "GENERATE_BENCHMARK_CANDIDATE",
                        "status": "ok",
                        "run_id": "run-1",
                        "answer": "질문만으로 생성한 후보 답변입니다.",
                        "claims": [],
                        "claim_citations": [],
                        "assumptions": [],
                        "limitations": [],
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "schema_version": "1.0",
                    "skill_id": "S3",
                    "mode": "GENERATE_BENCHMARK_CANDIDATE",
                    "status": "ok",
                    "run_id": "run-1",
                    "answer": "손해를 배상해야 합니다.[CT1]",
                    "claims": [
                        {
                            "claim_id": "C1",
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
                            "citation_id": "CT1",
                            "claim_id": "C1",
                            "provision_id": "C001",
                            "quoted_text": "손해를 배상한다",
                            "support_description": "검색된 후보 조문",
                            "answer_marker": "[CT1]",
                        }
                    ],
                    "assumptions": [],
                    "limitations": [],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "schema_version": "1.0",
                "skill_id": "S3",
                "mode": "GENERATE_ANSWER",
                "status": "ok",
                "run_id": "run-1",
                "answer": "손해를 배상해야 합니다.[CT1]",
                "claims": [
                    {
                        "claim_id": "C1",
                        "text": "손해를 배상해야 합니다.",
                        "claim_type": "legal_rule",
                        "applicability": "direct",
                        "citation_required": True,
                        "public_role": "conclusion",
                    }
                ],
                "claim_citations": [
                    {
                        "citation_id": "CT1",
                        "claim_id": "C1",
                        "provision_id": "P1",
                        "quoted_text": "손해를 배상한다",
                        "support_description": "책임의 근거",
                        "answer_marker": "[CT1]",
                    }
                ],
                "assumptions": [],
                "limitations": [],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _candidate():
        return {
            "provision_id": "P1",
            "statute_name": "예시법 제1조",
            "provision_text": "고의 또는 과실로 손해를 배상한다.",
            "issue_id": "I1",
            "source_request_id": "RQ1",
            "retrieval_round": 1,
            "first_stage_score": 1.0,
            "fusion_rank": 1,
            "rerank_score": 1.0,
            "target_evidence_item_ids": ["E1"],
        }

    @staticmethod
    def _s3_transport_input(question_only=False, required_contract=False):
        benchmark = question_only
        provision_key = "candidate_provisions" if benchmark else "accepted_provisions"
        source = {
            "provision_id": "C001" if benchmark else "P1",
            "text": "고의 또는 과실로 손해를 배상한다.",
            "supported_evidence_item_ids": ["E1"],
        }
        return {
            "schema_version": "1.0",
            "mode": (
                "GENERATE_BENCHMARK_CANDIDATE"
                if benchmark
                else "GENERATE_ANSWER"
            ),
            "run_id": "run-1",
            "required_evidence_items": [
                {"evidence_item_id": "E1", "issue_id": "I1", "critical": True}
            ],
            "answer_targets": [{"answer_target_id": "T1"}],
            "coverage_assessments": [
                {"evidence_item_id": "E1", "status": "covered"}
            ],
            "accepted_provisions": [] if benchmark else [source],
            "candidate_provisions": [] if question_only else ([source] if benchmark else []),
            "answer_mode": "abstain_candidate" if benchmark else "full",
            "answered_target_ids": ["T1"],
            "deferred_target_ids": [],
            "authorization": {
                "action": (
                    "GENERATE_BENCHMARK_CANDIDATE" if benchmark else "GENERATE"
                ),
                "authorized_by": (
                    "HARNESS_BENCHMARK_DIAGNOSTIC"
                    if benchmark
                    else "PROVISION_COVERAGE_POLICY"
                ),
                "validated_state_version": 1,
            },
            "generation_purpose": (
                "benchmark_candidate" if benchmark else "published_answer"
            ),
            "publishable": not benchmark,
            "candidate_answer_basis": "question_only" if question_only else (
                "retrieved_candidates" if benchmark else "published_answer"
            ),
            "generation_constraints": {
                "language": "ko",
                "max_answer_chars": 800,
                "citation_marker_style": "citation_id",
                **({"public_conclusion_contract": "required"} if required_contract else {}),
            },
        }

    def test_s1_maps_plural_sparse_channel_and_frozen_top_k(self):
        result = self.executor.execute(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            {
                "run_id": "run-1",
                "question": "손해배상 책임은 무엇인가",
                "normalized_question": "손해배상 책임은 무엇인가",
                "query_history": [],
            },
        )

        self.assertEqual(result["retrieval_requests"][0]["query_channel"], "sparse_keyword")
        self.assertEqual(result["retrieval_requests"][0]["top_k"], 100)
        self.assertEqual(result["retrieval_requests"][0]["query_terms"], ["손해배상"])
        self.assertEqual(
            result["retrieval_requests"][0]["query_text"],
            "손해배상 책임\n[원문 맥락]\n손해배상 책임은 무엇인가",
        )
        self.assertEqual(result["required_evidence_items"][0]["completion_criteria"], "책임의 근거 조문이 있다")

    def test_s1_context_anchor_keeps_only_the_last_fact_and_question(self):
        source = (
            "무관한 첫 사실이다. 상품이 인도된 날부터 기간을 계산한다. "
            "[질문] 손해배상청구권은 언제까지 행사하는가?"
        )

        contextual = self.executor._with_source_context(
            "운송계약 소멸시효", {"normalized_question": source}
        )

        self.assertNotIn("무관한 첫 사실", contextual)
        self.assertIn("상품이 인도된 날부터", contextual)

    def test_s2_and_s3_map_rich_skill_contracts_to_harness_contracts(self):
        evidence = {
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "손해배상 규정",
            "critical": True,
            "completion_criteria": "책임의 근거 조문이 있다",
            "completion_requirements": [
                {"requirement_id": "E1-R1", "text": "책임의 근거 조문"}
            ],
        }
        coverage = self.executor.execute(
            "provision_coverage_assessment",
            "ASSESS_COVERAGE",
            {
                "run_id": "run-1",
                "normalized_question": "손해배상 책임은 무엇인가",
                "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                "required_evidence_items": [evidence],
                "candidate_provisions": [self._candidate()],
            },
        )
        self.assertEqual(coverage["evidence_links"][0]["assessment"], "accepted")
        self.assertEqual(coverage["evidence_links"][0]["provision_id"], "P1")
        self.assertEqual(coverage["evidence_links"][0]["support_spans"], [{"start_char": 0, "end_char": len(self._candidate()["provision_text"])}])

        answer = self.executor.execute(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            {
                "run_id": "run-1",
                "normalized_question": "손해배상 책임은 무엇인가",
                "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                "required_evidence_items": [evidence],
                "coverage_assessments": coverage["coverage_assessments"],
                "accepted_provisions": [
                    dict(self._candidate(), supported_evidence_item_ids=["E1"])
                ],
                "state_version": 3,
            },
        )
        self.assertEqual(answer["claim_citations"][0]["claim_id"], "C1")
        self.assertEqual(answer["claim_citations"][0]["provision_id"], "P1")
        self.assertEqual(answer["claim_citations"][0]["answer_marker"], "[CT1]")
        self.assertEqual(answer["assumptions"], [])

    def test_s3_transport_normalizes_bad_markers_and_rebuilds_answer(self):
        skill_input = self._s3_transport_input()
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "wrong",
            "answer": "모델이 만든 불완전한 답변",
            "claims": [
                {
                    "claim_id": "rule",
                    "text": "손해를 배상해야 합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "direct",
                    "citation_required": True,
                },
                {
                    "claim_id": "scope",
                    "text": "고의 또는 과실이 필요합니다.",
                    "claim_type": "application",
                    "applicability": "direct",
                    "citation_required": True,
                },
            ],
            "claim_citations": [
                {
                    "citation_id": "bad",
                    "claim_id": "rule",
                    "provision_id": "P1",
                    "quoted_text": "잘못된 인용",
                    "support_description": "배상 의무",
                    "answer_marker": "[CT9]",
                },
                {
                    "citation_id": "also-bad",
                    "claim_id": "scope",
                    "provision_id": "P1",
                    "quoted_text": "축약 인용",
                    "support_description": "고의·과실 요건",
                    "answer_marker": "",
                },
            ],
            "assumptions": [{"code": "A1", "message": "사실관계는 추가 확인이 필요합니다."}],
            "limitations": [{"code": "L1", "message": "판례 판단은 포함하지 않습니다."}],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            raw,
        )

        self.assertEqual([claim["claim_id"] for claim in normalized["claims"]], ["C1", "C2"])
        self.assertEqual(
            [citation["answer_marker"] for citation in normalized["claim_citations"]],
            ["[CT1]", "[CT2]"],
        )
        self.assertEqual(
            normalized["answer"],
            "손해를 배상해야 합니다.[CT1]\n고의 또는 과실이 필요합니다.[CT2]",
        )
        self.assertEqual(
            [claim["answer_target_ids"] for claim in normalized["claims"]],
            [["T1"], ["T1"]],
        )
        self.assertEqual(normalized["assumptions"], raw["assumptions"])
        self.assertEqual(normalized["limitations"], raw["limitations"])
        self.assertEqual(
            normalized["claim_citations"][0]["quoted_text"],
            "고의 또는 과실로 손해를 배상한다.",
        )
        self.assertEqual(normalized["assumptions"], raw["assumptions"])
        self.assertEqual(normalized["limitations"], raw["limitations"])
        self.assertNotIn("전제:", normalized["answer"])
        self.assertNotIn("한계:", normalized["answer"])
        self.assertLessEqual(len(normalized["answer"]), 800)
        self.assertEqual(
            self.executor._validators["grounded_legal_answer_generation"](
                normalized, skill_input
            ),
            [],
        )

    def test_s3_required_contract_leaves_roleless_output_for_validator(self):
        skill_input = self._s3_transport_input(required_contract=True)
        raw = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER",
            "status": "ok", "run_id": "run-1", "answer": "원문",
            "claims": [{
                "claim_id": "raw", "text": "배상 책임이 있습니다.",
                "claim_type": "application", "applicability": "direct",
                "citation_required": True, "answer_target_ids": ["T1"],
            }],
            "claim_citations": [{"claim_id": "raw", "provision_id": "P1", "support_description": "근거"}],
            "assumptions": [], "limitations": [],
        }
        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", skill_input, raw
        )
        self.assertNotIn("public_role", normalized["claims"][0])
        errors = self.executor._validators["grounded_legal_answer_generation"](normalized, skill_input)
        self.assertIn("every claim must declare public_role under the public conclusion contract", errors)

    def test_s3_public_answer_selects_three_claims_and_preserves_full_audit(self):
        skill_input = self._s3_transport_input(required_contract=True)
        claim_specs = [
            ("conclusion", "배상 책임이 인정됩니다.", "application", "direct"),
            ("procedure", "청구 절차를 따라야 합니다.", "procedure", "direct"),
            ("condition", "고의 또는 과실이 있는 경우에 한합니다.", "application", "conditional"),
            ("rule", "민법상 손해배상 규정이 근거입니다.", "legal_rule", "direct"),
            ("remedy", "손해액 상당액을 청구할 수 있습니다.", "remedy", "direct"),
        ]
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "run-1",
            "answer": "모델의 장문 답변",
            "claims": [
                {
                    "claim_id": claim_id,
                    "text": text,
                    "claim_type": claim_type,
                    "applicability": applicability,
                    "citation_required": True,
                    "public_role": "conclusion" if claim_id == "conclusion" else "audit",
                }
                for claim_id, text, claim_type, applicability in claim_specs
            ],
            "claim_citations": [
                {
                    "citation_id": "model-%d" % index,
                    "claim_id": claim_id,
                    "provision_id": "P1",
                    "quoted_text": "축약 인용",
                    "support_description": "감사용 근거 %d" % index,
                    "answer_marker": "[모델]",
                }
                for index, (claim_id, _, _, _) in enumerate(claim_specs, start=1)
            ],
            "assumptions": [
                {"code": "A1", "message": "계약 관계가 존재한다고 가정합니다."}
            ],
            "limitations": [
                {"code": "L1", "message": "구체적 손해액은 별도 확인이 필요합니다."}
            ],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            raw,
        )

        self.assertEqual(len(normalized["claims"]), 5)
        self.assertEqual(len(normalized["claim_citations"]), 5)
        self.assertEqual(
            normalized["answer"],
            "배상 책임이 인정됩니다.[CT1]",
        )
        self.assertEqual(normalized["assumptions"], raw["assumptions"])
        self.assertEqual(normalized["limitations"], raw["limitations"])
        self.assertEqual(len(normalized["answer"].splitlines()), 1)
        self.assertLessEqual(len(normalized["answer"]), 800)
        self.assertEqual(
            self.executor._validators["grounded_legal_answer_generation"](
                normalized, skill_input
            ),
            [],
        )

    def test_s3_transport_retains_limited_scope_audit_without_publishing_notes(self):
        skill_input = self._s3_transport_input()
        skill_input.update(
            {
                "answer_mode": "limited",
                "answer_targets": [
                    {"answer_target_id": "T1"},
                    {
                        "answer_target_id": "T2",
                        "requested_output": "T2 청구 범위",
                    },
                ],
                "answered_target_ids": ["T1"],
                "deferred_target_ids": ["T2"],
            }
        )
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "run-1",
            "answer": "모델 원문",
            "claims": [
                {
                    "claim_id": "rule",
                    "text": "손해를 배상해야 합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "direct",
                    "citation_required": True,
                }
            ],
            "claim_citations": [
                {
                    "citation_id": "raw",
                    "claim_id": "rule",
                    "provision_id": "P1",
                    "quoted_text": "축약 인용",
                    "support_description": "배상 의무",
                    "answer_marker": "[raw]",
                }
            ],
            "assumptions": [
                {"code": "A1", "message": "사실관계는 추가 확인이 필요합니다."}
            ],
            "limitations": [
                {"code": "L1", "message": "T2 청구 범위는 답변에서 제외합니다."}
            ],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            raw,
        )

        self.assertEqual(normalized["answer"], "손해를 배상해야 합니다.[CT1]")
        self.assertEqual(normalized["assumptions"], raw["assumptions"])
        self.assertEqual(normalized["limitations"], raw["limitations"])
        self.assertEqual(
            self.executor._validators["grounded_legal_answer_generation"](
                normalized, skill_input
            ),
            [],
        )

    def test_s3_transport_keeps_every_marker_for_multiple_citations(self):
        skill_input = self._s3_transport_input()
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "run-1",
            "answer": "마커가 빠진 답변",
            "claims": [
                {
                    "claim_id": "claim",
                    "text": "손해를 배상해야 합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "direct",
                    "citation_required": True,
                }
            ],
            "claim_citations": [
                {
                    "citation_id": "one",
                    "claim_id": "claim",
                    "provision_id": "P1",
                    "quoted_text": "임의 인용",
                    "support_description": "첫 번째 근거",
                    "answer_marker": "[CT7]",
                },
                {
                    "citation_id": "two",
                    "claim_id": "claim",
                    "provision_id": "P1",
                    "quoted_text": "임의 인용",
                    "support_description": "두 번째 근거",
                    "answer_marker": "[CT8]",
                },
            ],
            "assumptions": [],
            "limitations": [],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            raw,
        )

        self.assertEqual(normalized["answer"], "손해를 배상해야 합니다.[CT1][CT2]")
        self.assertEqual(
            [citation["citation_id"] for citation in normalized["claim_citations"]],
            ["CT1", "CT2"],
        )
        self.assertEqual(
            self.executor._validators["grounded_legal_answer_generation"](
                normalized, skill_input
            ),
            [],
        )

    def test_s3_transport_leaves_unknown_claim_or_provision_for_validator(self):
        skill_input = self._s3_transport_input()
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "run-1",
            "answer": "손해를 배상해야 합니다.",
            "claims": [
                {
                    "claim_id": "known",
                    "text": "손해를 배상해야 합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "direct",
                    "citation_required": True,
                }
            ],
            "claim_citations": [
                {
                    "citation_id": "bad",
                    "claim_id": "unknown",
                    "provision_id": "P999",
                    "quoted_text": "임의 인용",
                    "support_description": "잘못된 연결",
                    "answer_marker": "[bad]",
                }
            ],
            "assumptions": [],
            "limitations": [],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            skill_input,
            raw,
        )
        errors = self.executor._validators["grounded_legal_answer_generation"](
            normalized, skill_input
        )

        self.assertEqual(normalized["claim_citations"][0]["claim_id"], "unknown")
        self.assertIn("citation references unknown claim: bad", errors)
        self.assertIn("citation uses non-accepted provision: bad", errors)

    def test_s3_transport_preserves_question_only_candidate_answer(self):
        skill_input = self._s3_transport_input(question_only=True)
        raw = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_BENCHMARK_CANDIDATE",
            "status": "ok",
            "run_id": "wrong",
            "answer": "질문만으로 생성한 후보 답변입니다.",
            "claims": [],
            "claim_citations": [],
            "assumptions": [],
            "limitations": [],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation",
            "GENERATE_BENCHMARK_CANDIDATE",
            skill_input,
            raw,
        )

        self.assertEqual(normalized["answer"], raw["answer"])
        self.assertEqual(normalized["claims"], [])
        self.assertEqual(normalized["claim_citations"], [])
        self.assertEqual(
            self.executor._validators["grounded_legal_answer_generation"](
                normalized, skill_input
            ),
            [],
        )

    def test_s3_benchmark_candidate_maps_retrieved_provision_to_source_id(self):
        evidence = {
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "손해배상 규정",
            "critical": True,
            "completion_criteria": "책임의 근거 조문이 있다",
        }
        result = self.executor.execute(
            "grounded_legal_answer_generation",
            "GENERATE_BENCHMARK_CANDIDATE",
            {
                "run_id": "run-1",
                "normalized_question": "손해배상 책임은 무엇인가",
                "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                "answer_targets": [
                    {
                        "answer_target_id": "T1",
                        "question_anchor": "손해배상 책임은 무엇인가",
                        "requested_output": "법적 근거",
                        "answer_type": "legal_rule",
                    }
                ],
                "required_evidence_items": [evidence],
                "coverage_assessments": [
                    {"evidence_item_id": "E1", "status": "uncovered"}
                ],
                "accepted_provisions": [],
                "candidate_provisions": [self._candidate()],
                "candidate_answer_basis": "retrieved_candidates",
                "answer_mode": "abstain_candidate",
                "answered_target_ids": ["T1"],
                "deferred_target_ids": [],
                "state_version": 3,
            },
        )

        self.assertEqual(result["claim_citations"][0]["claim_id"], "C1")
        self.assertEqual(result["claim_citations"][0]["provision_id"], "P1")
        self.assertEqual(result["claim_citations"][0]["answer_marker"], "[CT1]")

    def test_s3_question_only_candidate_allows_empty_claims_and_citations(self):
        evidence = {
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "손해배상 규정",
            "critical": True,
            "completion_criteria": "책임의 근거 조문이 있다",
        }
        result = self.executor.execute(
            "grounded_legal_answer_generation",
            "GENERATE_BENCHMARK_CANDIDATE",
            {
                "run_id": "run-1",
                "normalized_question": "손해배상 책임은 무엇인가",
                "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                "answer_targets": [
                    {
                        "answer_target_id": "T1",
                        "question_anchor": "손해배상 책임은 무엇인가",
                        "requested_output": "법적 근거",
                        "answer_type": "legal_rule",
                    }
                ],
                "required_evidence_items": [evidence],
                "coverage_assessments": [
                    {"evidence_item_id": "E1", "status": "uncovered"}
                ],
                "accepted_provisions": [],
                "candidate_provisions": [],
                "candidate_answer_basis": "question_only",
                "answer_mode": "abstain_candidate",
                "answered_target_ids": ["T1"],
                "deferred_target_ids": [],
                "state_version": 3,
            },
        )

        self.assertEqual(result["claims"], [])
        self.assertEqual(result["claim_citations"], [])

    def test_s2_rejects_repeated_evidence_assessments_without_repairing_ids(self):
        raw = {
            "schema_version": "1.0",
            "skill_id": "S2",
            "mode": "ASSESS_COVERAGE",
            "status": "ok",
            "run_id": "wrong",
            "evidence_links": [
                {
                    "link_id": "L1",
                    "evidence_item_id": "E1",
                    "provision_id": "C001",
                    "relation": "supports",
                    "quoted_text": "[FULL_TEXT]",
                    "rationale": "근거",
                },
                {
                    "link_id": "L1",
                    "evidence_item_id": "E1",
                    "provision_id": "C001",
                    "relation": "supports",
                    "quoted_text": "[FULL_TEXT]",
                    "rationale": "중복 근거",
                },
            ],
            "coverage_assessments": [
                {
                    "evidence_item_id": "E1",
                    "rationale": "충족",
                    "legal_status": "covered",
                    "applicability_status": "direct",
                    "gap_type": "none",
                    "criterion_results": [],
                },
                {
                    "evidence_item_id": "E1",
                    "rationale": "중복",
                    "legal_status": "covered",
                    "applicability_status": "direct",
                    "gap_type": "none",
                    "criterion_results": [],
                },
            ],
        }
        executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            generator=lambda prompt: json.dumps(raw, ensure_ascii=False),
        )
        evidence = {
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "손해배상 규정",
            "critical": True,
            "completion_criteria": "책임의 근거 조문이 있다",
        }

        with self.assertRaises(SkillExecutionError):
            executor.execute(
                "provision_coverage_assessment",
                "ASSESS_COVERAGE",
                {
                    "run_id": "run-1",
                    "normalized_question": "손해배상 책임은 무엇인가",
                    "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                    "required_evidence_items": [evidence],
                    "candidate_provisions": [self._candidate()],
                },
            )

    def test_s2_derives_aspect_ids_from_complete_criterion_results(self):
        skill_input = {
            "run_id": "run-1",
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "critical": True,
                    "completion_requirements": [
                        {"requirement_id": "E1-R1", "text": "책임 근거"},
                        {"requirement_id": "E1-R2", "text": "적용 요건"},
                    ],
                }
            ],
            "candidate_provisions": [{"provision_id": "C001"}],
        }
        raw = {
            "status": "ok",
            "evidence_links": [
                {
                    "evidence_item_id": "E1",
                    "provision_id": "C001",
                    "relation": "partially_supports",
                }
            ],
            "coverage_assessments": [
                {
                    "evidence_item_id": "E1",
                    "rationale": "일부 요건이 부족함",
                    "legal_status": "partially_covered",
                    "applicability_status": "not_assessed",
                    "gap_type": "missing_statute",
                    "criterion_results": [
                        {"requirement_id": "E1-R2", "status": "unsatisfied"},
                        {"requirement_id": "E1-R1", "status": "satisfied"},
                    ],
                }
            ],
            "missing_evidence_items": [],
            "evidence_conflicts": [],
        }

        normalized = self.executor._normalize_harness_owned_fields(
            "provision_coverage_assessment",
            "ASSESS_COVERAGE",
            skill_input,
            raw,
        )
        assessment = normalized["coverage_assessments"][0]

        self.assertEqual(assessment["satisfied_aspects"], ["E1-R1"])
        self.assertEqual(assessment["missing_aspects"], ["E1-R2"])
        self.assertEqual(
            [item["requirement_id"] for item in assessment["criterion_results"]],
            ["E1-R1", "E1-R2"],
        )

    def test_s3_accepts_cited_partial_critical_evidence_only_conditionally(self):
        skill_input = {
            "schema_version": "1.0",
            "mode": "GENERATE_ANSWER",
            "run_id": "run-1",
            "normalized_question": "비용은 누가 부담하는가",
            "legal_issues": [{"issue_id": "I1"}],
            "required_evidence_items": [
                {"evidence_item_id": "E1", "issue_id": "I1", "critical": True}
            ],
            "coverage_assessments": [
                {"evidence_item_id": "E1", "status": "partially_covered"}
            ],
            "accepted_provisions": [
                {
                    "provision_id": "P1",
                    "statute_name": "예시법",
                    "article_label": "제1조",
                    "text": "중대한 과실이면 비용을 부담한다.",
                    "source_snapshot_id": "sha256:test",
                    "supported_evidence_item_ids": ["E1"],
                }
            ],
            "authorization": {
                "action": "GENERATE",
                "authorized_by": "PROVISION_COVERAGE_POLICY",
                "validated_state_version": 3,
            },
            "generation_purpose": "published_answer",
            "publishable": True,
            "candidate_answer_basis": "published_answer",
            "generation_constraints": {
                "language": "ko",
                "max_answer_chars": 800,
                "citation_marker_style": "citation_id",
            },
        }
        output = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "run-1",
            "answer": "중대한 과실이면 비용을 부담합니다.[CT1]",
            "claims": [
                {
                    "claim_id": "C1",
                    "text": "중대한 과실이면 비용을 부담합니다.",
                    "claim_type": "legal_rule",
                    "applicability": "conditional",
                    "citation_required": True,
                }
            ],
            "claim_citations": [
                {
                    "citation_id": "CT1",
                    "claim_id": "C1",
                    "provision_id": "P1",
                    "quoted_text": "중대한 과실이면 비용을 부담한다.",
                    "support_description": "조건부 비용 부담",
                    "answer_marker": "[CT1]",
                }
            ],
            "assumptions": [],
            "limitations": [
                {"code": "FACT_CONDITION", "message": "중대한 과실인지는 추가 확인이 필요합니다."}
            ],
        }

        errors = self.executor._validators[
            "grounded_legal_answer_generation"
        ](output, skill_input)

        self.assertEqual(errors, [])
        invariants = self.executor._output_invariants(
            "grounded_legal_answer_generation", skill_input
        )
        self.assertIn("Include at least one cited conditional legal claim", invariants)
        self.assertIn("Every claims[] item must set citation_required", invariants)

        uncited_limitation = dict(output)
        uncited_limitation["answer"] = (
            output["answer"] + " 중대한 과실 해당 여부는 추가 확인이 필요합니다."
        )
        uncited_limitation["claims"] = output["claims"] + [
            {
                "claim_id": "C2",
                "text": "중대한 과실 해당 여부는 추가 확인이 필요합니다.",
                "claim_type": "limitation",
                "applicability": "conditional",
                "citation_required": False,
            }
        ]
        errors = self.executor._validators[
            "grounded_legal_answer_generation"
        ](uncited_limitation, skill_input)
        self.assertIn("every claims[] item must require citation: C2", errors)
        self.assertIn("claim lacks citation: C2", errors)


    def test_s2_invariants_delegate_to_closed_requirement_mapping(self):
        skill_input = {
            "required_evidence_items": [
                {"evidence_item_id": "E1", "issue_id": "I1", "critical": True}
            ],
            "candidate_provisions": [
                {"provision_id": "C001"},
                {"provision_id": "C002"},
            ],
        }

        invariants = self.executor._output_invariants(
            "provision_coverage_assessment", skill_input
        )

        self.assertIn("closed-requirement coverage mapping", invariants)
        self.assertIn("never invent IDs", invariants)
        self.assertIn("Omit legacy status", invariants)

    def test_s1_normalizes_initial_and_gap_queries(self):
        initial = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            {"run_id": "run-1"},
            {
                "legal_issues": [
                    {"issue_id": "I1", "decision_question": "도박죄 처벌"},
                    {"issue_id": "I2", "decision_question": "도박죄 성립 요건"},
                ],
                "retrieval_requests": [
                    {
                        "issue_id": "I1",
                        "query_text": "도박죄 처벌 규정",
                        "query_terms": ["도박죄", "도박죄", " 처벌 ", ""],
                        "statute_hints": ["형법", "형법", " 형법 "],
                    },
                    {"issue_id": "I2", "query_text": "도박죄 처벌 규정"},
                ],
            },
        )
        initial_requests = initial["retrieval_requests"]
        self.assertEqual([item["request_id"] for item in initial_requests], ["RQ1", "RQ2"])
        self.assertNotEqual(initial_requests[0]["query_text"], initial_requests[1]["query_text"])
        self.assertEqual(initial_requests[0]["query_terms"], ["도박죄", "처벌"])
        self.assertEqual(initial_requests[0]["statute_hints"], ["형법"])
        self.assertEqual(self.executor._max_tokens("legal_issue_and_query_planning"), 4096)

        gap = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            {
                "run_id": "run-1",
                "normalized_question": "도박죄 처벌 여부는?",
                "required_evidence_items": [
                    {
                        "evidence_item_id": "E1",
                        "issue_id": "I1",
                        "description": "도박죄 처벌 규정",
                        "completion_criteria": "처벌 조문",
                    }
                ],
                "missing_evidence_items": [{"evidence_item_id": "E1"}],
                "evidence_conflicts": [],
                "query_history": [{
                    "query_text": "기존 질의\n[원문 맥락]\n도박죄 처벌 여부는?"
                }],
            },
            {
                "gap_retrieval_requests": [
                    {"issue_id": None, "evidence_item_id": None, "query_text": "기존 질의"}
                ]
            },
        )
        gap_request = gap["gap_retrieval_requests"][0]
        self.assertEqual(gap_request["request_id"], "GRQ-R1-1")
        second_round = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            {
                "run_id": "run-1",
                "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "description": "도박죄 처벌 규정", "completion_criteria": "처벌 조문"}],
                "missing_evidence_items": [{"evidence_item_id": "E1"}],
                "evidence_conflicts": [],
                "query_history": [],
                "next_retrieval_round": 2,
            },
            {"gap_retrieval_requests": [{"issue_id": "I1", "evidence_item_id": "E1", "query_text": "새 질의"}]},
        )
        self.assertEqual(second_round["gap_retrieval_requests"][0]["request_id"], "GRQ-R2-1")
        self.assertEqual(gap_request["issue_id"], "I1")
        self.assertEqual(gap_request["evidence_item_id"], "E1")
        self.assertEqual(
            gap_request["query_text"],
            "기존 질의\n[원문 맥락]\n도박죄 처벌 여부는?",
        )
        self.assertEqual(gap["target_evidence_item_ids"], ["E1"])

    def test_s1_reports_ollama_length_truncation_separately(self):
        def truncated_json(_prompt):
            return {
                "response": '{"schema_version":"1.0"',
                "done_reason": "length",
                "eval_count": 4096,
            }

        truncated_executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            max_attempts=1,
            generator=truncated_json,
        )

        with self.assertRaisesRegex(
            SkillExecutionError,
            "MODEL_OUTPUT_TRUNCATED: legal_issue_and_query_planning INITIAL_PLAN attempt 1 reached num_predict=4096",
        ):
            truncated_executor.execute(
                "legal_issue_and_query_planning",
                "INITIAL_PLAN",
                {
                    "run_id": "run-1",
                    "question": "손해배상 책임은 무엇인가",
                    "normalized_question": "손해배상 책임은 무엇인가",
                    "query_history": [],
                },
            )

    def test_gap_history_duplicate_is_preserved_after_context_is_attached(self):
        source = (
            "상품이 인도되었다. [질문] 손해배상청구권은 언제까지 행사하는가?"
        )
        completion = "운송인의 손해배상청구권 기간과 기산점"
        skill_input = {
            "run_id": "run-1",
            "normalized_question": source,
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "description": completion,
                    "completion_criteria": completion,
                }
            ],
            "missing_evidence_items": [{"evidence_item_id": "E1"}],
            "evidence_conflicts": [],
        }
        prior_query = self.executor._with_source_context(
            completion + " 법률 조문", skill_input
        )
        skill_input["query_history"] = [{"query_text": prior_query}]

        result = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            skill_input,
            {
                "gap_retrieval_requests": [
                    {
                        "issue_id": "I1",
                        "evidence_item_id": "E1",
                        "query_text": prior_query,
                    }
                ]
            },
        )

        emitted = result["gap_retrieval_requests"][0]["query_text"]
        self.assertEqual(
            self.executor._normalized_query(emitted),
            self.executor._normalized_query(prior_query),
        )
        self.assertIn("[원문 맥락]", emitted)

    def test_gap_same_output_duplicate_gets_deterministic_unique_fallback(self):
        source = "상품이 인도되었다. [질문] 손해배상청구권은 언제까지 행사하는가?"
        completion = "운송인의 손해배상청구권 기간과 기산점"
        skill_input = {
            "run_id": "run-1",
            "normalized_question": source,
            "required_evidence_items": [{
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "description": completion,
                "completion_criteria": completion,
            }],
            "missing_evidence_items": [{"evidence_item_id": "E1"}],
            "evidence_conflicts": [],
            "query_history": [],
        }
        output = {
            "gap_retrieval_requests": [
                {"issue_id": "I1", "evidence_item_id": "E1", "query_text": completion},
                {"issue_id": "I1", "evidence_item_id": "E1", "query_text": completion},
            ]
        }

        first = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", skill_input, json.loads(json.dumps(output))
        )
        second = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", skill_input, json.loads(json.dumps(output))
        )
        first_queries = [request["query_text"] for request in first["gap_retrieval_requests"]]
        second_queries = [request["query_text"] for request in second["gap_retrieval_requests"]]

        self.assertEqual(first_queries, second_queries)
        self.assertNotEqual(
            self.executor._normalized_query(first_queries[0]),
            self.executor._normalized_query(first_queries[1]),
        )
        self.assertEqual(
            first_queries[1],
            self.executor._with_source_context(completion + " 법률 조문", skill_input),
        )

    def test_gap_missing_query_uses_contextual_fallback(self):
        source = "상품이 인도되었다. [질문] 손해배상청구권은 언제까지 행사하는가?"
        completion = "운송인의 손해배상청구권 기간과 기산점"
        skill_input = {
            "run_id": "run-1",
            "normalized_question": source,
            "required_evidence_items": [{
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "description": completion,
                "completion_criteria": completion,
            }],
            "missing_evidence_items": [{"evidence_item_id": "E1"}],
            "evidence_conflicts": [],
            "query_history": [],
        }

        result = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            skill_input,
            {"gap_retrieval_requests": [{
                "issue_id": "I1", "evidence_item_id": "E1", "query_text": None
            }]},
        )

        self.assertEqual(
            result["gap_retrieval_requests"][0]["query_text"],
            self.executor._with_source_context(completion + " 법률 조문", skill_input),
        )


    @staticmethod
    def _initial_plan_payload():
        return {
            "run_id": "run-1",
            "question": "손해배상 책임은 무엇인가",
            "normalized_question": "손해배상 책임은 무엇인가",
            "query_history": [],
        }

    def test_s1_length_retry_uses_larger_limit_and_records_raw_diagnostics(self):
        diagnostics = []
        call_count = 0

        def generator(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "response": '{"schema_version":"1.0","unfinished":',
                    "done_reason": "length",
                    "eval_count": 4096,
                }
            return {
                "response": self._generate(prompt),
                "done_reason": "stop",
                "eval_count": 512,
            }

        executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            generator=generator,
            diagnostic_sink=diagnostics.append,
        )
        result = executor.execute(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            self._initial_plan_payload(),
        )

        self.assertEqual(result["retrieval_requests"][0]["request_id"], "RQ1")
        self.assertEqual(
            [item["requested_max_tokens"] for item in diagnostics],
            [4096, 8192],
        )
        self.assertEqual(
            [item["outcome"] for item in diagnostics],
            ["truncated", "valid"],
        )
        self.assertEqual(diagnostics[0]["done_reason"], "length")
        self.assertEqual(diagnostics[0]["error_code"], "MODEL_OUTPUT_TRUNCATED")
        self.assertEqual(diagnostics[0]["eval_count"], 4096)
        self.assertEqual(diagnostics[0]["response_tokens"], 4096)
        self.assertEqual(diagnostics[0]["response_characters"], 37)
        self.assertEqual(len(diagnostics[0]["response_sha256"]), 64)
        self.assertTrue(diagnostics[0]["response_tail"].endswith('"unfinished":'))

    def test_invalid_json_has_distinct_error_code_and_diagnostic(self):
        diagnostics = []
        executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            max_attempts=1,
            generator=lambda prompt: {
                "response": '{"unfinished":',
                "done_reason": "stop",
                "eval_count": 12,
            },
            diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError) as raised:
            executor.execute(
                "legal_issue_and_query_planning",
                "INITIAL_PLAN",
                self._initial_plan_payload(),
            )

        self.assertIn("MODEL_OUTPUT_INVALID_JSON", str(raised.exception))
        self.assertEqual(diagnostics[0]["outcome"], "invalid_json")
        self.assertEqual(diagnostics[0]["error_code"], "MODEL_OUTPUT_INVALID_JSON")
        self.assertEqual(diagnostics[0]["done_reason"], "stop")

    def test_s1_query_terms_exact_duplicates_are_removed_deterministically(self):
        def generator(prompt):
            output = json.loads(self._generate(prompt))
            output["retrieval_requests"][0]["query_terms"] = [
                "손해배상",
                "손해배상",
                "책임",
            ]
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            skills_root=PROJECT_ROOT / "skills",
            model="test-model",
            generator=generator,
        )
        result = executor.execute(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            self._initial_plan_payload(),
        )

        self.assertEqual(
            result["retrieval_requests"][0]["query_terms"],
            ["손해배상", "책임"],
        )

    def test_generate_forwards_configured_seed_to_ollama(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            @staticmethod
            def read():
                return b'{"response":"{}"}'

        for seed in (0, 1729):
            with self.subTest(seed=seed):
                executor = LocalOllamaSkillExecutor(
                    skills_root=PROJECT_ROOT / "skills",
                    model="test-model",
                    seed=seed,
                )
                with patch(
                    "runtime.local_ollama_executor.urllib.request.urlopen",
                    return_value=Response(),
                ) as urlopen:
                    executor._generate("seed transport test", max_tokens=321)

                request = urlopen.call_args.args[0]
                payload = json.loads(request.data.decode("utf-8"))
                self.assertEqual(payload["options"]["seed"], seed)
                self.assertEqual(payload["options"]["temperature"], 0)
                self.assertEqual(payload["options"]["num_ctx"], executor.num_ctx)
                self.assertEqual(payload["options"]["num_predict"], 321)

    def test_s2_and_s3_skill_instructions_preserve_precision_boundaries(self):
        skills_root = PROJECT_ROOT / "skills"
        manifest = json.loads(
            (skills_root / "skill-pack-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [skill["folder"] for skill in manifest["skills"]],
            ["legal_issue_and_query_planning", "provision_coverage_assessment", "grounded_legal_answer_generation"],
        )

        s2 = (skills_root / "provision_coverage_assessment" / "SKILL.md").read_text(encoding="utf-8")
        s2_contract = (skills_root / "provision_coverage_assessment" / "references" / "contract.md").read_text(encoding="utf-8")
        s2_text = s2 + "\n" + s2_contract
        self.assertIn("smallest directly entailing provision set", s2_text)
        self.assertIn("Audit-only helpful context", s2_text)
        self.assertIn("must remain unlinked", s2_text)

        s3 = (skills_root / "grounded_legal_answer_generation" / "SKILL.md").read_text(encoding="utf-8")
        s3_contract = (skills_root / "grounded_legal_answer_generation" / "references" / "contract.md").read_text(encoding="utf-8")
        s3_text = s3 + "\n" + s3_contract
        self.assertIn("requested answer targets", s3_text)
        self.assertIn("do not summarize every accepted provision", s3_text)
        self.assertIn("adjacent legal fact", s3_text)

    def test_prompts_redact_run_ids_for_all_skills_without_mutating_skill_input(self):
        run_ids = (
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        )
        evidence = {
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "손해배상 규정",
            "critical": True,
            "completion_criteria": "책임의 근거 조문이 있다",
        }

        def payload_for(skill_name, run_id):
            if skill_name == "legal_issue_and_query_planning":
                payload = self._initial_plan_payload()
                payload["run_id"] = run_id
                payload["query_history"] = [{"run_id": run_id, "query_text": "기존 질의"}]
                return payload
            payload = {
                "run_id": run_id,
                "normalized_question": "손해배상 책임은 무엇인가",
                "legal_issues": [{"issue_id": "I1", "description": "손해배상"}],
                "answer_targets": [{"answer_target_id": "T1"}],
                "required_evidence_items": [evidence],
                "candidate_provisions": [self._candidate()],
                "accepted_provisions": [],
            }
            if skill_name == "provision_coverage_assessment":
                return payload
            payload.update(
                {
                    "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered"}],
                    "candidate_answer_basis": "retrieved_candidates",
                    "state_version": 1,
                }
            )
            return payload

        cases = (
            ("legal_issue_and_query_planning", "INITIAL_PLAN"),
            ("provision_coverage_assessment", "ASSESS_COVERAGE"),
            ("grounded_legal_answer_generation", "GENERATE_BENCHMARK_CANDIDATE"),
        )
        for skill_name, entry_point in cases:
            with self.subTest(skill_name=skill_name):
                prompts = []
                inputs = []
                for run_id in run_ids:
                    skill_input = self.executor._build_skill_input(
                        skill_name, entry_point, payload_for(skill_name, run_id)
                    )
                    inputs.append(skill_input)
                    prompts.append(
                        self.executor._prompt(skill_name, entry_point, skill_input, "")
                    )

                self.assertEqual(prompts[0], prompts[1])
                self.assertIn(PROMPT_RUN_ID_PLACEHOLDER, prompts[0])
                for run_id, skill_input in zip(run_ids, inputs):
                    self.assertNotIn(run_id, prompts[0])
                    self.assertEqual(skill_input["run_id"], run_id)
                if skill_name != "legal_issue_and_query_planning":
                    self.assertIn(
                        '"retrieval_metadata":{"run_id":"%s"' % PROMPT_RUN_ID_PLACEHOLDER,
                        prompts[0],
                    )

        skill_input = self.executor._build_skill_input(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            payload_for("legal_issue_and_query_planning", run_ids[0]),
        )
        normalized = self.executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            skill_input,
            json.loads(self._generate("ENTRY POINT: INITIAL_PLAN")),
        )
        self.assertEqual(normalized["run_id"], run_ids[0])
        self.executor._adapt_output(
            "legal_issue_and_query_planning", "INITIAL_PLAN", normalized, skill_input
        )
        self.assertEqual(normalized["run_id"], run_ids[0])
        self.assertEqual(skill_input["run_id"], run_ids[0])

    def test_validation_retry_prompts_redact_normalized_run_id(self):
        run_ids = (
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        )

        def run_with_retry(run_id):
            prompts = []
            diagnostics = []

            def generator(prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    return json.dumps(
                        {
                            "schema_version": "1.0",
                            "skill_id": "S1",
                            "mode": "INITIAL_PLAN",
                            "status": "ok",
                            "run_id": "model-supplied-run-id",
                        }
                    )
                return self._generate(prompt)

            executor = LocalOllamaSkillExecutor(
                skills_root=PROJECT_ROOT / "skills",
                model="test-model",
                generator=generator,
                diagnostic_sink=diagnostics.append,
            )
            payload = self._initial_plan_payload()
            payload["run_id"] = run_id
            result = executor.execute(
                "legal_issue_and_query_planning", "INITIAL_PLAN", payload
            )
            return prompts, diagnostics, result

        first_prompts, first_diagnostics, first_result = run_with_retry(run_ids[0])
        second_prompts, second_diagnostics, second_result = run_with_retry(run_ids[1])
        self.assertEqual(first_prompts, second_prompts)
        self.assertEqual(len(first_prompts), 2)
        self.assertIn("Previous JSON:", first_prompts[1])
        self.assertIn(
            '"run_id":"%s"' % PROMPT_RUN_ID_PLACEHOLDER,
            first_prompts[1].split("Previous JSON: ", 1)[1],
        )
        for prompt in first_prompts:
            self.assertIn(PROMPT_RUN_ID_PLACEHOLDER, prompt)
            for run_id in run_ids:
                self.assertNotIn(run_id, prompt)
        self.assertEqual(
            [item["run_id"] for item in first_diagnostics], [run_ids[0], run_ids[0]]
        )
        self.assertEqual(
            [item["run_id"] for item in second_diagnostics], [run_ids[1], run_ids[1]]
        )
        self.assertEqual(first_result["retrieval_requests"], second_result["retrieval_requests"])
