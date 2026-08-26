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
from harness.runner import HarnessConfig, HarnessRunner
from harness.validation import ValidationError, validate_coverage_assessment
from retrieval.corpus import InMemoryProvisionCorpus, ProvisionDocument
from runtime.local_ollama_executor import LocalOllamaSkillExecutor, SKILL_IDS
from tools.validate_citation_integrity import CitationIntegrityChecker


ROOT = Path(__file__).resolve().parents[1]
S2 = "provision_coverage_assessment"
S1 = "legal_issue_and_query_planning"
S3 = "grounded_legal_answer_generation"


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


class RecordingLocalExecutor:
    """Keep the real local adapter while recording only its dispatch contract."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    def execute(self, skill_name, entry_point, payload):
        self.calls.append((skill_name, entry_point, copy.deepcopy(payload)))
        return self.delegate.execute(skill_name, entry_point, payload)


class OneProvisionRetriever:
    """CPU-only retrieval fixture with one valid, request-scoped candidate."""

    def __init__(self):
        self.calls = []

    def retrieve(self, requests, retrieval_round, *, critical_evidence_item_ids=()):
        self.calls.append((list(requests), retrieval_round, list(critical_evidence_item_ids)))
        return [
            CandidateProvision(
                "P1",
                "예시법 제1조",
                "법률 요건을 정한다.",
                requests[0].issue_id,
                requests[0].request_id,
                retrieval_round,
                1.0,
                1,
                1.0,
            )
        ]


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

    def test_legacy_projection_garbage_is_bounded_invalid_without_changing_axes(self):
        payload = s2_input()
        for field in ("status", "partial_kind", "governing_legal_regime"):
            for malformed in ([], {}):
                with self.subTest(field=field, malformed_type=type(malformed).__name__):
                    raw = raw_s2("covered", "direct", "none", links=[core_link()])
                    raw["coverage_assessments"][0][field] = malformed
                    normalized = self.normalize(raw, payload)
                    assessment = normalized["coverage_assessments"][0]
                    self.assertEqual(
                        (assessment["legal_status"], assessment["applicability_status"], assessment["gap_type"]),
                        ("covered", "direct", "none"),
                    )
                    self.assertEqual(assessment["status"], "covered")
                    diagnostic = normalized.projection_diagnostics[0]
                    self.assertEqual(
                        diagnostic.raw_projection_disposition[field]["value"], "invalid"
                    )
                    self.assertEqual(
                        diagnostic.raw_projection_disposition["disposition"], "suppressed"
                    )
                    self.assertEqual(self.executor._validators[S2](normalized, payload), [])

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

    def test_s2_adapter_overwrites_model_private_diagnostic_spoof(self):
        raw = raw_s2(
            "covered", "direct", "none", links=[core_link(provision_id="C001")]
        )
        raw["_harness_s2_projection_diagnostics"] = [{
            "evidence_item_id": "SPOOF-MARKER",
            "secret": "model-owned text must never reach harness diagnostics",
        }]
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture", generator=lambda _: json.dumps(raw)
        )
        result = executor.execute(
            S2,
            "ASSESS_COVERAGE",
            {
                "run_id": "spoof-c06",
                "normalized_question": "법률 요건은?",
                "legal_issues": [{"issue_id": "I1", "description": "법률 요건"}],
                "required_evidence_items": [{
                    "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                    "description": "법률 요건", "critical": True,
                }],
                "candidate_provisions": [{
                    "provision_id": "P1", "statute_name": "예시법 제1조",
                    "provision_text": "법률 요건을 정한다.",
                }],
            },
        )
        diagnostics = result["_harness_s2_projection_diagnostics"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["evidence_item_id"], "E1")
        self.assertEqual(diagnostics[0]["derived_status"], "covered")
        serialized = json.dumps(diagnostics, ensure_ascii=False)
        self.assertNotIn("SPOOF-MARKER", serialized)
        self.assertNotIn("model-owned text", serialized)

    def test_full_runner_uses_s1_s2_s3_and_projection_trace_is_preapply_only(self):
        initial = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "INITIAL_PLAN",
            "status": "ok", "run_id": "model-will-be-overwritten",
            "answer_targets": [{
                "answer_target_id": "T1", "question_anchor": "법률 요건은?",
                "requested_output": "적용 요건", "answer_type": "legal_rule",
            }],
            "legal_issues": [{
                "issue_id": "I1", "issue_statement": "법률 요건 적용",
                "decision_question": "법률 요건은 무엇인가", "importance": "critical",
            }],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                "description": "법률 요건", "critical": True,
                "completion_criteria": "법률 요건", "necessity_reason": "답변의 핵심 근거",
                "answer_target_ids": ["T1"], "scope_source": "explicit_question",
                "completion_requirements": [{
                    "requirement_id": "E1-R1", "text": "법률 요건의 직접 근거",
                }],
            }],
            "retrieval_requests": [{
                "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "provision_style", "query_text": "법률 요건",
                "query_terms": ["법률 요건"], "statute_hints": [],
                "rationale": "핵심 요건 조문 검색",
            }],
        }
        covered = raw_s2(
            "covered",
            "direct",
            "none",
            links=[core_link(provision_id="C001")],
            criterion_results=[{
                "requirement_id": "E1-R1", "status": "satisfied",
                "linked_provision_ids": ["C001"], "rationale": "직접 근거",
                "direct_entailment": {
                    "regulated_subject_or_act": "matched",
                    "outcome_changing_qualifiers": "matched",
                    "legal_effect": "matched",
                    "procedure_or_remedy_path": "not_applicable",
                    "rationale": "직접 적용",
                },
            }],
        )
        covered["_harness_s2_projection_diagnostics"] = [{
            "evidence_item_id": "SPOOF-MARKER",
            "secret": "model-owned text must not reach trace events",
        }]
        answer = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER",
            "status": "ok", "run_id": "model-will-be-overwritten",
            "answer": "법률 요건이 적용됩니다.",
            "claims": [{
                "claim_id": "claim", "text": "법률 요건이 적용됩니다.",
                "claim_type": "legal_rule", "applicability": "direct",
                "citation_required": True, "answer_target_ids": ["T1"],
                "public_role": "conclusion",
            }],
            "claim_citations": [{
                "claim_id": "claim", "provision_id": "P1", "support_description": "직접 근거",
            }],
            "assumptions": [], "limitations": [],
        }

        def generator(prompt):
            if "ENTRY POINT: INITIAL_PLAN" in prompt:
                return json.dumps(initial)
            if "ENTRY POINT: ASSESS_COVERAGE" in prompt:
                return json.dumps(covered)
            if "ENTRY POINT: GENERATE_ANSWER" in prompt:
                return json.dumps(answer)
            raise AssertionError("unexpected test fixture prompt")

        trace = CaptureTrace()
        executor = RecordingLocalExecutor(
            LocalOllamaSkillExecutor(ROOT / "skills", "fixture", generator=generator)
        )
        retriever = OneProvisionRetriever()
        runner = HarnessRunner(
            executor,
            retriever,
            CitationIntegrityChecker(InMemoryProvisionCorpus([
                ProvisionDocument("P1", "예시법 제1조", "법률 요건을 정한다.")
            ])),
            config=HarnessConfig(total_retrieval_rounds=3, total_retrieval_requests=9),
            trace_sink=trace,
        )
        outcome = runner.run("법률 요건은?", run_id="c06-full-flow")

        self.assertEqual(outcome.status.value, "ANSWER")
        self.assertEqual(
            [(skill, entry) for skill, entry, _ in executor.calls],
            [(S1, "INITIAL_PLAN"), (S2, "ASSESS_COVERAGE"), (S3, "GENERATE_ANSWER")],
        )
        self.assertEqual(list(SKILL_IDS), [S1, S2, S3])
        self.assertEqual(len(retriever.calls), 1)

        events = [record["event"] for record in trace.records]
        initial_index = events.index("INITIAL_PLAN_VALIDATED")
        retrieval_index = events.index("INITIAL_RETRIEVAL_VALIDATED")
        projection_index = events.index("S2_LEGACY_PROJECTION_DERIVED")
        coverage_index = events.index("COVERAGE_ASSESSMENT_VALIDATED")
        terminal_index = events.index("RUN_COMPLETED")
        self.assertLess(initial_index, retrieval_index)
        self.assertLess(retrieval_index, projection_index)
        self.assertLess(projection_index, coverage_index)
        self.assertLess(coverage_index, terminal_index)
        self.assertNotIn("SPOOF-MARKER", json.dumps(trace.records, ensure_ascii=False))
        self.assertNotIn("model-owned text", json.dumps(trace.records, ensure_ascii=False))

        retrieval_trace = trace.records[retrieval_index]
        projection_trace = trace.records[projection_index]
        coverage_trace = trace.records[coverage_index]
        policy_trace = trace.records[events.index("POLICY_DECISION")]
        self.assertEqual(projection_trace["action_trace_length"], retrieval_trace["action_trace_length"])
        self.assertEqual(coverage_trace["action_trace_length"], projection_trace["action_trace_length"] + 1)
        s3_payload = executor.calls[-1][2]
        self.assertEqual(s3_payload["state_version"], policy_trace["action_trace_length"])
        action_events = [item.event for item in outcome.state.action_trace]
        self.assertNotIn("S2_LEGACY_PROJECTION_DERIVED", action_events)
        self.assertEqual(action_events[-2:], ["ANSWER_DRAFT_VALIDATED", "CITATION_INTEGRITY_PASS"])

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

    def test_forged_unhashable_private_diagnostic_is_clean_invalid_skill_output(self):
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
        local = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture", generator=lambda _: json.dumps(raw)
        )
        response = local.execute(
            S2,
            "ASSESS_COVERAGE",
            {
                "run_id": "forged-private-c06",
                "normalized_question": "법률 요건은?",
                "legal_issues": [{"issue_id": "I1", "description": "법률 요건"}],
                "required_evidence_items": [{
                    "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                    "description": "법률 요건", "critical": True,
                    "completion_criteria": "법률 요건",
                    "completion_requirements": [{"requirement_id": "E1-R1", "text": "법률 요건"}],
                }],
                "candidate_provisions": [{
                    "provision_id": "P1", "statute_name": "예시법 제1조",
                    "provision_text": "법률 요건을 정한다.",
                }],
            },
        )

        class StaticExecutor:
            def __init__(self, value):
                self.value = value

            def execute(self, skill_name, entry_point, payload):
                return copy.deepcopy(self.value)

        def coverage_state():
            state = RunState(
                question="법률 요건은?", normalized_question="법률 요건은?",
                run_id="forged-private-c06", total_round_budget=3,
                remaining_round_budget=2, remaining_request_budget=8,
                phase=Phase.RETRIEVING_INITIAL,
            )
            state.legal_issues = [LegalIssue("I1", "법률 요건")]
            state.required_evidence_items = [RequiredEvidenceItem(
                "E1", "I1", "rule", "법률 요건", True,
                completion_criteria="법률 요건",
                completion_requirements=[CompletionRequirement("E1-R1", "법률 요건")],
            )]
            state.candidate_provisions = [CandidateProvision(
                "P1", "예시법 제1조", "법률 요건을 정한다.", "I1", "RQ1", 1, 1.0, 1, 1.0,
            )]
            state.query_history = [RetrievalRequest(
                "RQ1", "I1", "E1", "provision_style", "법률 요건"
            )]
            return state

        mutations = {
            "source": lambda diagnostic: diagnostic["raw_projection_disposition"]["status"].update({"source": []}),
            "value": lambda diagnostic: diagnostic["raw_projection_disposition"]["status"].update({"value": {}}),
            "ledger_shape": lambda diagnostic: diagnostic["raw_projection_disposition"]["missing_evidence_items"].update({"shape": []}),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                forged = copy.deepcopy(response)
                mutate(forged["_harness_s2_projection_diagnostics"][0])
                runner = HarnessRunner(
                    StaticExecutor(forged),
                    retriever=object(),
                    citation_validator=CitationIntegrityChecker(
                        InMemoryProvisionCorpus([])
                    ),
                )
                failure = runner._assess_coverage(coverage_state())
                self.assertIsNotNone(failure)
                self.assertEqual(failure.status.value, "EXECUTION_FAILURE")
                self.assertEqual(failure.termination_reason.value, "INVALID_SKILL_OUTPUT")

    def test_exact_three_skill_order_is_unchanged(self):
        expected = [
            "legal_issue_and_query_planning",
            "provision_coverage_assessment",
            "grounded_legal_answer_generation",
        ]
        self.assertEqual(list(SKILL_IDS), expected)
        self.assertEqual(
            sorted(path.name for path in (ROOT / "skills").iterdir() if path.is_dir()),
            sorted(expected),
        )


if __name__ == "__main__":
    unittest.main()
