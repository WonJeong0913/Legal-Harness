import unittest

from harness.contracts import (
    CandidateAnswerStatus,
    CandidateProvision,
    GapPlanRecovery,
    GapPlanRecoveryDisposition,
    OutcomeStatus,
    TerminationReason,
)
from harness.runner import HarnessConfig, HarnessRunner
from retrieval.corpus import InMemoryProvisionCorpus, ProvisionDocument
from tools.validate_citation_integrity import CitationIntegrityChecker


S1 = "legal_issue_and_query_planning"
S2 = "provision_coverage_assessment"
S3 = "grounded_legal_answer_generation"


class ScriptedSkillExecutor:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def execute(self, skill_name, entry_point, payload):
        self.calls.append((skill_name, entry_point, payload))
        key = (skill_name, entry_point)
        if key not in self.responses or not self.responses[key]:
            raise RuntimeError("unexpected skill call: %s" % (key,))
        return self.responses[key].pop(0)


class ScriptedRetriever:
    def __init__(self, provisions_by_round):
        self.provisions_by_round = provisions_by_round
        self.calls = []

    def retrieve(
        self,
        requests,
        retrieval_round,
        *,
        critical_evidence_item_ids=(),
    ):
        self.calls.append(
            (list(requests), retrieval_round, list(critical_evidence_item_ids))
        )
        return [
            CandidateProvision(
                provision_id=provision_id,
                statute_name="테스트법",
                provision_text=text,
                issue_id=requests[0].issue_id,
                source_request_id=requests[0].request_id,
                retrieval_round=retrieval_round,
                first_stage_score=1.0,
                fusion_rank=index,
                rerank_score=1.0 / index,
            )
            for index, (provision_id, text) in enumerate(
                self.provisions_by_round.get(retrieval_round, []), start=1
            )
        ]


def initial_plan():
    return {
        "legal_issues": [{"issue_id": "I1", "description": "적용 요건"}],
        "required_evidence_items": [
            {
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "evidence_type": "application_requirement",
                "description": "필수 요건",
                "critical": True,
            }
        ],
        "retrieval_requests": [
            {
                "request_id": "RQ-I1-01",
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "query_channel": "provision_style",
                "query_text": "적용 요건",
                "top_k": 100,
            }
        ],
    }


def coverage(status, provision_id=None):
    links = []
    linked_ids = []
    if provision_id:
        links = [
            {
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "provision_id": provision_id,
                "support_spans": [{"start_char": 0, "end_char": 2}],
                "assessment": "accepted",
            }
        ]
        linked_ids = [provision_id]
    return {
        "evidence_links": links,
        "coverage_assessments": [
            {
                "evidence_item_id": "E1",
                "status": status,
                "linked_provision_ids": linked_ids,
                "rationale": "테스트 판정",
            }
        ],
        "evidence_conflicts": [],
    }


def answer(provision_id):
    return {
        "claims": [{"claim_id": "C1", "text": "근거 기반 결론"}],
        "claim_citations": [{"claim_id": "C1", "provision_ids": [provision_id]}],
        "answer": "테스트 답변입니다.",
    }


def question_only_candidate():
    return {"claims": [], "claim_citations": [], "answer": "질문만으로 생성한 후보 답변입니다."}


def gap_plan(query="예외 규정"):
    return {
        "gap_retrieval_requests": [
            {
                "request_id": "GRQ-" + query,
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "query_channel": "statute_aware",
                "query_text": query,
                "top_k": 100,
            }
        ]
    }


def repair_collision_recovery(*, dropped_ids, remaining_count):
    return GapPlanRecovery(
        disposition=GapPlanRecoveryDisposition.REPAIR_INDUCED_HISTORY_COLLISION,
        dropped_request_ids=list(dropped_ids),
        repaired_query_sha256=["a" * 64 for _ in dropped_ids],
        dropped_request_count=len(dropped_ids),
        remaining_request_count=remaining_count,
    )


class HarnessPathTests(unittest.TestCase):
    def make_runner(self, skill_responses, provisions_by_round, corpus_documents, config=None):
        executor = ScriptedSkillExecutor(skill_responses)
        retriever = ScriptedRetriever(provisions_by_round)
        corpus = InMemoryProvisionCorpus(corpus_documents)
        runner = HarnessRunner(
            executor,
            retriever,
            CitationIntegrityChecker(corpus),
            config=config or HarnessConfig(),
        )
        return runner, executor, retriever

    def test_initial_path_generates_only_after_citation_pass(self):
        runner, executor, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S2, "ASSESS_COVERAGE"): [coverage("covered", "P1")],
                (S3, "GENERATE_ANSWER"): [answer("P1")],
            },
            {1: [("P1", "적용 요건 조문")]},
            [ProvisionDocument("P1", "테스트법", "적용 요건 조문")],
        )

        outcome = runner.run("  적용   요건은?  ", run_id="answer-path")

        self.assertEqual(outcome.status, OutcomeStatus.ANSWER)
        self.assertEqual(outcome.answer, "테스트 답변입니다.")
        self.assertEqual(outcome.termination_reason, TerminationReason.COMPLETED)
        self.assertEqual(outcome.state.normalized_question, "적용 요건은?")
        self.assertEqual(retriever.calls[0][2], ["E1"])
        self.assertEqual([call[:2] for call in executor.calls], [(S1, "INITIAL_PLAN"), (S2, "ASSESS_COVERAGE"), (S3, "GENERATE_ANSWER")])

    def test_gap_path_reassesses_then_generates(self):
        runner, executor, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [gap_plan()],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered"), coverage("covered", "P2")],
                (S3, "GENERATE_ANSWER"): [answer("P2")],
            },
            {1: [("P1", "초기 조문")], 2: [("P2", "보충 조문")]},
            [
                ProvisionDocument("P1", "테스트법", "초기 조문"),
                ProvisionDocument("P2", "테스트법", "보충 조문"),
            ],
        )

        outcome = runner.run("질문", run_id="gap-path")

        self.assertEqual(outcome.status, OutcomeStatus.ANSWER)
        self.assertEqual(outcome.state.retrieval_rounds_used, 2)
        self.assertEqual(len(retriever.calls), 2)
        self.assertIn((S1, "GAP_QUERY_PLAN"), [call[:2] for call in executor.calls])

    def test_empty_gap_plan_keeps_abstention_and_generates_a_benchmark_candidate(self):
        runner, executor, _ = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{"gap_retrieval_requests": []}],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered")],
                (S3, "GENERATE_BENCHMARK_CANDIDATE"): [answer("P1")],
            },
            {1: [("P1", "초기 조문")]},
            [ProvisionDocument("P1", "테스트법", "초기 조문")],
        )

        outcome = runner.run("질문", run_id="abstain-path")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN)
        self.assertEqual(outcome.termination_reason, TerminationReason.NO_VALID_GAP_QUERY)
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.candidate_answer, "테스트 답변입니다.")
        self.assertEqual(outcome.candidate_answer_status, CandidateAnswerStatus.GENERATED)
        self.assertIn(
            (S3, "GENERATE_BENCHMARK_CANDIDATE"),
            [call[:2] for call in executor.calls],
        )

    def test_all_collision_recovery_preserves_validated_state_and_abstains(self):
        runner, executor, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{
                    "gap_retrieval_requests": [],
                    "harness_gap_plan_recovery": repair_collision_recovery(
                        dropped_ids=["GRQ-R2-1"], remaining_count=0
                    ),
                }],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered")],
                (S3, "GENERATE_BENCHMARK_CANDIDATE"): [answer("P1")],
            },
            {1: [("P1", "초기 조문")]},
            [ProvisionDocument("P1", "테스트법", "초기 조문")],
        )

        outcome = runner.run("질문", run_id="all-collision")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN)
        self.assertEqual(outcome.termination_reason, TerminationReason.NO_VALID_GAP_QUERY)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(outcome.state.retrieval_rounds_used, 1)
        self.assertEqual(outcome.state.remaining_round_budget, 2)
        self.assertEqual(outcome.state.remaining_request_budget, 8)
        # The initial uncovered coverage assessment already set this to one;
        # all-dropped recovery must preserve it rather than advancing it.
        self.assertEqual(outcome.state.no_progress_rounds, 1)
        self.assertEqual(len(outcome.state.query_history), 1)
        self.assertEqual(outcome.state.coverage_assessments[0].status.value, "uncovered")
        self.assertEqual(outcome.state.accepted_provision_ids, set())
        self.assertEqual(outcome.state.core_accepted_provision_ids, set())
        self.assertEqual(outcome.state.supplemental_provision_ids, set())
        self.assertEqual(outcome.state.qualifying_provision_ids, set())
        self.assertEqual(outcome.state.alternative_provision_ids, set())
        recovery_events = [
            event for event in outcome.state.action_trace
            if event.event == "GAP_PLAN_REPAIR_COLLISION_RECOVERED"
        ]
        fallback_policies = [
            event for event in outcome.state.action_trace
            if event.event == "POLICY_DECISION"
            and event.details["action"] == "ABSTAIN"
        ]
        self.assertEqual(len(recovery_events), 1)
        self.assertEqual(len(fallback_policies), 1)
        self.assertEqual(recovery_events[0].details["dropped_request_ids"], ["GRQ-R2-1"])
        self.assertEqual(recovery_events[0].details["remaining_request_count"], 0)
        self.assertNotIn(
            (S3, "GENERATE_ANSWER"), [call[:2] for call in executor.calls]
        )

    def test_all_collision_recovery_records_limited_policy_once(self):
        runner, _, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{
                    "gap_retrieval_requests": [],
                    "harness_gap_plan_recovery": repair_collision_recovery(
                        dropped_ids=["GRQ-R2-1"], remaining_count=0
                    ),
                }],
                (S2, "ASSESS_COVERAGE"): [coverage("partially_covered", "P1")],
                (S3, "GENERATE_ANSWER"): [answer("P1")],
            },
            {1: [("P1", "초기 조문")]},
            [ProvisionDocument("P1", "테스트법", "초기 조문")],
        )

        outcome = runner.run("질문", run_id="all-collision-limited")

        self.assertEqual(outcome.status, OutcomeStatus.ANSWER)
        self.assertEqual(outcome.state.answer_mode.value, "limited")
        self.assertEqual(len(retriever.calls), 1)
        fallback_policies = [
            event for event in outcome.state.action_trace
            if event.event == "POLICY_DECISION"
            and event.details["action"] == "GENERATE"
        ]
        self.assertEqual(len(fallback_policies), 1)
        self.assertEqual(fallback_policies[0].details["answer_mode"], "limited")

    def test_mixed_collision_recovery_dispatches_only_novel_request(self):
        novel = {
            "request_id": "GRQ-R2-2",
            "issue_id": "I1",
            "evidence_item_id": "E1",
            "query_channel": "statute_aware",
            "query_text": "새로운 법정 요건",
            "top_k": 100,
        }
        runner, _, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{
                    "gap_retrieval_requests": [novel],
                    "harness_gap_plan_recovery": repair_collision_recovery(
                        dropped_ids=["GRQ-R2-1"], remaining_count=1
                    ),
                }],
                (S2, "ASSESS_COVERAGE"): [
                    coverage("uncovered"), coverage("covered", "P2")
                ],
                (S3, "GENERATE_ANSWER"): [answer("P2")],
            },
            {1: [("P1", "초기 조문")], 2: [("P2", "보충 조문")]},
            [
                ProvisionDocument("P1", "테스트법", "초기 조문"),
                ProvisionDocument("P2", "테스트법", "보충 조문"),
            ],
        )

        outcome = runner.run("질문", run_id="mixed-collision")

        self.assertEqual(outcome.status, OutcomeStatus.ANSWER)
        self.assertEqual(len(retriever.calls), 2)
        self.assertEqual(
            [request.query_text for request in retriever.calls[1][0]],
            ["새로운 법정 요건"],
        )
        recovery_event = next(
            event for event in outcome.state.action_trace
            if event.event == "GAP_PLAN_REPAIR_COLLISION_RECOVERED"
        )
        self.assertEqual(recovery_event.details["dropped_request_count"], 1)
        self.assertEqual(recovery_event.details["remaining_request_count"], 1)

    def test_benchmark_candidate_failure_does_not_reclassify_abstention(self):
        runner, _, _ = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{"gap_retrieval_requests": []}],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered")],
            },
            {1: [("P1", "초기 조문")]},
            [ProvisionDocument("P1", "테스트법", "초기 조문")],
        )

        outcome = runner.run("질문", run_id="candidate-failure")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN)
        self.assertEqual(
            outcome.candidate_answer_status, CandidateAnswerStatus.EXECUTION_FAILURE
        )
        self.assertEqual(
            outcome.candidate_answer_termination_reason,
            TerminationReason.INVALID_SKILL_OUTPUT,
        )
        self.assertIsNone(outcome.candidate_answer)
        self.assertTrue(outcome.candidate_answer_error)

    def test_empty_retrieval_still_records_a_question_only_candidate(self):
        runner, _, _ = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [{"gap_retrieval_requests": []}],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered")],
                (S3, "GENERATE_BENCHMARK_CANDIDATE"): [question_only_candidate()],
            },
            {1: []},
            [],
        )

        outcome = runner.run("질문", run_id="question-only-candidate")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN)
        self.assertEqual(outcome.candidate_answer_status, CandidateAnswerStatus.GENERATED)
        self.assertEqual(outcome.candidate_answer_basis.value, "question_only")
        self.assertEqual(outcome.candidate_answer, "질문만으로 생성한 후보 답변입니다.")

    def test_two_no_progress_rounds_stop_retrieval(self):
        runner, _, retriever = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S1, "GAP_QUERY_PLAN"): [gap_plan("추가 요건"), gap_plan("다른 요건")],
                (S2, "ASSESS_COVERAGE"): [coverage("uncovered"), coverage("uncovered"), coverage("uncovered")],
                (S3, "GENERATE_BENCHMARK_CANDIDATE"): [answer("P1")],
            },
            {1: [("P1", "초기 조문")], 2: [], 3: []},
            [ProvisionDocument("P1", "테스트법", "초기 조문")],
        )

        outcome = runner.run("질문", run_id="no-progress")

        self.assertEqual(outcome.status, OutcomeStatus.ABSTAIN)
        self.assertEqual(outcome.termination_reason, TerminationReason.NO_RETRIEVAL_PROGRESS)
        self.assertEqual(len(retriever.calls), 2)

    def test_snapshot_mismatch_is_execution_failure_not_abstention(self):
        runner, _, _ = self.make_runner(
            {
                (S1, "INITIAL_PLAN"): [initial_plan()],
                (S2, "ASSESS_COVERAGE"): [coverage("covered", "P1")],
                (S3, "GENERATE_ANSWER"): [answer("P1")],
            },
            {1: [("P1", "검색 당시 조문")]},
            [ProvisionDocument("P1", "테스트법", "바뀐 조문")],
        )

        outcome = runner.run("질문", run_id="citation-failure")

        self.assertEqual(outcome.status, OutcomeStatus.EXECUTION_FAILURE)
        self.assertEqual(outcome.termination_reason, TerminationReason.CITATION_INTEGRITY_FAILED)
        self.assertIn("PROVISION_SNAPSHOT_MISMATCH:P1", outcome.errors[0])
