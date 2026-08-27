import copy
import unittest

from scripts import replay_c02_candidate_hypotheses as replay
from tests.test_c02_candidate_replay import C02CandidateReplayTests


class C02CandidateReplayCriticalQuotaTests(unittest.TestCase):
    def _fixture(self):
        fixture = C02CandidateReplayTests()
        return fixture, fixture._stage_records(), fixture._result(
            "ANSWER", ["P1-alias", "P2"]
        )

    def test_noncritical_request_does_not_inflate_quota_or_dynamic_budget(self):
        fixture, records, result = self._fixture()
        result["state"]["query_history"].append(
            {"request_id": "RQ3", "evidence_item_id": "E3"}
        )
        result["state"]["required_evidence_items"].append(
            {"evidence_item_id": "E3", "critical": False}
        )
        records.extend(
            [
                fixture._record(
                    "first_stage", "P4", source_request_ids=["RQ3"],
                    target_evidence_item_ids=["E3"], first_stage_rank=1,
                    first_stage_score=1.0,
                ),
                fixture._record(
                    "request_rerank", "P4", source_request_ids=["RQ3"],
                    target_evidence_item_ids=["E3"], rerank_rank=1,
                    rerank_score=1.0,
                ),
                fixture._record(
                    "selected", "P4", source_request_ids=["RQ3"],
                    target_evidence_item_ids=["E3"], rerank_rank=1,
                    rerank_score=1.0, fusion_rank=1,
                ),
                fixture._record(
                    "first_stage", "P5", source_request_ids=["RQ2"],
                    target_evidence_item_ids=["E2"], first_stage_rank=2,
                    first_stage_score=0.6,
                ),
                fixture._record(
                    "request_rerank", "P5", source_request_ids=["RQ2"],
                    target_evidence_item_ids=["E2"], rerank_rank=2,
                    rerank_score=0.6,
                ),
                fixture._record(
                    "selected", "P5", source_request_ids=["RQ2"],
                    target_evidence_item_ids=["E2"], rerank_rank=2,
                    rerank_score=0.6, fusion_rank=4,
                ),
            ]
        )

        variants, provenance = replay._variant_rounds(
            records, result, top_k=2, dynamic_cap=6, evidence_quota=2, rrf_k=60
        )

        self.assertEqual(provenance["dynamic_top_k_by_round"], {"1": 4})
        self.assertEqual(
            variants["request_rank_round_robin_quota2_dynamic"][1],
            ["P1-alias", "P3", "P2", "P5"],
        )
        self.assertNotIn(
            "P4", variants["request_rank_round_robin_quota2_dynamic"][1]
        )

    def test_zero_active_critical_evidence_fails_explicitly(self):
        _, records, result = self._fixture()
        result = copy.deepcopy(result)
        result["state"]["query_history"] = [
            {"request_id": "RQ1", "evidence_item_id": "E3"}
        ]
        result["state"]["required_evidence_items"].append(
            {"evidence_item_id": "E3", "critical": False}
        )

        with self.assertRaisesRegex(ReplayError, "no active critical evidence IDs"):
            replay._variant_rounds(
                records, result, top_k=2, dynamic_cap=6, evidence_quota=2, rrf_k=60
            )


ReplayError = replay.ReplayError


if __name__ == "__main__":
    unittest.main()
