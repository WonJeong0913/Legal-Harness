import copy
import importlib.util
import json
import unittest
from pathlib import Path

import jsonschema

from harness.contracts import (
    AnswerMode,
    AnswerTarget,
    CandidateProvision,
    CompletionRequirement,
    LegalIssue,
    RequiredEvidenceItem,
)
from harness.runner import HarnessRunner
from harness.run_state import RunState
from harness.state_update import apply_coverage_assessment
from harness.validation import ValidationError, validate_answer_draft, validate_coverage_assessment
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


def _load_s3_validator():
    path = ROOT / "skills" / "grounded_legal_answer_generation" / "scripts" / "validate_output.py"
    spec = importlib.util.spec_from_file_location("c11_s3_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S3_VALIDATOR = _load_s3_validator()


def _candidate(provision_id, text):
    return CandidateProvision(
        provision_id=provision_id,
        statute_name="소득세법 시행령",
        provision_text=text,
        issue_id="I1",
        source_request_id="RQ1",
        retrieval_round=1,
        first_stage_score=1.0,
        fusion_rank=1,
        rerank_score=1.0,
    )


def _card_raw_payload(*, include_card=True, second_status="covered", p2_role="CORE"):
    p2_text = (
        "국외에서 근로를 제공하여 받는 보수는 월 100만원까지 비과세한다. "
        "다만 원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우 월 500만원까지 비과세한다."
    )
    condition = {
        "kind": "alternative_outcome",
        "answer_target_id": "T2",
        "condition_text": "원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우",
        "outcome_text": "월 500만원",
        "source_provision_id": "P2",
    }
    status_fields = {
        "covered": {
            "status": "covered",
            "partial_kind": "not_applicable",
            "missing_aspects": [],
            "legal_status": "covered",
            "applicability_status": "direct",
            "gap_type": "none",
            "governing_legal_regime": "direct_entailment",
            "criterion_status": "satisfied",
        },
        "partial": {
            "status": "partially_covered",
            "partial_kind": "factual_condition",
            "missing_aspects": ["E2-R1"],
            "legal_status": "covered",
            "applicability_status": "conditional",
            "gap_type": "missing_fact",
            "governing_legal_regime": "direct_entailment",
            "criterion_status": "partially_satisfied",
        },
    }[second_status]
    second = {
        "evidence_item_id": "E2",
        "status": status_fields["status"],
        "linked_provision_ids": ["P2"],
        "rationale": "국외 근로소득 한도를 직접 정한다.",
        "partial_kind": status_fields["partial_kind"],
        "missing_aspects": status_fields["missing_aspects"],
        "legal_status": status_fields["legal_status"],
        "applicability_status": status_fields["applicability_status"],
        "gap_type": status_fields["gap_type"],
        "governing_legal_regime": status_fields["governing_legal_regime"],
        "criterion_results": [{
            "requirement_id": "E2-R1",
            "status": status_fields["criterion_status"],
            "linked_provision_ids": ["P2"],
            "rationale": "일반 한도와 특례 한도를 정한다.",
            **({"public_material_conditions": [condition]} if include_card else {}),
        }],
    }
    return {
        "evidence_links": [
            {
                "issue_id": "I1", "evidence_item_id": "E1", "provision_id": "P1",
                "support_spans": [{"start_char": 0, "end_char": 5}], "assessment": "accepted",
                "role": "CORE", "condition": "", "rationale": "육아휴직수당 한도",
            },
            {
                "issue_id": "I1", "evidence_item_id": "E2", "provision_id": "P2",
                "support_spans": [{"start_char": 0, "end_char": 5}], "assessment": "accepted",
                "role": p2_role, "condition": "", "rationale": "국외 근로소득 한도",
            },
        ],
        "coverage_assessments": [
            {
                "evidence_item_id": "E1", "status": "covered", "linked_provision_ids": ["P1"],
                "rationale": "육아휴직수당 한도를 직접 정한다.", "partial_kind": "not_applicable",
                "missing_aspects": [], "legal_status": "covered", "applicability_status": "direct",
                "gap_type": "none", "governing_legal_regime": "direct_entailment",
                "criterion_results": [{
                    "requirement_id": "E1-R1", "status": "satisfied",
                    "linked_provision_ids": ["P1"], "rationale": "월 150만원 한도",
                }],
            },
            second,
        ],
        "evidence_conflicts": [],
    }


def _card_state(*, include_card=True, second_status="covered", p2_role="CORE"):
    state = RunState(question="국외 근로소득 비과세 한도는?", normalized_question="국외 근로소득 비과세 한도는?", run_id="c11-card")
    state.legal_issues = [LegalIssue("I1", "비과세 한도")]
    state.answer_targets = [
        AnswerTarget("T1", "육아휴직수당 한도", "한도", "amount_or_limit"),
        AnswerTarget("T2", "국외 근로소득 한도", "한도", "amount_or_limit"),
    ]
    state.required_evidence_items = [
        RequiredEvidenceItem("E1", "I1", "rule", "육아휴직수당 비과세 한도", True, answer_target_ids=["T1"], completion_requirements=[CompletionRequirement("E1-R1", "월 한도")]),
        RequiredEvidenceItem("E2", "I1", "rule", "국외 근로소득 비과세 한도", True, answer_target_ids=["T2"], completion_requirements=[CompletionRequirement("E2-R1", "일반 및 특례 월 한도")]),
    ]
    state.candidate_provisions = [
        _candidate("P1", "육아휴직수당은 월 150만원까지 비과세한다."),
        _candidate("P2", "국외에서 근로를 제공하여 받는 보수는 월 100만원까지 비과세한다. 다만 원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우 월 500만원까지 비과세한다."),
    ]
    links, assessments, conflicts = validate_coverage_assessment(
        _card_raw_payload(include_card=include_card, second_status=second_status, p2_role=p2_role), state
    )
    apply_coverage_assessment(state, links, assessments, conflicts)
    state.answer_mode = AnswerMode.FULL
    state.answered_target_ids = ["T1", "T2"]
    return state


def _s3_input(state):
    payload = HarnessRunner(None, None, None)._answer_payload(state)
    executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture", generator=lambda _: "{}")
    return executor._build_skill_input("grounded_legal_answer_generation", "GENERATE_ANSWER", payload)


def _output_for_input(input_data, *, include_material=True, material_role="conclusion", material_target="T2", material_value="월 500만원", material_source=None):
    by_source = {
        provision.get("source_provision_id", provision["provision_id"]): provision
        for provision in input_data["accepted_provisions"]
    }
    p1, p2 = by_source["P1"], by_source["P2"]
    material_id = input_data["public_material_conditions"][0]["material_id"] if input_data["public_material_conditions"] else None
    c1 = {
        "claim_id": "C1", "text": "육아휴직수당은 월 150만원까지 비과세입니다.",
        "claim_type": "legal_rule", "applicability": "direct", "answer_target_ids": ["T1"],
        "citation_required": True, "public_role": "conclusion",
    }
    c2 = {
        "claim_id": "C2",
        "text": "국외 근로 보수는 월 100만원까지이고, 원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우 %s까지 비과세입니다." % material_value,
        "claim_type": "legal_rule", "applicability": "direct", "answer_target_ids": [material_target],
        "citation_required": True, "public_role": material_role,
        **({"public_material_condition_ids": [material_id]} if include_material and material_id else {}),
    }
    citations = [
        {"citation_id": "CT1", "claim_id": "C1", "provision_id": p1["provision_id"], "quoted_text": p1["text"], "support_description": "월 한도", "answer_marker": "[CT1]"},
        {"citation_id": "CT2", "claim_id": "C2", "provision_id": (material_source or p2)["provision_id"], "quoted_text": (material_source or p2)["text"], "support_description": "국외 근로 한도", "answer_marker": "[CT2]"},
    ]
    answer = "%s[CT1]\n%s[CT2]" % (c1["text"], c2["text"]) if material_role == "conclusion" else "%s[CT1]" % c1["text"]
    return {
        "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER", "status": "ok",
        "run_id": input_data["run_id"], "answer": answer, "claims": [c1, c2],
        "claim_citations": citations, "assumptions": [], "limitations": [],
    }


class C11MaterialConditionCardTests(unittest.TestCase):
    def test_qa180_shape_transports_harness_derived_card_and_passes(self):
        state = _card_state()
        card = state.coverage_assessments[1].criterion_results[0].public_material_conditions[0]
        self.assertEqual(card.material_id, "E2-R1-M1")
        input_data = _s3_input(state)
        self.assertEqual([card["material_id"] for card in input_data["public_material_conditions"]], ["E2-R1-M1"])
        output = _output_for_input(input_data)
        self.assertEqual(S3_VALIDATOR.validate(output, input_data), [])
        self.assertLessEqual(len(output["answer"]), 800)
        draft = validate_answer_draft(output, state)
        self.assertEqual(draft.claims[1].public_material_condition_ids, ["E2-R1-M1"])
        self.assertEqual(len([claim for claim in output["claims"] if claim["public_role"] == "conclusion"]), 2)

    def test_raw_s3_transport_preserves_material_id_through_normalization(self):
        state = _card_state()
        input_data = _s3_input(state)
        output = _output_for_input(input_data)
        raw = copy.deepcopy(output)
        raw.pop("run_id")
        raw.pop("answer")
        for citation in raw["claim_citations"]:
            citation.pop("citation_id")
            citation.pop("quoted_text")
            citation.pop("answer_marker")
        schema_path = ROOT / "skills" / "grounded_legal_answer_generation" / "references" / "compact_output.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(raw)
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture", generator=lambda _: "{}")
        normalized = executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", input_data, raw
        )
        self.assertEqual(
            normalized["claims"][1]["public_material_condition_ids"], ["E2-R1-M1"]
        )
        self.assertEqual(S3_VALIDATOR.validate(normalized, input_data), [])

    def test_qa180_omission_assumption_audit_wrong_target_value_and_source_fail(self):
        input_data = _s3_input(_card_state())
        omitted = _output_for_input(input_data, include_material=False)
        self.assertTrue(any("exactly one conclusion claim" in error for error in S3_VALIDATOR.validate(omitted, input_data)))
        assumption_only = _output_for_input(input_data, include_material=False)
        with self.assertRaisesRegex(ValidationError, "exactly one conclusion claim"):
            validate_answer_draft(omitted, _card_state())

        assumption_only["assumptions"] = [{"code": "A1", "message": "원양어업 선박이면 월 500만원"}]
        self.assertTrue(any("exactly one conclusion claim" in error for error in S3_VALIDATOR.validate(assumption_only, input_data)))
        audit_only = _output_for_input(input_data, material_role="audit")
        self.assertTrue(any("material condition" in error for error in S3_VALIDATOR.validate(audit_only, input_data)))
        wrong_target = _output_for_input(input_data, material_target="T1")
        self.assertTrue(any("not rendered" in error for error in S3_VALIDATOR.validate(wrong_target, input_data)))
        wrong_value = _output_for_input(input_data, material_value="월 400만원")
        self.assertTrue(any("not rendered" in error for error in S3_VALIDATOR.validate(wrong_value, input_data)))
        p1 = next(item for item in input_data["accepted_provisions"] if item.get("source_provision_id", item["provision_id"]) == "P1")
        wrong_source = _output_for_input(input_data, material_source=p1)
        self.assertTrue(any("not rendered" in error for error in S3_VALIDATOR.validate(wrong_source, input_data)))

    def test_qa26_direct_concise_no_card_path_is_accepted(self):
        state = _card_state(include_card=False)
        state.answer_targets = [state.answer_targets[0]]
        state.required_evidence_items = [state.required_evidence_items[0]]
        state.candidate_provisions = [state.candidate_provisions[0]]
        state.evidence_links = [state.evidence_links[0]]
        state.coverage_assessments = [state.coverage_assessments[0]]
        state.answered_target_ids = ["T1"]
        input_data = _s3_input(state)
        self.assertNotIn("public_material_conditions", input_data)
        p1 = input_data["accepted_provisions"][0]
        output = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER",
            "status": "ok", "run_id": input_data["run_id"],
            "answer": "육아휴직수당은 월 150만원까지 비과세입니다.[CT1]",
            "claims": [{
                "claim_id": "C1", "text": "육아휴직수당은 월 150만원까지 비과세입니다.",
                "claim_type": "legal_rule", "applicability": "direct",
                "answer_target_ids": ["T1"], "citation_required": True,
                "public_role": "conclusion",
            }],
            "claim_citations": [{
                "citation_id": "CT1", "claim_id": "C1", "provision_id": p1["provision_id"],
                "quoted_text": p1["text"], "support_description": "월 한도",
                "answer_marker": "[CT1]",
            }],
            "assumptions": [], "limitations": [],
        }
        self.assertEqual(S3_VALIDATOR.validate(output, input_data), [])
        self.assertNotIn("public_material_condition_ids", output["claims"][0])
        self.assertEqual(len(output["claims"]), 1)
        self.assertLessEqual(len(output["answer"]), 800)

    def test_qa653_partial_and_conditional_cards_are_rejected_at_s2(self):
        state = _card_state(include_card=False)
        with self.assertRaisesRegex(ValidationError, "public material conditions require"):
            validate_coverage_assessment(_card_raw_payload(second_status="partial"), state)

    def test_limited_deferred_target_has_no_card_and_no_rescue(self):
        state = _card_state()
        state.answer_mode = AnswerMode.LIMITED
        state.answered_target_ids = ["T1"]
        state.deferred_target_ids = ["T2"]
        input_data = _s3_input(state)
        self.assertNotIn("public_material_conditions", input_data)
        p1 = next(item for item in input_data["accepted_provisions"] if item.get("source_provision_id", item["provision_id"]) == "P1")
        output = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER", "status": "ok", "run_id": input_data["run_id"],
            "answer": "육아휴직수당은 월 150만원까지 비과세입니다.[CT1]",
            "claims": [{"claim_id": "C1", "text": "육아휴직수당은 월 150만원까지 비과세입니다.", "claim_type": "legal_rule", "applicability": "direct", "answer_target_ids": ["T1"], "citation_required": True, "public_role": "conclusion"}],
            "claim_citations": [{"citation_id": "CT1", "claim_id": "C1", "provision_id": p1["provision_id"], "quoted_text": p1["text"], "support_description": "월 한도", "answer_marker": "[CT1]"}],
            "assumptions": [], "limitations": [{"code": "L1", "message": "T2는 답변 범위에서 유보한다."}],
        }
        self.assertEqual(S3_VALIDATOR.validate(output, input_data), [])

    def test_auxiliary_source_cannot_create_card(self):
        state = _card_state(include_card=False)
        with self.assertRaisesRegex(ValidationError, "accepted CORE provisions"):
            validate_coverage_assessment(_card_raw_payload(p2_role="SUPPLEMENTAL"), state)


if __name__ == "__main__":
    unittest.main()
