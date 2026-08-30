import copy
import hashlib
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]
C34_S1_PROMPT_RESOURCE_SHA256 = {
    "skills/legal_issue_and_query_planning/SKILL.md": (
        "6fc4008c72afd0a7e7d58f9214dee1eaa8af56de9c3ade5c920fb73d74f84094"
    ),
    "skills/legal_issue_and_query_planning/references/contract.md": (
        "59bcda8231e581eb51c96535c8193ac23b9573ce3242741c3f228fccf701f115"
    ),
}
C37_S3_PROMPT_RESOURCE_SHA256 = {
    "skills/grounded_legal_answer_generation/SKILL.md": (
        "a146c3c7a0910c43d3d0f84a7f347e747a193a5ba88dcf7af50a800379735eac"
    ),
    "skills/grounded_legal_answer_generation/references/contract.md": (
        "f7a2760eb9a5a7aaefd09da4f1a322b90d4825bc25d78f9600fa79b0e71d083a"
    ),
    "skills/grounded_legal_answer_generation/references/input.schema.json": (
        "575583d54580687f0d23e6adecf0d3a0f2dc3d5f0d3eacbad2dc010480daa527"
    ),
}
C39_VALIDATOR_SHA256 = {
    "skills/grounded_legal_answer_generation/scripts/validate_output.py": (
        "4b427f3232cd947a9678d68323f547bc0dcae7e03a2a26c2e6dbd0b9186462bd"
    ),
}
C40_S1_VALIDATOR_SHA256 = {
    "skills/legal_issue_and_query_planning/scripts/validate_output.py": (
        "e1db2ec6a07fbac84a84280caaafc3ab1e95d912cec9ccc4a911382f84d9caba"
    ),
}


def _qa0_payload():
    provision = {
        "provision_id": "상법 650조  보험료의 지급과 지체의 효과#KOBLEX-115945",
        "statute_name": "상법 650조 보험료의 지급과 지체의 효과 2항",
        "provision_text": (
            "②계속보험료가 약정한 시기에 지급되지 아니한 때에는 보험자는 상당한 "
            "기간을 정하여 보험계약자에게 최고하고 그 기간내에 지급되지 아니한 "
            "때에는 그 계약을 해지할 수 있다."
        ),
        "supported_evidence_item_ids": ["E1"],
    }
    return {
        "run_id": "qa0-c34-replay",
        "normalized_question": "보험료 미납 시 보험사가 취할 조치는 무엇인가?",
        "legal_issues": [{"issue_id": "I1"}],
        "answer_targets": [{
            "answer_target_id": "T1",
            "question_anchor": "보험사가 취할 조치는 무엇인가?",
            "requested_output": "보험료 미납 시 보험사가 취할 법적 조치의 종류와 요건",
            "answer_type": "legal_conclusion",
        }],
        "required_evidence_items": [{
            "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
            "description": "보험료 미납 시 보험사 조치", "critical": True,
            "completion_criteria": "보험료 미납 시 조치와 요건",
            "completion_requirements": [
                {"requirement_id": "E1-R1", "text": "보험료 미납 시 조치"},
                {"requirement_id": "E1-R2", "text": "조치의 법적 요건"},
            ],
            "answer_target_ids": ["T1"], "scope_source": "explicit_question",
            "necessity_reason": "질문의 직접 근거가 필요하다.",
        }],
        "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered"}],
        "accepted_provisions": [provision],
        "core_accepted_provisions": [provision],
        "supplemental_provisions": [], "qualifying_provisions": [],
        "alternative_provisions": [], "candidate_provisions": [],
        "answer_mode": "full", "answered_target_ids": ["T1"],
        "deferred_target_ids": [], "state_version": 1,
    }


def _c34_qa0_first_s3_raw():
    """Decoded saved raw response: C34 qa0 attempt 1, dd6c0826…9224."""
    return {
        "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER",
        "status": "ok",
        "claims": [
            {
                "claim_id": "C1",
                "text": "상법 제650조 제2항에 따라, 계속보험료가 약정한 시기에 지급되지 아니한 때에는 보험자는 상당한 기간을 정하여 보험계약자에게 최고하고 그 기간내에 지급되지 아니한 때에는 그 계약을 해지할 수 있다.",
                "claim_type": "legal_rule", "applicability": "direct",
                "answer_target_ids": ["T1"], "citation_required": True,
                "public_role": "conclusion",
            },
            {
                "claim_id": "C2",
                "text": "갑이 3개월 연속으로 보험료를 미납한 사안에 대해, 보험사 을은 상당한 기간을 정하여 최고한 후에도 보험료가 지급되지 않으면 상법 제650조 제2항에 근거하여 보험계약을 해지할 수 있다.",
                "claim_type": "application", "applicability": "direct",
                "answer_target_ids": ["T1"], "citation_required": True,
                "public_role": "conclusion",
            },
        ],
        "claim_citations": [
            {"claim_id": "C1", "provision_id": "상법 650조  보험료의 지급과 지체의 효과#KOBLEX-115945", "support_description": "계속보험료 미납 시 보험사의 최고 및 해지 권한에 관한 법적 근거"},
            {"claim_id": "C2", "provision_id": "상법 650조  보험료의 지급과 지체의 효과#KOBLEX-115945", "support_description": "갑의 보험료 미납 사실에 대한 상법 제650조 제2항의 적용"},
        ],
        "assumptions": [{"code": "A1", "message": "갑과 을 사이의 계약이 상법상 보험계약에 해당하며, 갑의 미납 보험료가 '계속보험료'에 해당한다고 가정한다."}],
        "limitations": [{"code": "L1", "message": "본 답변은 상법 제650조 제2항에 명시된 계약 해지 조치에 한정되며, 보험업법이나 자동차손해배상보장법상 다른 행정적 조치나 제재는 다루지 않는다."}],
    }


def _gap_payload(run_id, evidence_items, missing_ids, query_history=None):
    return {
        "run_id": run_id,
        "normalized_question": "관련 법적 기준을 설명하라.",
        "next_retrieval_round": 2,
        "legal_issues": [{"issue_id": "I1"}, {"issue_id": "I2"}, {"issue_id": "I3"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": evidence_items,
        "coverage_assessments": [],
        "missing_evidence_items": [
            item for item in evidence_items if item["evidence_item_id"] in missing_ids
        ],
        "evidence_conflicts": [], "query_history": query_history or [],
        "candidate_cross_references": [], "seen_provision_ids": [],
        "remaining_request_budget": 6,
    }


def _c34_qa168_evidence():
    return [
        {
            "evidence_item_id": "E2", "issue_id": "I2", "evidence_type": "rule",
            "description": "사망한 대상자의 상속재산 집행 가능성", "critical": True,
            "completion_criteria": "사망 후 상속재산 집행 근거",
            "completion_requirements": [{"requirement_id": "E2-R1", "text": "사망 후 상속재산 집행 가능 여부"}],
            "answer_target_ids": ["T1"], "scope_source": "explicit_question",
            "necessity_reason": "질문의 직접 근거가 필요하다.",
        },
        {
            "evidence_item_id": "E3", "issue_id": "I3", "evidence_type": "limitation",
            "description": "몰수·추징의 시효 기간에 관한 규정", "critical": True,
            "completion_criteria": "시효 기간 근거",
            "completion_requirements": [{"requirement_id": "E3-R1", "text": "몰수·추징의 시효 기간"}],
            "answer_target_ids": ["T1"], "scope_source": "explicit_question",
            "necessity_reason": "질문의 직접 근거가 필요하다.",
        },
    ]


def _c34_qa168_first_gap_raw():
    """Decoded saved raw response: C34 qa168 attempt 1, 147aa306…b753."""
    return {
        "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
        "status": "ok", "run_id": "__HARNESS_RUN_ID__",
        "target_evidence_item_ids": ["E2", "E3"],
        "gap_retrieval_requests": [
            {
                "request_id": "GRQ-R1-1", "issue_id": "I2", "evidence_item_id": "E2",
                "query_channel": "sparse_keywords", "query_text": "몰수 추징 피고인 사망 상속인 재산 집행",
                "query_terms": ["몰수", "추징", "사망", "상속인", "집행"],
                "statute_hints": ["형법", "형사소송법"], "rationale": "피고인 사망 후 상속재산에 대한 몰수·추징 집행 가능 여부를 규정한 조항을 확인하기 위함",
                "gap_reason": "E2-R1 미충족: 사망 후 상속재산 집행 규정 부재", "source_assessment_status": "uncovered",
            },
            {
                "request_id": "GRQ-R2-1", "issue_id": "I3", "evidence_item_id": "E3",
                "query_channel": "sparse_keywords", "query_text": "몰수 추징 시효 기간 연",
                "query_terms": ["몰수", "추징", "시효", "기간"],
                "statute_hints": ["형법", "형사소송법"], "rationale": "몰수·추징의 시효 기간을 명시하는 조항을 확인하기 위함",
                "gap_reason": "E3-R1 미충족: 몰수·추징 시효 기간 규정 부재", "source_assessment_status": "uncovered",
            },
        ],
    }


def _c34_qa86_evidence():
    phrase = "산재 요양 중 산재보험 의료기관에서 발생한 의료사고로 인한 추가 상해의 업무상 재해 인정 기준"
    return [{
        "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
        "description": phrase, "critical": True, "completion_criteria": phrase,
        "completion_requirements": [{"requirement_id": "E1-R1", "text": phrase}],
        "answer_target_ids": ["T1"], "scope_source": "explicit_question",
        "necessity_reason": "질문의 직접 근거가 필요하다.",
    }]


def _c34_qa86_two_request_gap_raw():
    """Decoded saved raw response: C34 qa86 attempt 1, 1b2dd603…c93b."""
    return {
        "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
        "status": "ok", "run_id": "__HARNESS_RUN_ID__",
        "target_evidence_item_ids": ["E1"],
        "gap_retrieval_requests": [
            {
                "request_id": "GRQ-R1-1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware", "query_text": "산업재해보상보험법 제37조 업무상 재해 인정 기준 요양 중 의료기관 내 사고",
                "query_terms": ["업무상 재해", "산재 요양", "산재보험 의료기관", "의료사고", "추가 상해"],
                "statute_hints": ["산업재해보상보험법"], "rationale": "미충족 요구사항 E1-R1의 핵심인 산재 요양 중 의료기관 내 사고의 업무상 재해 인정 법적 근거를 중립적으로 검색한다.",
                "gap_reason": "이전 검색에서 해당 상황의 업무상 재해 인정 기준을 명시하는 조항이 확인되지 않았다.", "source_assessment_status": "uncovered",
            },
            {
                "request_id": "GRQ-R1-2", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keywords", "query_text": "요양 중 의료과실로 인한 상해 업무상 재해 해당 여부",
                "query_terms": ["요양 중", "의료과실", "업무상 재해", "인정 기준"],
                "statute_hints": ["산업재해보상보험법"], "rationale": "의료과실이라는 구체적 사고 유형과 요양 중이라는 상황 요소를 결합하여 업무상 재해 인정 가능성을 탐색한다.",
                "gap_reason": "의료과실로 인한 추가 상해가 업무상 재해에 포함되는지 여부에 대한 명시적 근거가 부족하다.", "source_assessment_status": "uncovered",
            },
        ],
    }


class C36PromptStabilityTests(unittest.TestCase):
    def _executor(self, generator=lambda _prompt: "{}", diagnostics=None, max_attempts=2):
        return LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", generator=generator,
            diagnostic_sink=None if diagnostics is None else diagnostics.append,
            max_attempts=max_attempts,
        )

    def _normalized_s1(self, payload, raw):
        executor = self._executor()
        skill_input = executor._build_skill_input(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )
        output = executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", skill_input, copy.deepcopy(raw)
        )
        output, _repairs = executor._repair_s1_transport(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", output, skill_input
        )
        return output, executor._validators["legal_issue_and_query_planning"](output, skill_input)

    def test_c36_s1_c39_s3_prompt_resources_and_c40_validator_hashes(self):
        for relative, expected in C34_S1_PROMPT_RESOURCE_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
        for relative, expected in C37_S3_PROMPT_RESOURCE_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
        for relative, expected in C39_VALIDATOR_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
        for relative, expected in C40_S1_VALIDATOR_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_saved_c34_qa0_raw_replays_through_c35_s3_normalizer_validator(self):
        executor = self._executor()
        skill_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", _qa0_payload()
        )
        output = executor._normalize_harness_owned_fields(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", skill_input,
            _c34_qa0_first_s3_raw(),
        )
        output, _repairs = executor._repair_s3_redundant_public_rule_application_projection(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", output, skill_input
        )
        self.assertEqual(
            executor._validators["grounded_legal_answer_generation"](output, skill_input), []
        )

    def test_saved_c34_qa168_split_terms_replay_through_c35_validator(self):
        output, errors = self._normalized_s1(
            _gap_payload("qa168-c34-replay", _c34_qa168_evidence(), {"E2", "E3"}),
            _c34_qa168_first_gap_raw(),
        )
        self.assertEqual(errors, [])
        self.assertEqual(output["gap_retrieval_requests"][1]["query_terms"][-2:], ["시효", "기간"])

    def test_saved_c34_qa86_two_request_gap_remains_valid(self):
        output, errors = self._normalized_s1(
            _gap_payload("qa86-c34-replay", _c34_qa86_evidence(), {"E1"}),
            _c34_qa86_two_request_gap_raw(),
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(output["gap_retrieval_requests"]), 2)

    def test_raw_history_duplicate_remains_fail_closed(self):
        evidence = [{
            "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
            "description": "일반 법정 근거", "critical": True,
            "completion_criteria": "일반 법정 근거",
            "completion_requirements": [{"requirement_id": "E1-R1", "text": "일반 법정 근거"}],
            "answer_target_ids": ["T1"], "scope_source": "explicit_question",
            "necessity_reason": "질문의 직접 근거가 필요하다.",
        }]
        payload = _gap_payload(
            "raw-history-duplicate", evidence, {"E1"},
            [{"query_text": "기존 질의\n[원문 맥락]\n관련 법적 기준을 설명하라."}],
        )
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "__HARNESS_RUN_ID__", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "GRQ-R1-1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keywords", "query_text": "기존 질의",
                "query_terms": ["기존", "질의"], "statute_hints": [],
                "rationale": "이미 사용한 질의", "gap_reason": "근거가 부족하다.",
                "source_assessment_status": "uncovered",
            }],
        }
        executor = self._executor(
            generator=lambda _prompt: json.dumps(raw, ensure_ascii=False), max_attempts=1
        )
        with self.assertRaises(SkillExecutionError):
            executor.execute("legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload)

    def test_primary_fingerprints_are_run_id_invariant_and_hash_actual_prompt(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "INITIAL_PLAN",
            "status": "ok", "run_id": "__HARNESS_RUN_ID__",
            "answer_targets": [{"answer_target_id": "T1", "question_anchor": "계약 해지 요건은 무엇인가?", "requested_output": "계약 해지 요건", "answer_type": "legal_rule"}],
            "legal_issues": [{"issue_id": "I1", "issue_statement": "계약 해지 요건", "decision_question": "계약 해지 요건은 무엇인가?", "importance": "critical"}],
            "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "계약 해지 요건", "critical": True, "completion_criteria": "계약 해지 요건", "necessity_reason": "질문의 직접 근거가 필요하다.", "answer_target_ids": ["T1"], "scope_source": "explicit_question", "completion_requirements": [{"requirement_id": "E1-R1", "text": "계약 해지 요건"}]}],
            "retrieval_requests": [{"request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1", "query_channel": "sparse_keywords", "query_text": "계약 해지 요건", "query_terms": ["계약 해지", "요건"], "statute_hints": [], "rationale": "법정 근거를 검색한다."}],
        }

        def execute(run_id):
            prompts, diagnostics = [], []
            executor = self._executor(
                generator=lambda prompt: prompts.append(prompt) or json.dumps(raw, ensure_ascii=False),
                diagnostics=diagnostics,
            )
            payload = {
                "run_id": run_id, "question": "계약 해지 요건은 무엇인가?",
                "normalized_question": "계약 해지 요건은 무엇인가?", "query_history": [],
            }
            expected = executor._prompt(
                "legal_issue_and_query_planning", "INITIAL_PLAN",
                executor._build_skill_input("legal_issue_and_query_planning", "INITIAL_PLAN", payload), "",
            )
            executor.execute("legal_issue_and_query_planning", "INITIAL_PLAN", payload)
            return prompts, diagnostics, expected

        first_prompts, first_diagnostics, expected = execute("run-one")
        second_prompts, second_diagnostics, _ = execute("run-two")
        self.assertEqual(first_prompts, [expected])
        self.assertEqual(first_prompts, second_prompts)
        self.assertNotIn("run-one", first_prompts[0])
        first = first_diagnostics[0]
        second = second_diagnostics[0]
        self.assertEqual(first["prompt_sha256"], hashlib.sha256(first_prompts[0].encode("utf-8")).hexdigest())
        self.assertEqual(first["prompt_sha256"], second["prompt_sha256"])
        self.assertEqual(first["redacted_skill_input_sha256"], second["redacted_skill_input_sha256"])

    def test_repair_note_changes_only_prompt_fingerprint(self):
        valid = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "INITIAL_PLAN", "status": "ok",
            "run_id": "__HARNESS_RUN_ID__", "answer_targets": [{"answer_target_id": "T1", "question_anchor": "계약 해지 요건은 무엇인가?", "requested_output": "계약 해지 요건", "answer_type": "legal_rule"}],
            "legal_issues": [{"issue_id": "I1", "issue_statement": "계약 해지 요건", "decision_question": "계약 해지 요건은 무엇인가?", "importance": "critical"}],
            "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "계약 해지 요건", "critical": True, "completion_criteria": "계약 해지 요건", "necessity_reason": "질문의 직접 근거가 필요하다.", "answer_target_ids": ["T1"], "scope_source": "explicit_question", "completion_requirements": [{"requirement_id": "E1-R1", "text": "계약 해지 요건"}]}],
            "retrieval_requests": [{"request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1", "query_channel": "sparse_keywords", "query_text": "계약 해지 요건", "query_terms": ["계약 해지", "요건"], "statute_hints": [], "rationale": "법정 근거를 검색한다."}],
        }
        responses = iter([{"schema_version": "1.0", "skill_id": "S1", "mode": "INITIAL_PLAN", "status": "ok", "run_id": "__HARNESS_RUN_ID__"}, valid])
        prompts, diagnostics = [], []
        executor = self._executor(
            generator=lambda prompt: prompts.append(prompt) or json.dumps(next(responses), ensure_ascii=False),
            diagnostics=diagnostics,
        )
        executor.execute("legal_issue_and_query_planning", "INITIAL_PLAN", {
            "run_id": "repair-note-run", "question": "계약 해지 요건은 무엇인가?",
            "normalized_question": "계약 해지 요건은 무엇인가?", "query_history": [],
        })
        self.assertEqual(len(prompts), 2)
        self.assertIn("Previous JSON", prompts[1])
        self.assertNotEqual(diagnostics[0]["prompt_sha256"], diagnostics[1]["prompt_sha256"])
        self.assertEqual(diagnostics[0]["redacted_skill_input_sha256"], diagnostics[1]["redacted_skill_input_sha256"])
        for prompt, diagnostic in zip(prompts, diagnostics):
            self.assertEqual(diagnostic["prompt_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
