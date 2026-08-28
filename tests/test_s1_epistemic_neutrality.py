import unittest
import json
from pathlib import Path
import importlib.util

from runtime.local_ollama_executor import LocalOllamaSkillExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SPEC = importlib.util.spec_from_file_location("s1_validator", PROJECT_ROOT / "skills/legal_issue_and_query_planning/scripts/validate_output.py")
S1_VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(S1_VALIDATOR)


class S1EpistemicNeutralityFixtures(unittest.TestCase):
    """Prompt fixtures: no benchmark IDs or asserted legal answers."""

    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", generator=lambda _prompt: "{}"
        )

    def test_requirement_question_does_not_invite_an_invented_success_threshold(self):
        fixture_question = "청구가 가능한 요건은 무엇인가?"
        prompt = self.executor._output_invariants(
            "legal_issue_and_query_planning",
            {"mode": "INITIAL_PLAN", "normalized_question": fixture_question},
        )
        self.assertIn("evidence obligations", prompt)
        self.assertIn("Do not state a legal answer, article, condition, or threshold", prompt)
        contract = (PROJECT_ROOT / "skills/legal_issue_and_query_planning/references/contract.md").read_text(encoding="utf-8")
        self.assertIn("retrieval hypotheses", contract)

    def test_generic_conditions_question_does_not_authorize_a_blanket_exception_query(self):
        prompt = self.executor._prompt(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            {
                "run_id": "s1-generic-conditions",
                "mode": "INITIAL_PLAN",
                "normalized_question": "청구의 조건과 요건은 무엇인가?",
            },
            "",
        )
        self.assertIn(
            "generic request for conditions or requirements does not by itself authorize a blanket \"exception provision\"",
            " ".join(prompt.split()),
        )
        self.assertIn("a stated concrete fact activates it", prompt)
        for relative in (
            "skills/legal_issue_and_query_planning/SKILL.md",
            "skills/legal_issue_and_query_planning/references/contract.md",
        ):
            self.assertIn(
                "never a generic exception provision",
                (PROJECT_ROOT / relative).read_text(encoding="utf-8"),
            )

    def test_single_explicit_output_does_not_invite_an_unrelated_contract_theory(self):
        fixture_question = "이 통지가 효력이 있는지 판단하라."
        prompt = self.executor._output_invariants(
            "legal_issue_and_query_planning",
            {"mode": "INITIAL_PLAN", "normalized_question": fixture_question},
        )
        self.assertIn("separate critical evidence for distinct rules, exceptions, cross-references, or legal effects", prompt)
        self.assertIn("genuinely independent rules", prompt)

    def test_gap_prompt_requires_relevance_before_promoting_cross_reference_provenance(self):
        prompt = self.executor._output_invariants(
            "legal_issue_and_query_planning",
            {
                "mode": "GAP_QUERY_PLAN",
                "normalized_question": "형사 책임이 성립하는가",
                "query_history": [],
                "missing_evidence_items": [{"evidence_item_id": "E1"}],
                "evidence_conflicts": [],
            },
        )
        self.assertIn("candidate_cross_references item", prompt)
        self.assertIn("provenance, not its relevance", prompt)
        self.assertIn("matches every material component stated in the unresolved completion requirement", prompt)
        self.assertIn("subject/actor, act, trigger/qualifier, and legal effect as applicable", prompt)
        self.assertIn("A partial component overlap is insufficient", prompt)
        self.assertIn("literal range that excludes the requirement's relevant root", prompt)
        self.assertIn("Never invent an article, paragraph, deadline, or threshold", prompt)
        self.assertIn("court, agency, actor, or procedure name alone is not a statute hint", prompt)
        self.assertIn("unsatisfied atomic completion requirement", prompt)
        self.assertIn("material legal relation rather than paraphrasing", prompt)

        skill = (PROJECT_ROOT / "skills/legal_issue_and_query_planning/SKILL.md").read_text(encoding="utf-8")
        contract = (PROJECT_ROOT / "skills/legal_issue_and_query_planning/references/contract.md").read_text(encoding="utf-8")
        for source in (skill, contract):
            normalized_source = " ".join(source.split())
            self.assertIn("provenance, not relevance", normalized_source)
            self.assertIn("matches every material component stated in the unresolved completion requirement", normalized_source)
            self.assertIn("A partial component overlap is insufficient", normalized_source)
            self.assertIn("literal range that excludes the requirement's relevant root", normalized_source)
            self.assertIn("court, agency, actor, or procedure name alone is not a statute hint", normalized_source)
            self.assertIn("unsatisfied atomic completion requirement", normalized_source)

    def test_directly_matched_supplied_cross_reference_remains_transport_eligible(self):
        errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": "예시법 제14조 해제 통지의 효력",
                "query_terms": ["해제 통지", "효력"],
                "statute_hints": ["예시법 제14조"],
            }],
            {
                "normalized_question": "통지의 효력을 판단하라.",
                "seen_provision_ids": ["candidate-alpha"],
                "candidate_cross_references": [{
                    "source_candidate_id": "candidate-alpha",
                    "target_statute_name": "예시법",
                    "target_article": "제14조",
                    "excerpt": "해제 통지의 효력은 예시법 제14조에 따른다.",
                    "start_char": 0,
                    "end_char": 23,
                }],
            },
            errors,
        )
        self.assertEqual(errors, [])


    def test_validator_rejects_new_unanchored_article_and_allows_question_article(self):
        unanchored_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "민법 제999조 요건", "statute_hints": []}],
            {"normalized_question": "통지의 효력은 무엇인가?"},
            unanchored_errors,
        )
        self.assertTrue(any("question or supplied candidate-cross-reference provenance" in error for error in unanchored_errors))
        anchored_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "민법 제186조 효과", "statute_hints": ["민법 제186조"]}],
            {"normalized_question": "민법 제186조의 효과는 무엇인가?"},
            anchored_errors,
        )
        self.assertEqual(anchored_errors, [])


    def test_candidate_provenance_allows_each_retrieval_field_and_rejects_unanchored_term(self):
        anchored_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": "형법 제333조",
                "query_terms": ["333조"],
                "statute_hints": ["제333조"],
                "first_stage_query_text": "형법 333조",
                "rerank_query_text": "제333조 적용",
            }],
            {
                "normalized_question": "강도죄가 성립하는가?",
                "seen_provision_ids": ["P1"],
                "candidate_cross_references": [{
                    "source_candidate_id": "P1", "target_statute_name": "형법",
                    "target_article": "제333조", "excerpt": "전조",
                    "start_char": 4, "end_char": 6,
                }],
            },
            anchored_errors,
        )
        self.assertEqual(anchored_errors, [])
        rejected_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "제999조", "query_terms": ["999조"], "statute_hints": []}],
            {"normalized_question": "강도죄가 성립하는가?", "seen_provision_ids": ["P1"], "candidate_cross_references": []},
            rejected_errors,
        )
        self.assertTrue(any("provenance" in error for error in rejected_errors))

    def test_cross_law_pair_provenance_and_request_scoped_paragraph_binding(self):
        anchor = {
            "normalized_question": "특별법 적용 여부를 판단하라.",
            "seen_provision_ids": ["P1"],
            "candidate_cross_references": [{
                "source_candidate_id": "P1",
                "target_statute_name": "형법",
                "target_article": "제329조",
                "excerpt": "「형법」 제329조",
                "start_char": 0,
                "end_char": 10,
            }],
        }
        allowed_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": "「형법」 제329조",
                "query_terms": ["329조"],
                "statute_hints": ["형법 제329조"],
                "first_stage_query_text": "형법 제329조 구성요건",
                "rerank_query_text": "제329조 적용",
            }], anchor, allowed_errors,
        )
        self.assertEqual(allowed_errors, [])
        denied_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "특별법 제329조", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            anchor, denied_errors,
        )
        self.assertTrue(any("statute/article pair lacks" in error for error in denied_errors))
        paragraph_anchor = dict(anchor, candidate_cross_references=[{
            "source_candidate_id": "P1",
            "target_statute_name": "형법",
            "target_article": "제334조",
            "target_paragraph": "제1항",
            "excerpt": "제334조 제1항",
            "start_char": 0,
            "end_char": 8,
        }])
        paragraph_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조 제1항", "query_terms": ["제1항"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paragraph_anchor, paragraph_errors,
        )
        self.assertEqual(paragraph_errors, [])
        less_specific_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조", "query_terms": ["제334조"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paragraph_anchor, less_specific_errors,
        )
        self.assertEqual(less_specific_errors, [])
        missing_binding_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조", "query_terms": ["제1항"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paragraph_anchor, missing_binding_errors,
        )
        self.assertEqual(missing_binding_errors, [])
        wrong_paragraph_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조", "query_terms": ["제2항"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paragraph_anchor, wrong_paragraph_errors,
        )
        self.assertTrue(any("request-scoped" in error for error in wrong_paragraph_errors))
        no_article_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "강도죄", "query_terms": ["제1항"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paragraph_anchor, no_article_errors,
        )
        self.assertTrue(any("request-scoped" in error for error in no_article_errors))
        article_only_anchor = dict(anchor, candidate_cross_references=[{
            "source_candidate_id": "P1", "target_statute_name": "형법",
            "target_article": "제334조", "excerpt": "제334조",
            "start_char": 0, "end_char": 4,
        }])
        invented_paragraph_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조 제1항", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            article_only_anchor, invented_paragraph_errors,
        )
        self.assertTrue(any("statute/article pair lacks" in error for error in invented_paragraph_errors))
        ambiguous_anchor = dict(anchor, candidate_cross_references=[
            {"source_candidate_id": "P1", "target_statute_name": "형법", "target_article": "제334조", "target_paragraph": "제1항", "excerpt": "제334조 제1항", "start_char": 0, "end_char": 8},
            {"source_candidate_id": "P1", "target_statute_name": "민법", "target_article": "제999조", "target_paragraph": "제1항", "excerpt": "제999조 제1항", "start_char": 9, "end_char": 17},
        ])
        ambiguous_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조 제1항 및 민법 제999조 제1항", "query_terms": ["제1항"], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            ambiguous_anchor, ambiguous_errors,
        )
        self.assertTrue(any("request-scoped" in error for error in ambiguous_errors))

    def test_anchor_aware_statute_suffix_parsing_and_wrong_law_rejection(self):
        anchor = {
            "normalized_question": "질문의 법률 적용을 판단하라.",
            "seen_provision_ids": ["P1"],
            "candidate_cross_references": [
                {"source_candidate_id": "P1", "target_statute_name": "형법", "target_article": "제333조", "excerpt": "제333조", "start_char": 0, "end_char": 4},
                {"source_candidate_id": "P1", "target_statute_name": "국민체육진흥법", "target_article": "제48조", "target_paragraph": "제3항", "excerpt": "제48조 제3항", "start_char": 5, "end_char": 14},
            ],
        }
        allowed_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": "강도죄 형법 제333조",
                "query_terms": ["적용 법률 형법 제333조"],
                "statute_hints": ["형법 제333조"],
                "first_stage_query_text": "형법 제333조",
                "rerank_query_text": "강도죄 형법 제333조",
            }], anchor, allowed_errors,
        )
        self.assertEqual(allowed_errors, [])
        multiword_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": "적용 법률 국민체육진흥법 제48조 제3항",
                "query_terms": ["제3항"],
                "statute_hints": ["국민체육진흥법 제48조"],
                "first_stage_query_text": "국민체육진흥법 제48조",
                "rerank_query_text": "국민체육진흥법 제48조 제3항",
            }], anchor, multiword_errors,
        )
        self.assertEqual(multiword_errors, [])
        paired_law_errors = []
        paired_anchor = dict(anchor, candidate_cross_references=[
            {"source_candidate_id": "P1", "target_statute_name": "형법", "target_article": "제334조", "target_paragraph": "제1항", "excerpt": "제334조 제1항", "start_char": 0, "end_char": 8},
            {"source_candidate_id": "P1", "target_statute_name": "민법", "target_article": "제334조", "excerpt": "제334조", "start_char": 9, "end_char": 14},
        ])
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제334조 제1항과 민법 제334조", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            paired_anchor, paired_law_errors,
        )
        self.assertEqual(paired_law_errors, [])
        compound_subordinate_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "의로기기법 시행규칙 제48조 제2항", "query_terms": ["제2항"], "statute_hints": [], "first_stage_query_text": "의로기기법 시행규칙 제48조", "rerank_query_text": "의로기기법 시행규칙 제48조 제2항"}],
            {"normalized_question": "관련 의로기기법 시행규칙 제48조 제2항의 적용 여부"},
            compound_subordinate_errors,
        )
        self.assertEqual(compound_subordinate_errors, [])
        question_suffix_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "형법 제333조", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            {"normalized_question": "강도죄 형법 제333조 적용 여부"},
            question_suffix_errors,
        )
        self.assertEqual(question_suffix_errors, [])
        substring_alias_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "군형법 제333조", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            {"normalized_question": "강도죄 형법 제333조 적용 여부"},
            substring_alias_errors,
        )
        self.assertTrue(any("statute/article pair lacks" in error for error in substring_alias_errors))
        wrong_law_errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{"query_text": "특별법 제333조", "query_terms": [], "statute_hints": [], "first_stage_query_text": "", "rerank_query_text": ""}],
            anchor, wrong_law_errors,
        )
        self.assertTrue(any("statute/article pair lacks" in error for error in wrong_law_errors))

    def test_gap_anchor_coverage_requires_actual_korean_result_phrase_in_query_terms(self):
        evidence_item = {
            "evidence_item_id": "E1",
            "critical": True,
            "description": (
                "산재 요양 중 산재보험 의료기관에서 발생한 의료사고로 인한 "
                "추가 상해의 업무상 재해 인정 기준"
            ),
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": (
                    "산재 요양 중 산재보험 의료기관에서 발생한 의료사고로 인한 "
                    "추가 상해의 업무상 재해 인정 기준"
                ),
            }],
        }
        self.assertEqual(
            S1_VALIDATOR._trusted_gap_anchor_phrases(evidence_item),
            {"추가 상해"},
        )
        split_term_errors = []
        S1_VALIDATOR.validate_gap_query_terms_anchor_coverage(
            [{
                "evidence_item_id": "E1",
                "query_terms": ["요양 중", "의료사고", "추가", "상해", "업무상 재해"],
            }],
            [evidence_item], {"E1"}, split_term_errors,
        )
        self.assertEqual(split_term_errors, [])
        boundary_errors = []
        S1_VALIDATOR.validate_gap_query_terms_anchor_coverage(
            [
                {"evidence_item_id": "E1", "query_terms": ["추가"]},
                {"evidence_item_id": "E1", "query_terms": ["상해"]},
            ],
            [evidence_item], {"E1"}, boundary_errors,
        )
        self.assertEqual(boundary_errors, [
            "GAP_QUERY_PLAN query_terms omit trusted Korean fact/effect anchors: "
            "evidence_item_id=E1; missing_anchors=추가 상해"
        ])
        covered_errors = []
        S1_VALIDATOR.validate_gap_query_terms_anchor_coverage(
            [{
                "evidence_item_id": "E1",
                "query_terms": ["요양 중", "의료사고", "추가 상해", "업무상 재해"],
            }],
            [evidence_item], {"E1"}, covered_errors,
        )
        self.assertEqual(covered_errors, [])

    def test_gap_anchor_coverage_skips_mixed_language_evidence(self):
        evidence_item = {
            "evidence_item_id": "E1",
            "critical": True,
            "description": "additional injury 추가 상해의 인정 기준",
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": "additional injury 추가 상해의 인정 기준",
            }],
        }
        self.assertEqual(S1_VALIDATOR._trusted_gap_anchor_phrases(evidence_item), set())

    def test_gap_anchor_error_retries_with_literal_query_term(self):
        payload = {
            "run_id": "s1-gap-anchor-retry",
            "normalized_question": "추가 상해의 인정 여부를 판단하라.",
            "next_retrieval_round": 1,
            "legal_issues": [{"issue_id": "I1"}],
            "answer_targets": [{"answer_target_id": "T1"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "evidence_type": "rule",
                "description": (
                    "산재 요양 중 산재보험 의료기관에서 발생한 의료사고로 인한 "
                    "추가 상해의 업무상 재해 인정 기준"
                ),
                "critical": True,
                "answer_target_ids": ["T1"],
                "completion_requirements": [{
                    "requirement_id": "E1-R1",
                    "text": (
                        "산재 요양 중 산재보험 의료기관에서 발생한 의료사고로 인한 "
                        "추가 상해의 업무상 재해 인정 기준"
                    ),
                }],
            }],
            "coverage_assessments": [],
            "missing_evidence_items": [{"evidence_item_id": "E1"}],
            "evidence_conflicts": [],
            "query_history": [],
            "candidate_cross_references": [],
            "seen_provision_ids": [],
            "remaining_request_budget": 2,
        }

        def output(query_terms):
            return {
                "schema_version": "1.0",
                "skill_id": "S1",
                "mode": "GAP_QUERY_PLAN",
                "status": "ok",
                "target_evidence_item_ids": ["E1"],
                "gap_retrieval_requests": [{
                    "request_id": "GRQ-R1-1",
                    "issue_id": "I1",
                    "evidence_item_id": "E1",
                    "query_channel": "sparse_keywords",
                    "query_text": "의료사고 업무상 재해",
                    "query_terms": query_terms,
                    "statute_hints": [],
                    "source_assessment_status": "uncovered",
                }],
            }

        invalid = output(["의료사고", "업무상 재해"])
        corrected = output(["의료사고", "추가 상해", "업무상 재해"])
        prompts = []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid if len(prompts) == 1 else corrected, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2, generator=generator
        )
        result = executor.execute("legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload)
        self.assertEqual(len(prompts), 2)
        self.assertIn("missing_anchors=추가 상해", prompts[1])
        self.assertEqual(result["gap_retrieval_requests"][0]["query_terms"], corrected["gap_retrieval_requests"][0]["query_terms"])

    def test_gap_anchor_split_terms_need_no_retry_with_actual_morphology(self):
        text = "몰수·추징의 시효 기간에 관한 규정"
        evidence_item = {
            "evidence_item_id": "E3", "issue_id": "I3", "evidence_type": "limitation",
            "description": text, "critical": True, "answer_target_ids": ["T3"],
            "completion_requirements": [{"requirement_id": "E3-R1", "text": text}],
        }
        self.assertEqual(S1_VALIDATOR._trusted_gap_anchor_phrases(evidence_item), {"시효 기간"})
        payload = {
            "run_id": "s1-gap-anchor-split", "normalized_question": "시효를 설명하라.",
            "next_retrieval_round": 1, "legal_issues": [{"issue_id": "I3"}],
            "answer_targets": [{"answer_target_id": "T3"}],
            "required_evidence_items": [evidence_item], "coverage_assessments": [],
            "missing_evidence_items": [{"evidence_item_id": "E3"}],
            "evidence_conflicts": [], "query_history": [],
            "candidate_cross_references": [], "seen_provision_ids": [],
            "remaining_request_budget": 2,
        }
        response = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "target_evidence_item_ids": ["E3"],
            "gap_retrieval_requests": [{
                "request_id": "GRQ-R1-1", "issue_id": "I3", "evidence_item_id": "E3",
                "query_channel": "sparse_keywords", "query_text": "몰수 추징 시효 기간",
                "query_terms": ["몰수", "추징", "시효", "기간"], "statute_hints": [],
                "source_assessment_status": "uncovered",
            }],
        }
        prompts = []
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2,
            generator=lambda prompt: prompts.append(prompt) or json.dumps(response, ensure_ascii=False),
        )
        result = executor.execute("legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(result["gap_retrieval_requests"][0]["query_terms"], response["gap_retrieval_requests"][0]["query_terms"])

if __name__ == "__main__":
    unittest.main()
