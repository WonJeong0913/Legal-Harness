import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.contracts import (
    CandidateProvision,
    CompletionRequirement,
    LegalIssue,
    Phase,
    RequiredEvidenceItem,
    RetrievalRequest,
)
from harness.interfaces import SkillExecutionError
from harness.run_state import RunState
from harness.runner import HarnessRunner
from harness.validation import ValidationError, validate_coverage_assessment
from retrieval.corpus import InMemoryProvisionCorpus, ProvisionDocument
from runtime.local_ollama_executor import LocalOllamaSkillExecutor, SKILL_IDS
from tools.validate_citation_integrity import CitationIntegrityChecker


ROOT = Path(__file__).resolve().parents[1]
S2 = "provision_coverage_assessment"


def s2_input(*, critical=True, requirements=False, question="axis fixture"):
    evidence = {
        "evidence_item_id": "E1",
        "issue_id": "I1",
        "evidence_type": "rule",
        "description": "법률 요건",
        "critical": critical,
        "completion_criteria": "법률 요건",
    }
    if requirements:
        evidence["completion_requirements"] = [
            {"requirement_id": "E1-R1", "text": "법률 요건 A"},
            {"requirement_id": "E1-R2", "text": "법률 요건 B"},
        ]
    return {
        "schema_version": "1.0",
        "mode": "ASSESS_COVERAGE",
        "run_id": "c06-axis-fixture",
        "normalized_question": question,
        "legal_issues": [{"issue_id": "I1", "description": "법률 요건"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": [evidence],
        "candidate_provisions": [
            {
                "provision_id": "P1",
                "source_provision_id": "P1",
                "statute_name": "예시법 제1조",
                "text": "법률 요건을 정한다.",
            }
        ],
        "prior_coverage_assessments": [],
    }


def raw_s2(
    legal_status,
    applicability_status,
    gap_type,
    *,
    links=None,
    criterion_results=None,
    legacy=None,
):
    if links is None:
        links = []
    assessment = {
        "evidence_item_id": "E1",
        "rationale": "축 기반 판정",
        "legal_status": legal_status,
        "applicability_status": applicability_status,
        "gap_type": gap_type,
        "criterion_results": criterion_results or [],
    }
    if legacy:
        assessment.update(legacy)
    return {
        "schema_version": "1.0",
        "skill_id": "S2",
        "mode": "ASSESS_COVERAGE",
        "status": "ok",
        "evidence_links": links,
        "coverage_assessments": [assessment],
    }


def core_link(relation="supports", role="CORE", provision_id="P1"):
    return {
        "evidence_item_id": "E1",
        "provision_id": provision_id,
        "relation": relation,
        "role": role,
        "rationale": "공급된 요건의 근거",
    }


class CaptureTrace:
    def __init__(self):
        self.records = []

    def record(self, event, state, **details):
        self.records.append(
            {
                "event": event,
                "details": copy.deepcopy(details),
                "action_trace_length": len(state.action_trace),
                "retrieval_rounds_used": state.retrieval_rounds_used,
                "remaining_round_budget": state.remaining_round_budget,
                "remaining_request_budget": state.remaining_request_budget,
                "query_history": [request.request_id for request in state.query_history],
                "candidate_ids": [candidate.provision_id for candidate in state.candidate_provisions],
                "authorized": sorted(state.accepted_provision_ids),
                "core": sorted(state.core_accepted_provision_ids),
            }
        )


class C06S2AxisCanonicalTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture", generator=lambda _: "{}")

    def normalize(self, raw, payload):
        return self.executor._normalize_harness_owned_fields(
            S2, "ASSESS_COVERAGE", payload, copy.deepcopy(raw)
        )

    def test_full_allowed_tuple_matrix_and_noncritical_scope_excess(self):
        cases = [
            (("covered", "direct", "none"), True, [core_link()], "covered", "not_applicable", "direct_entailment", []),
            (("covered", "conditional", "missing_fact"), True, [core_link()], "partially_covered", "factual_condition", "direct_entailment", ["E1"]),
            (("partially_covered", "not_assessed", "missing_statute"), True, [core_link()], "partially_covered", "legal_support_gap", "not_direct_entailment", ["E1"]),
            (("uncovered", "not_assessed", "missing_statute"), True, [], "uncovered", "not_applicable", "not_direct_entailment", ["E1"]),
            (("conflicting", "not_assessed", "conflict"), True, [core_link(), core_link("conflicts")], "conflicting", "not_applicable", "not_direct_entailment", ["E1"]),
            (("uncovered", "not_assessed", "scope_excess"), False, [], "uncovered", "not_applicable", "not_direct_entailment", ["E1"]),
        ]
        for axes, critical, links, status, partial_kind, governing, missing in cases:
            with self.subTest(axes=axes, critical=critical):
                payload = s2_input(critical=critical)
                normalized = self.normalize(raw_s2(*axes, links=links), payload)
                assessment = normalized["coverage_assessments"][0]
                self.assertEqual(assessment["status"], status)
                self.assertEqual(assessment["partial_kind"], partial_kind)
                self.assertEqual(assessment["governing_legal_regime"], governing)
                self.assertEqual(
                    [item["evidence_item_id"] for item in normalized["missing_evidence_items"]],
                    missing,
                )
                self.assertEqual(self.executor._validators[S2](normalized, payload), [])

    def test_partial_malformed_unsupported_and_critical_scope_axes_fail_closed(self):
        payload = s2_input(critical=True)
        failures = [
            raw_s2("uncovered", "not_assessed", "scope_excess"),
            raw_s2("covered", "direct", "missing_fact"),
            raw_s2("covered", "direct", "not-a-gap"),
            raw_s2("covered", "direct", "none"),
        ]
        del failures[-1]["coverage_assessments"][0]["gap_type"]
        for raw in failures:
            with self.subTest(raw=raw["coverage_assessments"][0]):
                with self.assertRaises(SkillExecutionError):
                    self.normalize(raw, payload)

    def test_canonical_validator_rejects_critical_scope_excess_after_transport(self):
        state = RunState(question="질문", normalized_question="질문", run_id="canonical")
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "법률 요건", True,
        )]
        payload = {
            "evidence_links": [],
            "coverage_assessments": [{
                "evidence_item_id": "E1",
                "status": "uncovered",
                "linked_provision_ids": [],
                "rationale": "비핵심 범위가 아님",
                "partial_kind": "not_applicable",
                "missing_aspects": ["법률 요건"],
                "legal_status": "uncovered",
                "applicability_status": "not_assessed",
                "gap_type": "scope_excess",
                "governing_legal_regime": "not_direct_entailment",
                "criterion_results": [],
            }],
            "evidence_conflicts": [],
        }
        with self.assertRaises(ValidationError):
            validate_coverage_assessment(payload, state)

    def test_qa140_shaped_legacy_conflict_projects_identically_twice(self):
        payload = s2_input(requirements=True)
        raw = raw_s2(
            "covered",
            "conditional",
            "missing_fact",
            links=[core_link()],
            criterion_results=[
                {
                    "requirement_id": "E1-R1",
                    "status": "satisfied",
                    "linked_provision_ids": ["P1"],
                    "rationale": "법률 요건은 충족",
                },
                {
                    "requirement_id": "E1-R2",
                    "status": "partially_satisfied",
                    "linked_provision_ids": ["P1"],
                    "rationale": "사실 조건 확인 필요",
                },
            ],
            legacy={
                "status": "covered",
                "partial_kind": "not_applicable",
                "governing_legal_regime": "not_direct_entailment",
            },
        )
        raw["missing_evidence_items"] = []
        raw["evidence_conflicts"] = [{"description": "ignored legacy ledger"}]
        first = self.normalize(raw, payload)
        second = self.normalize(raw, payload)
        self.assertEqual(dict(first), dict(second))
        assessment = first["coverage_assessments"][0]
        self.assertEqual(assessment["status"], "partially_covered")
        self.assertEqual(assessment["partial_kind"], "factual_condition")
        self.assertEqual(assessment["governing_legal_regime"], "direct_entailment")
        self.assertEqual(assessment["missing_aspects"], ["E1-R2"])
        self.assertEqual(first["missing_evidence_items"][0]["evidence_item_id"], "E1")
        self.assertEqual(first["evidence_conflicts"], [])
        self.assertEqual(self.executor._validators[S2](first, payload), [])
        diagnostic = first.projection_diagnostics[0]
        self.assertEqual(diagnostic.raw_projection_disposition["disposition"], "suppressed")
        self.assertEqual(diagnostic.raw_projection_disposition["status"]["value"], "covered")
        self.assertEqual(diagnostic.raw_projection_disposition["missing_evidence_items"]["count"], 0)

    def test_wrong_criterion_noncore_and_direct_entailment_remain_invalid(self):
        payload = s2_input(requirements=True)
        wrong_criterion = raw_s2(
            "covered", "direct", "none", links=[core_link()],
            criterion_results=[{
                "requirement_id": "E1-R9", "status": "satisfied",
                "linked_provision_ids": ["P1"], "rationale": "잘못된 요건",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "matched",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "형식 검사",
                },
            }],
        )
        noncore = raw_s2(
            "covered", "direct", "none", links=[core_link(role="SUPPLEMENTAL")],
            criterion_results=[{
                "requirement_id": "E1-R1", "status": "satisfied",
                "linked_provision_ids": ["P1"], "rationale": "보조 근거",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "matched",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "형식 검사",
                },
            }, {
                "requirement_id": "E1-R2", "status": "satisfied",
                "linked_provision_ids": ["P1"], "rationale": "보조 근거",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "matched",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "형식 검사",
                },
            }],
        )
        direct_mismatch = raw_s2(
            "covered", "direct", "none", links=[core_link()],
            criterion_results=[{
                "requirement_id": requirement_id, "status": "satisfied",
                "linked_provision_ids": ["P1"], "rationale": "직접 근거",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "mismatch",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "명시적 불일치",
                },
            } for requirement_id in ("E1-R1", "E1-R2")],
        )
        for raw in (wrong_criterion, noncore, direct_mismatch):
            with self.subTest(raw=raw):
                normalized = self.normalize(raw, payload)
                self.assertTrue(self.executor._validators[S2](normalized, payload))

    def test_executor_uses_per_call_diagnostics_sequentially_and_concurrently(self):
        def generator(prompt):
            if "concurrent-covered" in prompt:
                return json.dumps(
                    raw_s2(
                        "covered",
                        "direct",
                        "none",
                        links=[core_link(provision_id="C001")],
                    )
                )
            return json.dumps(raw_s2("uncovered", "not_assessed", "missing_statute"))

        executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture", generator=generator)

        def execute(question):
            payload = {
                "run_id": "run-" + question,
                "normalized_question": question,
                "legal_issues": [{"issue_id": "I1", "description": "법률 요건"}],
                "required_evidence_items": [{
                    "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                    "description": "법률 요건", "critical": True,
                }],
                "candidate_provisions": [{
                    "provision_id": "P1", "statute_name": "예시법 제1조",
                    "provision_text": "법률 요건을 정한다.",
                }],
            }
            return executor.execute(S2, "ASSESS_COVERAGE", payload)

        self.assertEqual(
            execute("sequential-uncovered")["_harness_s2_projection_diagnostics"][0]["derived_status"],
            "uncovered",
        )
        self.assertEqual(
            execute("concurrent-covered")["_harness_s2_projection_diagnostics"][0]["derived_status"],
            "covered",
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, ["concurrent-covered", "concurrent-uncovered"]))
        self.assertEqual(
            [result["_harness_s2_projection_diagnostics"][0]["derived_status"] for result in results],
            ["covered", "uncovered"],
        )

    def test_runner_trace_is_once_per_assessment_and_does_not_mutate_preapply_state(self):
        raw = raw_s2(
            "covered", "direct", "none", links=[core_link(provision_id="C001")],
            criterion_results=[{
                "requirement_id": "E1-R1", "status": "satisfied",
                "linked_provision_ids": ["C001"], "rationale": "직접 근거",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "matched",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "직접 근거",
                },
            }],
        )
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture", generator=lambda _: json.dumps(raw)
        )
        trace = CaptureTrace()
        runner = HarnessRunner(
            executor,
            retriever=object(),
            citation_validator=CitationIntegrityChecker(
                InMemoryProvisionCorpus([ProvisionDocument("P1", "예시법", "법률 요건을 정한다.")])
            ),
            trace_sink=trace,
        )
        state = RunState(
            question="법률 요건은?", normalized_question="법률 요건은?", run_id="trace-c06",
            total_round_budget=3, remaining_round_budget=2, remaining_request_budget=8,
            phase=Phase.RETRIEVING_INITIAL,
        )
        state.legal_issues = [LegalIssue("I1", "법률 요건")]
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "법률 요건", True,
            completion_criteria="법률 요건",
            completion_requirements=[CompletionRequirement("E1-R1", "법률 요건")],
        )]
        state.candidate_provisions = [CandidateProvision(
            "P1", "예시법", "법률 요건을 정한다.", "I1", "RQ1", 1, 1.0, 1, 1.0,
        )]
        state.query_history = [RetrievalRequest("RQ1", "I1", "E1", "provision_style", "법률 요건")]
        baseline = {
            "history": [request.request_id for request in state.query_history],
            "rounds": state.retrieval_rounds_used,
            "round_budget": state.remaining_round_budget,
            "request_budget": state.remaining_request_budget,
            "candidates": [candidate.provision_id for candidate in state.candidate_provisions],
            "authorized": sorted(state.accepted_provision_ids),
            "core": sorted(state.core_accepted_provision_ids),
            "action_trace": len(state.action_trace),
        }
        self.assertIsNone(runner._assess_coverage(state))
        events = [record for record in trace.records if record["event"] == "S2_LEGACY_PROJECTION_DERIVED"]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["details"]["evidence_item_id"], "E1")
        self.assertEqual(event["details"]["derived_status"], "covered")
        self.assertEqual(event["action_trace_length"], baseline["action_trace"])
        self.assertEqual(event["query_history"], baseline["history"])
        self.assertEqual(event["retrieval_rounds_used"], baseline["rounds"])
        self.assertEqual(event["remaining_round_budget"], baseline["round_budget"])
        self.assertEqual(event["remaining_request_budget"], baseline["request_budget"])
        self.assertEqual(event["candidate_ids"], baseline["candidates"])
        self.assertEqual(event["authorized"], baseline["authorized"])
        self.assertEqual(event["core"], baseline["core"])
        self.assertFalse(any(item.event == "S2_LEGACY_PROJECTION_DERIVED" for item in state.action_trace))

    def test_exact_three_skill_order_is_unchanged(self):
        self.assertEqual(
            list(SKILL_IDS),
            [
                "legal_issue_and_query_planning",
                "provision_coverage_assessment",
                "grounded_legal_answer_generation",
            ],
        )


if __name__ == "__main__":
    unittest.main()
