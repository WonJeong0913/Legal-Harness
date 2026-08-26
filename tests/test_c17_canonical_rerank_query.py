import hashlib
import unittest

from harness.canonical_rerank_query import (
    CanonicalRerankQueryValidationError,
    canonicalize_missing_rerank_query,
)
from harness.contracts import (
    AnswerTarget,
    CompletionRequirement,
    QueryChannel,
    RequiredEvidenceItem,
    OutcomeStatus,
    RetrievalRequest,
)
from harness.run_state import RunState
from harness.runner import HarnessConfig, HarnessRunner
from retrieval.corpus import ProvisionDocument
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalHit


class CaptureFirstStage:
    def __init__(self):
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return [
            RetrievalHit(
                document=ProvisionDocument("P1", "테스트법", "원자 요건 근거"),
                score=1.0,
                source_request_id=request.request_id,
            )
        ]


class CaptureReranker:
    def __init__(self):
        self.queries = []

    def rerank(self, query_text, hits, top_k):
        self.queries.append(query_text)
        return [1.0 for _ in hits[:top_k]]


def trusted_inputs(*, override=None, query_text=None):
    target = AnswerTarget(
        answer_target_id="T1",
        question_anchor="신청인이 충족해야 할 원자 요건은 무엇인가",
        requested_output="원자 요건을 항목별로 제시",
        answer_type="legal_elements",
    )
    evidence = RequiredEvidenceItem(
        evidence_item_id="E1",
        issue_id="I1",
        evidence_type="application_requirement",
        description="원자 요건",
        critical=True,
        answer_target_ids=["T1"],
        scope_source="explicit_question",
        completion_requirements=[
            CompletionRequirement("CR2", "신청 주체의 자격"),
            CompletionRequirement("CR1", "제출 기한"),
        ],
    )
    request = RetrievalRequest(
        request_id="RQ-I1-01",
        issue_id="I1",
        evidence_item_id="E1",
        query_channel=QueryChannel.PROVISION_STYLE,
        query_text=query_text or ("배경전문 " * 180) + " 신청 요건",
        query_terms=["요건B", "요건A"],
        statute_hints=["관련법", "관련법 시행규칙"],
        first_stage_query_text="원래 KURE 질의",
        rerank_query_text=override,
    )
    return request, {"E1": evidence}, {"T1": target}


class CanonicalRerankQueryTests(unittest.TestCase):
    def test_qa150_shape_preserves_recall_text_and_canonicalizes_bge_only(self):
        request, evidence, targets = trusted_inputs()
        final_request, audit = canonicalize_missing_rerank_query(
            request, evidence, targets
        )

        self.assertEqual(final_request.query_text, request.query_text)
        self.assertEqual(
            final_request.first_stage_query_text, request.first_stage_query_text
        )
        self.assertIsNone(request.rerank_query_text)
        self.assertEqual(audit["source"], "canonical_missing_only")
        self.assertNotIn("배경전문", final_request.rerank_query_text)
        self.assertIn("[completion_requirements]", final_request.rerank_query_text)
        self.assertIn("제출 기한", final_request.rerank_query_text)
        self.assertIn("신청인이 충족해야 할 원자 요건은 무엇인가", final_request.rerank_query_text)
        self.assertIn("[statute_hints]", final_request.rerank_query_text)
        self.assertIn("[query_terms]", final_request.rerank_query_text)
        self.assertLessEqual(final_request.rerank_query_text.find("[completion_requirements]"), final_request.rerank_query_text.find("[answer_targets]"))
        self.assertLessEqual(final_request.rerank_query_text.find("[answer_targets]"), final_request.rerank_query_text.find("[statute_hints]"))
        self.assertLessEqual(final_request.rerank_query_text.find("[statute_hints]"), final_request.rerank_query_text.find("[query_terms]"))
        encoded = final_request.rerank_query_text.encode("utf-8")
        self.assertEqual(audit["final_rerank_query_sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(audit["final_rerank_query_characters"], len(final_request.rerank_query_text))
        self.assertEqual(audit["final_rerank_query_utf8_bytes"], len(encoded))
        self.assertTrue(audit["canonical_output_within_bounds"])

        repeated, repeated_audit = canonicalize_missing_rerank_query(
            request, evidence, targets
        )
        self.assertEqual(repeated, final_request)
        self.assertEqual(repeated_audit, audit)

        first_stage = CaptureFirstStage()
        reranker = CaptureReranker()
        pipeline = RetrievalPipeline(
            first_stage,
            reranker,
            rerank_pool_k=1,
            final_top_k=1,
            rerank_query_mode="per_request",
        )
        pipeline.retrieve([final_request], retrieval_round=1)
        self.assertEqual(first_stage.requests[0].query_text, "원래 KURE 질의")
        self.assertEqual(first_stage.requests[0].query_terms, [])
        self.assertEqual(reranker.queries, [final_request.rerank_query_text])

    def test_explicit_s1_override_is_never_replaced(self):
        request, evidence, targets = trusted_inputs(override="명시적 S1 BGE 질의")
        final_request, audit = canonicalize_missing_rerank_query(
            request, evidence, targets
        )

        self.assertIs(final_request, request)
        self.assertEqual(final_request.rerank_query_text, "명시적 S1 BGE 질의")
        self.assertEqual(audit["source"], "raw")
        self.assertEqual(
            audit["original_rerank_query_sha256"],
            audit["final_rerank_query_sha256"],
        )

    def test_normalization_order_and_dedup_are_deterministic(self):
        request, evidence, targets = trusted_inputs()
        target = targets["T1"]
        targets["T1"] = AnswerTarget(
            target.answer_target_id,
            "A\u030A   질문",
            "  출력\t형식 ",
            target.answer_type,
        )
        request = RetrievalRequest(
            **{
                **request.__dict__,
                "query_terms": ["용어B", "용어A"],
                "statute_hints": ["힌트B", "힌트A"],
            }
        )
        final_request, _ = canonicalize_missing_rerank_query(
            request, evidence, targets
        )
        self.assertIn("Å 질문", final_request.rerank_query_text)
        self.assertIn("requested_output: 출력 형식", final_request.rerank_query_text)
        self.assertLess(
            final_request.rerank_query_text.find("힌트A"),
            final_request.rerank_query_text.find("힌트B"),
        )
        self.assertLess(
            final_request.rerank_query_text.find("용어A"),
            final_request.rerank_query_text.find("용어B"),
        )

    def test_fail_closed_for_untrusted_empty_or_oversized_structured_material(self):
        request, evidence, targets = trusted_inputs()
        with self.assertRaises(CanonicalRerankQueryValidationError):
            canonicalize_missing_rerank_query(request, {"E1": object()}, targets)

        empty_evidence = RequiredEvidenceItem(
            **{**evidence["E1"].__dict__, "completion_requirements": []}
        )
        with self.assertRaises(CanonicalRerankQueryValidationError):
            canonicalize_missing_rerank_query(
                request, {"E1": empty_evidence}, targets
            )

        with self.assertRaises(CanonicalRerankQueryValidationError):
            canonicalize_missing_rerank_query(
                request, evidence, targets, max_characters=20
            )

        with self.assertRaises(CanonicalRerankQueryValidationError):
            canonicalize_missing_rerank_query(  # type: ignore[arg-type]
                {"future_request": True}, evidence, targets
            )

    def test_opt_in_runner_retains_raw_history_and_records_initial_and_gap_audits(self):
        request, evidence, targets = trusted_inputs()
        state = RunState(question="질문", normalized_question="질문", run_id="r1")
        state.required_evidence_items = list(evidence.values())
        state.answer_targets = list(targets.values())
        state.query_history = [request]
        runner = HarnessRunner(
            skill_executor=None,
            retriever=None,
            citation_validator=None,
            config=HarnessConfig(canonical_rerank_query_missing_only=True),
        )

        initial = runner._canonicalize_missing_rerank_queries(
            state, [request], is_gap=False
        )
        gap = runner._canonicalize_missing_rerank_queries(
            state,
            [RetrievalRequest(**{**request.__dict__, "request_id": "GRQ-I1-01"})],
            is_gap=True,
        )

        self.assertEqual(state.query_history, [request])
        self.assertIsNone(state.query_history[0].rerank_query_text)
        self.assertEqual(initial[0].query_text, request.query_text)
        self.assertEqual(gap[0].query_text, request.query_text)
        self.assertEqual(
            [audit["plan_kind"] for audit in state.rerank_query_transforms],
            ["initial", "gap"],
        )
        self.assertEqual(
            [audit["source"] for audit in state.rerank_query_transforms],
            ["canonical_missing_only", "canonical_missing_only"],
        )
        self.assertEqual(
            state.action_trace[-1].details["sources"], ["canonical_missing_only"]
        )

    def test_runner_keeps_raw_initial_request_in_history_but_retrieves_copy(self):
        class Executor:
            def __init__(self):
                self.calls = []

            def execute(self, skill_name, entry_point, payload):
                self.calls.append((skill_name, entry_point, payload))
                if entry_point == "INITIAL_PLAN":
                    return {
                        "legal_issues": [{"issue_id": "I1", "description": "요건"}],
                        "answer_targets": [{
                            "answer_target_id": "T1",
                            "question_anchor": "신청인이 충족해야 할 요건은 무엇인가",
                            "requested_output": "요건 목록",
                            "answer_type": "legal_elements",
                        }],
                        "required_evidence_items": [{
                            "evidence_item_id": "E1",
                            "issue_id": "I1",
                            "evidence_type": "application_requirement",
                            "description": "요건",
                            "critical": True,
                            "completion_criteria": "요건",
                            "necessity_reason": "답변에 필요",
                            "answer_target_ids": ["T1"],
                            "scope_source": "explicit_question",
                            "completion_requirements": [{
                                "requirement_id": "CR1",
                                "text": "제출 기한",
                            }],
                        }],
                        "retrieval_requests": [{
                            "request_id": "RQ-I1-01",
                            "issue_id": "I1",
                            "evidence_item_id": "E1",
                            "query_channel": "provision_style",
                            "query_text": "배경전문 " * 40 + "요건",
                            "top_k": 100,
                            "query_terms": ["요건"],
                            "statute_hints": [],
                        }],
                    }
                if entry_point == "GAP_QUERY_PLAN":
                    return {
                        "gap_retrieval_requests": [{
                            "request_id": "GRQ-I1-01",
                            "issue_id": "I1",
                            "evidence_item_id": "E1",
                            "query_channel": "statute_aware",
                            "query_text": "추가 요건",
                            "top_k": 100,
                            "query_terms": ["추가 요건"],
                            "statute_hints": [],
                        }],
                    }
                if entry_point == "ASSESS_COVERAGE":
                    return {
                        "evidence_links": [],
                        "coverage_assessments": [{
                            "evidence_item_id": "E1",
                            "status": "uncovered",
                            "legal_status": "uncovered",
                            "applicability_status": "not_assessed",
                            "gap_type": "missing_statute",
                            "linked_provision_ids": [],
                            "criterion_results": [{
                                "requirement_id": "CR1",
                                "status": "unsatisfied",
                                "linked_provision_ids": [],
                                "rationale": "근거 없음",
                            }],
                            "rationale": "근거 없음",
                        }],
                        "evidence_conflicts": [],
                    }
                raise AssertionError("unexpected entry point: %s" % entry_point)

        class Retriever:
            def __init__(self):
                self.requests = []

            def retrieve(self, requests, retrieval_round, **_kwargs):
                self.requests.append(list(requests))
                return []

        executor = Executor()
        retriever = Retriever()
        runner = HarnessRunner(
            executor,
            retriever,
            citation_validator=None,
            config=HarnessConfig(
                total_retrieval_rounds=2,
                canonical_rerank_query_missing_only=True,
            ),
        )
        raw_question = (
            "[배경 시나리오]\n" + ("배경전문 " * 50)
            + "\n\n[질문]\n신청인이 충족해야 할 요건은 무엇인가"
        )
        outcome = runner.run(raw_question, run_id="qa150-shaped")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN, outcome.errors)
        self.assertIsNone(outcome.state.query_history[0].rerank_query_text)
        self.assertIn("배경전문", outcome.state.query_history[0].query_text)
        sent = retriever.requests[0][0]
        self.assertEqual(sent.query_text, outcome.state.query_history[0].query_text)
        self.assertNotIn("배경전문", sent.rerank_query_text)
        self.assertEqual(len(retriever.requests), 2)
        self.assertEqual(
            [request.request_id for request in outcome.state.query_history],
            ["RQ-I1-01", "GRQ-I1-01"],
        )
        self.assertIsNone(outcome.state.query_history[1].rerank_query_text)
        gap_sent = retriever.requests[1][0]
        self.assertEqual(gap_sent.query_text, "추가 요건")
        self.assertIn("추가 요건", gap_sent.rerank_query_text)
        self.assertEqual(
            [audit["plan_kind"] for audit in outcome.state.rerank_query_transforms],
            ["initial", "gap"],
        )
        self.assertEqual(
            outcome.state.rerank_query_transforms[0]["raw_request"]["query_text"],
            outcome.state.query_history[0].query_text,
        )
        self.assertEqual(
            outcome.state.rerank_query_transforms[0]["final_request"][
                "rerank_query_text"
            ],
            sent.rerank_query_text,
        )

    def test_default_disabled_runner_does_not_construct_a_transform(self):
        request, evidence, targets = trusted_inputs()
        state = RunState(question="질문", normalized_question="질문", run_id="r1")
        state.required_evidence_items = list(evidence.values())
        state.answer_targets = list(targets.values())
        runner = HarnessRunner(None, None, None, config=HarnessConfig())

        transformed = runner._canonicalize_missing_rerank_queries(
            state, [request], is_gap=False
        )
        self.assertEqual(transformed, [request])
        self.assertFalse(state.rerank_query_transforms)
        self.assertFalse(state.action_trace)


if __name__ == "__main__":
    unittest.main()
