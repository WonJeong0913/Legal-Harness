#!/usr/bin/env python3
"""Prepare and run the isolated, offline V2 KURE experiment plan.

This file intentionally contains no model warm-up at import time.  The only
execution path that loads KURE/BGE/Ollama is ``run``; ``bootstrap``,
``preflight``, and ``--dry-run`` are CPU-only control-plane operations.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback
from urllib.error import URLError
from urllib.request import urlopen
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from public_answer_contract import (
    PUBLIC_ANSWER_FORMAT,
    PUBLIC_ANSWER_MAX_CHARACTERS,
    PUBLIC_ANSWER_MAX_CLAIMS,
)

DIAGNOSTIC21_MODE = "diagnostic21"
DIAGNOSTIC21_ENTRY_COUNT = 21
DIAGNOSTIC21_CHUNKS = ((1, 20), (21, 21))
DIAGNOSTIC21_PRIMARY_FROZEN_NAME = "v2-kure-qwen38-q8-offline-diagnostic21-c34-20260828"
DIAGNOSTIC21_REFERENCE_FROZEN_NAME = "v2-bm25-reference-qwen38-q8-offline-diagnostic21-c34-20260828"
DIAGNOSTIC21_SOURCE_PRIMARY_SHA256 = "f20e53be976b46ec093fb8723c29a4e9fbfb3f8e25d46c6e84367def8f3e130f"
DIAGNOSTIC21_SOURCE_REFERENCE_SHA256 = "a514a4f4c87960046f09677c2dc01a594e153bab140a7ac0803d04a93c8cf106"
DIAGNOSTIC21_IMPLEMENTATION_PARENT_COMMIT = "8e26c44c1353961a1e9b492e9c9144b23b833281"
DIAGNOSTIC21_FLOAT_TOLERANCE = 1e-12
DIAGNOSTIC21_C31_CONDITION_SUFFIX = "+C31-shared-public-answer-contract"
DIAGNOSTIC21_C31_RELEASE = "C31-shared-public-answer-contract-alignment"
DIAGNOSTIC21_C32_CONDITION_SUFFIX = "+C32-retry-only-qualifying-carry-forward"
DIAGNOSTIC21_C32_RELEASE = "C32-retry-only-qualifying-carry-forward"
DIAGNOSTIC21_C33_CONDITION_SUFFIX = "+C33-redundant-public-rule-demotion"
DIAGNOSTIC21_C33_RELEASE = "C33-redundant-public-rule-demotion"
DIAGNOSTIC21_C34_CONDITION_SUFFIX = "+C34-type-aware-public-projection-gap-anchors"
DIAGNOSTIC21_C34_RELEASE = "C34-type-aware-public-projection-gap-anchors"
DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE = "single_issue_fusion_top_k"
DIAGNOSTIC21_C02_ROUND_MERGE_MODE = "request_rank_top1_guarded_swap"
DIAGNOSTIC21_C30_CONDITION_SUFFIX = "+C30-paired-C02-gate-S3-carry-forward-overlay"
DIAGNOSTIC21_CANDIDATE_ID = (
    "C29-preserved-S1-S2-S3-contract+"
    "C30-paired-C02-answer-cohort-gate+S3-carry-forward+"
    "C31-shared-public-answer-contract+"
    "C32-retry-only-qualifying-carry-forward+"
    "C33-redundant-public-rule-demotion+"
    "C34-type-aware-public-projection-gap-anchors"
)
DIAGNOSTIC21_C22_CAPABILITY = {
    "capability": "standalone ungrounded paragraph gap recovery",
    "audit_kind": "neutralized_ungrounded_standalone_paragraph",
    "semantic_inference": "FAIL_CLOSED_NO_STATUTE_OR_PROVISION_SEMANTIC_INFERENCE",
}
DIAGNOSTIC21_C28_CAPABILITIES = {
    "c25_single_target_anchor_transport": {
        "audit_kind": "single_target_non_substring_anchor_fallback",
        "scope": "FULLY_LINKED_SINGLE_TARGET_ORIGINAL_QUESTION_MARKER_ONLY",
        "legal_decision_mutation": "NONE",
    },
    "c26_repair_induced_sibling_collision": {
        "disposition": "repair_induced_intra_output_sibling_collision",
        "scope": "ONE_REPAIRED_QUERY_ONE_UNTOUCHED_SAME_CRITICAL_EVIDENCE_SIBLING",
        "query_synthesis": "NONE",
    },
    "c27_partial_core_retry_contract": {
        "scope": "S2_PROMPT_AND_RETRY_GUIDANCE_ONLY",
        "runtime_coverage_mutation": "NONE",
        "validator_boundary": "UNCHANGED_FAIL_CLOSED",
    },
}
DIAGNOSTIC21_C29_CAPABILITIES = {
    "c29a_s2_retry_only_scope": {
        "initial_s2_global_partial_core_injection": "REMOVED",
        "retry_scope": "CONSISTENCY_FAILURE_ONLY",
        "runtime_coverage_mutation": "NONE",
    },
    "c29b_s1_effect_neutrality": {
        "initial_plan": "TRUSTED_QUESTION_EFFECT_NEUTRALITY",
        "model_retry": "ONE_BOUNDED_MODEL_RETRY",
        "deterministic_plan_or_query_rewrite": "NONE",
    },
    "c29c_narrow_composite_application_conditional_exception_public_contract": {
        "application_gate": {
            "predicate": "ALL",
            "gold_free": True,
            "clauses": [
                {"field": "mode", "equals": "GENERATE_ANSWER"},
                {"field": "public_contract", "equals": "REQUIRED"},
                {"field": "answered_targets", "count_equals": 1},
                {"field": "answered_targets[0].answer_type", "equals": "legal_conclusion"},
                {"field": "critical_evidence_items", "target_linked_count_equals": 1},
                {
                    "field": "public_conclusion.claims",
                    "claim_type": "legal_rule",
                    "count_at_least": 2,
                },
                {
                    "field": "public_conclusion.cited_provision_ids",
                    "distinct_count_at_least": 2,
                },
                {"field": "public_conclusion.cited_application_count", "equals": 0},
            ],
        },
        "answered_target_conditional_exception": "PUBLIC_CONCLUSION",
        "deterministic_claim_text_type_role_or_citation_rewrite": "NONE",
    },
}
DIAGNOSTIC21_C30_CAPABILITIES = {
    "c30_paired_c02_answer_cohort_gate": {
        "cohort": "FIXED_C02_PUBLISHED_ANSWER_INTERSECTION_OF_DIAGNOSTIC21",
        "cohort_count": 4,
        "metric": "MEAN_TOKEN_F1_AT_800",
        "evaluation_only": True,
        "runtime_retrieval_or_answer_policy_mutation": "NONE",
        "threshold_lowering": "FORBIDDEN",
    },
    "c30_s3_public_conclusion_contract_recovery": {
        "public_presentation": "NORMALLY_2_TO_4_SENTENCES_MAX_800_CHARS",
        "public_conclusion_claim_bounds": {"minimum": 1, "maximum": 4},
        "audit_conditional_exception_duplicate": (
            "NORMALIZED_FULL_TEXT_IN_ONE_PUBLIC_CONCLUSION_WITH_COMPLETE_"
            "TARGET_AND_PROVISION_SETS"
        ),
        "first_invalid_retry_carry_forward": {
            "capture": "HIDDEN_AUDIT_CONDITIONAL_EXCEPTIONS",
            "obligation": "NORMALIZED_FULL_TEXT_ALL_TARGET_IDS_ALL_PROVISION_IDS_IN_ONE_PUBLIC_CONCLUSION",
            "claim_id_requirement": "NONE",
            "deterministic_legal_claim_status_or_citation_rewrite": "NONE",
            "silent_omission": "FAIL_CLOSED",
        },
    },
}
DIAGNOSTIC21_C30_SOURCE_PROVENANCE = {
    "base_source_commit": "cac3951420ee56486cc9e4a6cd37f77a81d68b0c",
    "base_source_tree": "97dd989d06bab5baa70164e1b2209dc3ab87f382",
    "paired_c02_gate_commit": "390ae000d21dda4487562273e5b08a798efe0047",
    "s3_carry_forward_commit": "cc559855ca0e268b06b00ebb0fbf21740df9893d",
}
DIAGNOSTIC21_C31_CAPABILITIES = {
    "shared_public_answer_contract": {
        "max_characters": PUBLIC_ANSWER_MAX_CHARACTERS,
        "max_conclusion_claims": PUBLIC_ANSWER_MAX_CLAIMS,
        "format": PUBLIC_ANSWER_FORMAT,
        "authority": "CYCLE_FREE_SHARED_CONSTANTS",
        "stale_paired_manifest_mismatch": "FAIL_CLOSED_PREFLIGHT",
    },
}
DIAGNOSTIC21_C31_SOURCE_PROVENANCE = {
    "base_source_commit": "f228408bd4f393bca7b5b03f19aae3fd845d5f37",
    "base_source_tree": "3846f41fd25c976cbca5d812848d5be339202438",
    "release": DIAGNOSTIC21_C31_RELEASE,
    "runtime_contract_module": "public_answer_contract.py",
}
DIAGNOSTIC21_C32_CAPABILITIES = {
    "retry_only_qualifying_carry_forward": {
        "authorization": "FROZEN_FIRST_INVALID_OBLIGATION_ONLY",
        "citation": "EXACT_ACCEPTED_QUALIFYING_PROVISION_ONLY",
        "coverage": "NORMALIZED_TEXT_AND_COMPLETE_TARGET_AND_PROVISION_SETS",
        "private_validator_context_in_model_prompt": "FORBIDDEN",
        "all_other_noncore_roles": "AUDIT_ONLY_FAIL_CLOSED",
    },
}
DIAGNOSTIC21_C32_SOURCE_PROVENANCE = {
    "base_source_commit": "567f70fee12c1e45a9ecf186adca5e16fb1bd524",
    "base_source_tree": "eecca53b77a2693484838361512cc2c3e330600f",
    "release": DIAGNOSTIC21_C32_RELEASE,
    "s3_validator_context": "LOCAL_EXECUTOR_ONLY",
}
DIAGNOSTIC21_C33_CAPABILITIES = {
    "c33_redundant_public_legal_rule_projection": {
        "phase": "POST_S1_PRE_VALIDATION_DETERMINISTIC_PUBLIC_PRESENTATION_REPAIR",
        "gold_benchmark_or_score_input": "FORBIDDEN",
        "predicate": {
            "mode": "GENERATE_ANSWER",
            "public_conclusion_contract": "required",
            "legal_rule": "public_role=conclusion,claim_type=legal_rule,applicability=direct",
            "application": "public_role=conclusion,claim_type=application",
            "matching": "EXACT_NONEMPTY_TARGET_ID_SET_AND_CORE_PROVISION_ID_SET",
        },
        "action": "DEMOTE_MATCHED_LEGAL_RULE_PUBLIC_ROLE_TO_AUDIT_ONLY",
        "claim_text_targets_and_citations": "PRESERVED",
        "public_answer": "REBUILT_FROM_REMAINING_PUBLIC_CLAIMS",
        "nonmatches": "FAIL_CLOSED_NO_MUTATION",
    },
}
DIAGNOSTIC21_C33_SOURCE_PROVENANCE = {
    "base_source_commit": "a5969bc0631bc5ed54f99677b7740094303f3da0",
    "base_source_tree": "6456ca2d89bdc3313d153b3cbbdf2762c86f2b0f",
    "release": DIAGNOSTIC21_C33_RELEASE,
    "implementation_layer": "LOCAL_EXECUTOR_POST_S1_PRE_VALIDATION_PUBLIC_PROJECTION",
}
DIAGNOSTIC21_C34_CAPABILITIES = {
    "c34_s3_type_aware_redundant_public_projection": {
        "phase": "POST_S1_PRE_VALIDATION_DETERMINISTIC_PUBLIC_PRESENTATION_REPAIR",
        "gold_benchmark_or_score_input": "FORBIDDEN",
        "predicate": "C33_EXACT_NONEMPTY_TARGET_AND_CORE_PROVISION_MATCH",
        "legal_conditions_all_matched_targets": "DEMOTE_APPLICATION_TO_AUDIT",
        "other_or_unknown_answer_types": "DEMOTE_LEGAL_RULE_TO_AUDIT",
        "claim_text_targets_and_citations": "PRESERVED",
        "public_answer": "REBUILT_FROM_REMAINING_PUBLIC_CLAIMS",
    },
    "c34_s3_case_fact_anchor_retry": {
        "scope": "SINGLE_TARGET_LEGAL_CONCLUSION_C33_EXACT_MATCH_ONLY",
        "anchor_source": "ONE_PARTICLE_NORMALIZED_KOREAN_REQUESTED_OUTPUT_RESULT_OBJECT_PHRASE",
        "missing_anchor_action": "BOUNDED_MODEL_RETRY_NO_HARNESS_SENTENCE_SYNTHESIS",
        "duplicate_invalid_response": "FAIL_CLOSED_EXISTING_PUBLIC_ROLE_GUARD",
    },
    "c34_s1_gap_anchor_coverage": {
        "scope": "UNRESOLVED_CRITICAL_EVIDENCE_ONLY",
        "anchor_source": "ONE_REPEATED_KOREAN_DESCRIPTION_AND_COMPLETION_REQUIREMENT_RESULT_OBJECT_PHRASE",
        "query_field": "EXPLICIT_QUERY_TERMS_ONLY",
        "english_or_mixed_source": "SKIP_NO_NEW_RESTRICTION",
        "runtime_query_or_statute_synthesis": "NONE",
    },
}
DIAGNOSTIC21_C34_SOURCE_PROVENANCE = {
    "base_source_commit": "8e26c44c1353961a1e9b492e9c9144b23b833281",
    "base_source_tree": "54b3b0faa1a8e92a562f4c7f3cbedc8cdc3d8644",
    "release": DIAGNOSTIC21_C34_RELEASE,
    "implementation_layer": "S1_GAP_VALIDATOR_AND_LOCAL_EXECUTOR_POST_S1_PRE_VALIDATION_PUBLIC_PROJECTION",
}
DIAGNOSTIC21_SEMANTIC_AUTHORITY = (
    "Execution semantic authority is the committed clean source snapshot plus frozen S1/S2/S3 skill hashes."
)
DIAGNOSTIC21_ROSTER = (
    (17, "qa_86_3hop_140"), (25, "qa_401_2hop_619"), (42, "qa_406_2hop_622"),
    (51, "qa_430_3hop_669"), (52, "qa_25_1hop_37"), (54, "qa_99_1hop_167"),
    (58, "qa_332_2hop_531"), (65, "qa_286_2hop_1091_rand"), (83, "qa_460_3hop_730"),
    (84, "qa_68_1hop_100"), (99, "qa_168_3hop_301"), (120, "qa_116_1hop_207"),
    (131, "qa_209_3hop_360"), (133, "qa_2_1hop_4"), (140, "qa_435_2hop_678"),
    (149, "qa_125_1hop_225"), (152, "qa_273_2hop_431"), (202, "qa_102_2hop_400_rand"),
    (208, "qa_0_1hop_0"), (211, "qa_110_1hop_193"), (213, "qa_22_2hop_33"),
)
DIAGNOSTIC21_COHORT_BY_SOURCE_ORDINAL = {
    42: "execution_failure", 54: "execution_failure", 65: "execution_failure",
    83: "execution_failure", 99: "execution_failure", 120: "execution_failure",
    152: "execution_failure", 202: "execution_failure",
    58: "accepted_abstain", 84: "accepted_abstain", 131: "accepted_abstain",
    133: "accepted_abstain", 140: "accepted_abstain", 208: "accepted_abstain",
    211: "accepted_abstain",
    17: "s2_loss", 25: "s2_loss", 51: "s2_loss", 52: "s2_loss",
    149: "s2_loss", 213: "s2_loss",
}
DIAGNOSTIC21_COHORT_COUNTS = {
    "execution_failure": 8,
    "accepted_abstain": 7,
    "s2_loss": 6,
}
DIAGNOSTIC21_CONDITION_LINEAGE = {
    "C04_evidence_roles": [
        "083813102b284052d546d1dacbd2c13829d9cafe",
        "e530a696f344b86ffe2a4ec047da522e45a4f409",
        "55e788e31618f3efa5233c01b6f2943c5dc484f9",
    ],
    "C05_collision_recovery": [
        "764eabdf412fa2c89170aaaf6fa9439729361a5e",
        "bed22c285793465b53a32bdac945d7f0461c9603",
    ],
    "C06_axis_projection": [
        "3569f8d44dc57ddb49c4fbb9e43f540e308cd17c",
        "f1282fcaa753f96b12c65b6958384d012dba7c5b",
    ],
    "C09_C08_list_dedupe_and_raw_duplicate_preservation": [
        "ec7fd5bbcdc588dc05a7c104f81309c2c6c09358",
        "6ae1f3c13aafbd1c23ba7106f8f9d9d96aab04db",
        "22482dac6ac7168979ecda174a73260d1f454874",
    ],
    "C10_trusted_anchor": ["bf51c7173d7137e226b82fbc5ff0532e77e3ee2e"],
    "C18_compact_s2_core_boundary": ["62fc37d7eda2946cc90bce9dbdd875d6852a4dda"],
    "C19_execution_path_safety": ["4db5a642f33816c9d1646222c2f56747ad299994"],
    "C22_standalone_paragraph_repair": ["17869b51c44a289f235c535f2f3e5f6eb2ed905a"],
    "C23_static_candidate_replay_analysis_only": [
        "04ec6ada68d32985c8426d7fd5fb02560568f45d"
    ],
    "C25_C29_full_commit_lineage": [
        "782e042eb986db88e37e35f0ba10556dfcfe7efe",
        "82ddba012d29ac8f497af2fa1e34f0c6241dc3ef",
        "64b3a11f1edb65a512f2c0487ebb3bf60aaa540e",
        "54d94d9f6c87a06a25d58cf162bc2f30c20f6a6f",
        "55d6a808eecf147372fec5f769d103497a608b13",
        "e6dfff14342b57b6cda4c3f1a37a333e6546b68f",
        "a604967a35649a6a5f5ccbbb59750f3ca594ec0b",
    ],
    "C30_integration_inputs": [
        "cac3951420ee56486cc9e4a6cd37f77a81d68b0c",
        "390ae000d21dda4487562273e5b08a798efe0047",
        "cc559855ca0e268b06b00ebb0fbf21740df9893d",
    ],
    "C33_presentation_repair_parent": [
        "a5969bc0631bc5ed54f99677b7740094303f3da0",
    ],
    "C34_type_aware_projection_and_gap_anchor_parent": [
        "8e26c44c1353961a1e9b492e9c9144b23b833281",
    ],
}
DIAGNOSTIC21_SKILL_FILES = {
    "S1": {
        "skill_path": "skills/legal_issue_and_query_planning/SKILL.md",
        "skill_sha256": "6fc4008c72afd0a7e7d58f9214dee1eaa8af56de9c3ade5c920fb73d74f84094",
        "validator_path": "skills/legal_issue_and_query_planning/scripts/validate_output.py",
        "validator_sha256": "84c1ab1ff20a053c67dbe245457c9bd55d91271407078f3b355cfadc38d80422",
    },
    "S2": {
        "skill_path": "skills/provision_coverage_assessment/SKILL.md",
        "skill_sha256": "a1d0ede5f6d049e975b356e7325d4a6aef1122db33d023a34cf6f59c45d96e95",
        "validator_path": "skills/provision_coverage_assessment/scripts/validate_output.py",
        "validator_sha256": "2d63bd38df2b7b5eb57009b6c056908339aeee4f5f9eee4ad987405841c3b619",
    },
    "S3": {
        "skill_path": "skills/grounded_legal_answer_generation/SKILL.md",
        "skill_sha256": "a146c3c7a0910c43d3d0f84a7f347e747a193a5ba88dcf7af50a800379735eac",
        "validator_path": "skills/grounded_legal_answer_generation/scripts/validate_output.py",
        "validator_sha256": "e150774086822f2b00d3337555645cd4468f30aa3239c236daf1d0a2fd89b6f4",
    },
}
DIAGNOSTIC21_RERANKER_PROVENANCE = {
    "model_id": "dragonkue/bge-reranker-v2-m3-ko",
    "model_path": "models/huggingface/dragonkue--bge-reranker-v2-m3-ko",
    "model_weights_sha256": "aba51b69d97bfff4cd2c1d8eb6c57764e350231850f712b75ae426270f265a43",
    "device": "cuda",
}
DIAGNOSTIC21_BASELINE = {
    "status_counts": {"ANSWER": 4, "ABSTAIN": 9, "EXECUTION_FAILURE": 8},
    "provision_macro": {"precision": 0.5294784580498866, "recall": 0.5317460317460317, "f1": 0.4862433862433862},
    "provision_exact_match_count": 2,
    "accepted_complete_evidence_count": 7,
    "token_f1_end_to_end": 0.0807217786048895,
    "token_f1_answered_only": 0.42378933767566984,
    "candidate_token_f1": {"all_outcomes": 0.19949510741048834, "normal_outcomes": 0.32226132735540425, "abstain": 0.277137767213064, "available": 13, "missing_or_failure": 8},
    "citation_integrity": {"attempted": 4, "passed": 4, "pass_rate": 1.0},
    "provenance": {
        "published_per_question_csv_sha256": "b0828c0d194aac9d59d3ad5894aae6220b8eaabc2c21959feabd76b5ac43e3f6",
        "evaluated_source_commit": "c02e2818ad54e9d5a1a9bd02b604e987192bb244",
        "evaluated_source_tree": "9fcb0ebceb0b3d96955f1626f2c952a457be930f",
        "published_result_commit": "b43c613ad9c5498627f2cb2a25915c80f9f08374",
        "published_result_tree": "d8296a2cacde164074688eba5068a5709534c0b5",
    },
}
DIAGNOSTIC21_C02_ANSWER_COHORT_FILE = "frozen_manifests/c02_diagnostic21_answer_cohort.json"
DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256 = "046b04e37437100a51769f40cf12e45e969169ecd15644188ef7c4cebf9b1b60"
DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE = {
    **DIAGNOSTIC21_BASELINE["provenance"],
    "per_question_csv_path": "records/evaluations/kure-c02-qwen38-q8-full226-20260826/per_question.csv",
}
DIAGNOSTIC21_C02_ANSWER_COHORT_ROWS = (
    {"source_ordinal": 17, "question_id": "qa_86_3hop_140", "n_hops": 3, "status": "ANSWER", "token_f1_at_800": 0.3170731707317073},
    {"source_ordinal": 25, "question_id": "qa_401_2hop_619", "n_hops": 2, "status": "ANSWER", "token_f1_at_800": 0.4999999999999999},
    {"source_ordinal": 51, "question_id": "qa_430_3hop_669", "n_hops": 3, "status": "ANSWER", "token_f1_at_800": 0.339622641509434},
    {"source_ordinal": 52, "question_id": "qa_25_1hop_37", "n_hops": 1, "status": "ANSWER", "token_f1_at_800": 0.5384615384615384},
)
DIAGNOSTIC21_C02_ANSWER_COHORT = {
    "schema_version": "c02_diagnostic21_answer_cohort_v1",
    "baseline_mean_token_f1_at_800": DIAGNOSTIC21_BASELINE["token_f1_answered_only"],
    "cohort_count": 4,
    "derivation": {
        "evaluation_only": True,
        "method": "Filter the immutable C02 published per_question.csv to the fixed diagnostic21 roster, then retain only rows whose published status is ANSWER. This artifact is a predeclared evaluation cohort and is not runtime retrieval, answer, abstention, or gold-aware policy.",
        "score_column": "token_f1_at_800",
        "status_equals": "ANSWER",
    },
    "provenance": DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE,
    "rows": [dict(row) for row in DIAGNOSTIC21_C02_ANSWER_COHORT_ROWS],
}
DIAGNOSTIC21_C02_ANSWER_COHORT_SOURCE_ORDINALS = tuple(
    int(row["source_ordinal"]) for row in DIAGNOSTIC21_C02_ANSWER_COHORT_ROWS
)
DIAGNOSTIC21_C02_ANSWER_COHORT_QUESTION_IDS = tuple(
    str(row["question_id"]) for row in DIAGNOSTIC21_C02_ANSWER_COHORT_ROWS
)
DIAGNOSTIC21_ANSWER_YIELD_MINIMUM = int(DIAGNOSTIC21_C02_ANSWER_COHORT["cohort_count"])
DIAGNOSTIC21_NONREGRESSION_MINIMUMS = {
    "provision_macro_f1": DIAGNOSTIC21_BASELINE["provision_macro"]["f1"],
    "provision_exact_match_count": DIAGNOSTIC21_BASELINE["provision_exact_match_count"],
    "complete_evidence_count": DIAGNOSTIC21_BASELINE["accepted_complete_evidence_count"],
    "token_f1_end_to_end": DIAGNOSTIC21_BASELINE["token_f1_end_to_end"],
    "token_f1_candidate": DIAGNOSTIC21_BASELINE["candidate_token_f1"]["all_outcomes"],
}
FULL226_C02_NONREGRESSION_MINIMUMS = {
    "token_f1_answered_only": 0.388839104735601,
    "token_f1_candidate": 0.34864352525272263,
}
FULL226_C02_BASELINE_PROVENANCE = {
    "published_aggregate_json_path": "records/evaluations/kure-c02-qwen38-q8-full226-20260826/aggregate.json",
    "published_aggregate_json_sha256": "02903d26253ef8a54238d19529a9d30308c5ca4341d9c178c28deefc663469bb",
    "published_per_question_csv_sha256": DIAGNOSTIC21_BASELINE["provenance"]["published_per_question_csv_sha256"],
    "published_result_commit": DIAGNOSTIC21_BASELINE["provenance"]["published_result_commit"],
    "published_result_tree": DIAGNOSTIC21_BASELINE["provenance"]["published_result_tree"],
}
TOTAL_FULL226 = 226
CHUNK_SIZE = 20
OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OLLAMA_NUM_PARALLEL": "1",
    "GGML_CUDA_DISABLE_GRAPHS": "1",
    "OLLAMA_NO_CLOUD": "1",
}
EXPECTED_RUNTIME = {
    "model": "legal-harness-qwen38-q8",
    "endpoint": "http://127.0.0.1:11435/api/generate",
    "seed": 0,
    "num_ctx": 32768,
    "num_parallel": 1,
}
PRIMARY_FROZEN_NAME = "v2-kure-c08-s1-repair-list-dedupe-v1-c06-s2-axis-canonical-projection-v1-c05-repair-collision-failsafe-v1-c04-core-auxiliary-roles-v1-s1-neutral-single-issue-fusion-top10-qwen38-q8-offline-full226-c34-20260828"
REFERENCE_FROZEN_NAME = "v2-bm25-reference-c08-s1-repair-list-dedupe-v1-c06-s2-axis-canonical-projection-v1-c05-repair-collision-failsafe-v1-c04-core-auxiliary-roles-v1-s1-neutral-single-issue-fusion-top10-qwen38-q8-offline-full226-c34-20260828"
SMOKE_FROZEN_NAME = "v2-kure-c08-s1-repair-list-dedupe-v1-c06-s2-axis-canonical-projection-v1-c05-repair-collision-failsafe-v1-c04-core-auxiliary-roles-v1-s1-neutral-single-issue-fusion-top10-qwen38-q8-offline-smoke3-c34-20260828"
SMOKE_REFERENCE_FROZEN_NAME = "v2-bm25-reference-c08-s1-repair-list-dedupe-v1-c06-s2-axis-canonical-projection-v1-c05-repair-collision-failsafe-v1-c04-core-auxiliary-roles-v1-s1-neutral-single-issue-fusion-top10-qwen38-q8-offline-smoke3-c34-20260828"
PUBLIC_ANSWER_FROZEN_CONFIGURATION = {
    "s3_public_answer_max_characters": PUBLIC_ANSWER_MAX_CHARACTERS,
    "s3_public_answer_max_claims": PUBLIC_ANSWER_MAX_CLAIMS,
    "s3_public_answer_format": PUBLIC_ANSWER_FORMAT,
}
V2_SOURCE_METADATA_CARRY_FORWARD = {
    "lineage": {
        "c04_evidence_role_contract": "c04_core_auxiliary_roles_v1",
        "c05_source_commit": "b27024cd15bf2692345670865c754608784ed7c4",
        "c05_source_tree": "797897a99ec9e3da622aa313ce4bb3616c179423",
        "c06_axis_canonical_projection_contract": "c06_s2_axis_canonical_projection_v1",
        "c06_implementation_commit": "3569f8d44dc57ddb49c4fbb9e43f540e308cd17c",
        "c06_protocol_commit": "3ab2388881322d9f08dc001e9a3764472cc89343",
        "c08_candidate_commit": "6ae1f3c13aafbd1c23ba7106f8f9d9d96aab04db",
        "c08_candidate_tree": "bb102d7728512b803973c02769b171d78975b273",
    },
    "repair_collision_contract": {
        "all_dropped": "existing_limited_or_abstain_no_state_mutation",
        "bounded_neutral_replan": 1,
        "mixed": "novel_only_dispatch",
        "raw_history_duplicate": "invalid",
        "repair_induced_history_collision": "typed_recovery",
    },
    "repair_induced_retrieval_list_dedupe_contract": {
        "contract": "c08_repair_induced_retrieval_list_dedupe_v1",
        "audit_kind": "deduplicated_repair_induced_list_values",
        "drop_scope": "only_collisions_newly_induced_by_article_neutralization",
        "fields": ["query_terms", "statute_hints"],
        "order": "stable_first",
        "raw_duplicates": "preserved_for_final_validator",
    },
    "s2_axis_canonical_projection_contract": {
        "contract": "c06_s2_axis_canonical_projection_v1",
        "audit_event": "S2_LEGACY_PROJECTION_DERIVED",
        "invalid_partial_unsupported_or_semantic_tuple": "fail_closed",
        "legacy_derived_by_harness": ["status", "partial_kind", "governing_legal_regime", "missing_evidence_items", "evidence_conflicts"],
        "no_runtime_state_or_role_union_mutation": True,
        "scope_excess": "noncritical_only",
    },
}
NORMAL_STATUSES = {"ANSWER", "ABSTAIN"}
DEFAULT_GPU_IDLE_UTILIZATION_MAX = 10
DEFAULT_GPU_IDLE_USED_MIB_MAX = 2048
DEFAULT_GPU_IDLE_POLL_SECONDS = 1800
DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS = 30
DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES = 2
QWEN_MODEL_PROVENANCE = {
    "alias": "legal-harness-qwen38-q8",
    "ollama_model_blob": "/root/.ollama/models/blobs/sha256-f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8",
    "sha256": "f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8",
    "file": "Qwen3.8-27B-Q8_0.gguf",
    "quantization": "Q8_0",
    "observed_architecture": "qwen35",
    "observed_parameter_count": "26.9B",
    "ollama_manifest_digest": "91f49c230b9d1fd034414b1035b361cfe4ad1c89f7076012b10420edea8b78ff",
    "ollama_details": {
        "family": "qwen35",
        "parameter_size": "26.9B",
        "quantization_level": "Q8_0",
    },
    "provenance_note": "Observed local Ollama metadata; architecture is recorded, not relabeled.",
}


class OrchestrationError(RuntimeError):
    """The isolated run plan would be unreproducible or unsafe."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrchestrationError("invalid JSON: %s" % path) from exc
    if not isinstance(payload, dict):
        raise OrchestrationError("JSON root must be an object: %s" % path)
    return dict(payload)


def _c02_answer_cohort_signature(rows: Any) -> Tuple[Tuple[int, str, int, str, float], ...]:
    if not isinstance(rows, list):
        raise OrchestrationError("C02 paired answer cohort rows must be an array")
    try:
        signature = tuple(
            (
                int(row["source_ordinal"]),
                str(row["question_id"]),
                int(row["n_hops"]),
                str(row["status"]),
                float(row["token_f1_at_800"]),
            )
            for row in rows
            if isinstance(row, Mapping)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OrchestrationError("C02 paired answer cohort row is malformed") from exc
    if len(signature) != len(rows):
        raise OrchestrationError("C02 paired answer cohort row must be an object")
    return signature


def assert_frozen_c02_answer_cohort(payload: Mapping[str, Any]) -> None:
    """Validate the predeclared C02 evaluation cohort without affecting runtime policy."""
    if dict(payload) != DIAGNOSTIC21_C02_ANSWER_COHORT:
        raise OrchestrationError("C02 paired answer cohort payload mismatch")
    rows = _c02_answer_cohort_signature(payload.get("rows"))
    expected = _c02_answer_cohort_signature(DIAGNOSTIC21_C02_ANSWER_COHORT["rows"])
    if rows != expected:
        raise OrchestrationError("C02 paired answer cohort row provenance mismatch")
    if len(rows) != DIAGNOSTIC21_ANSWER_YIELD_MINIMUM:
        raise OrchestrationError("C02 paired answer cohort denominator mismatch")
    if any(status != "ANSWER" for _, _, _, status, _ in rows):
        raise OrchestrationError("C02 paired answer cohort contains a non-ANSWER baseline row")
    roster = dict(DIAGNOSTIC21_ROSTER)
    if any(roster.get(source_ordinal) != question_id for source_ordinal, question_id, _, _, _ in rows):
        raise OrchestrationError("C02 paired answer cohort is outside the frozen diagnostic roster")
    values = [score for _, _, _, _, score in rows]
    if any(not math.isfinite(score) for score in values):
        raise OrchestrationError("C02 paired answer cohort has a non-finite baseline score")
    if abs(statistics.mean(values) - DIAGNOSTIC21_BASELINE["token_f1_answered_only"]) > DIAGNOSTIC21_FLOAT_TOLERANCE:
        raise OrchestrationError("C02 paired answer cohort baseline mean mismatch")


def load_frozen_c02_answer_cohort(exec_root: Path) -> Dict[str, Any]:
    """Load and hash-check the evaluation-only C02 cohort from the clean source snapshot."""
    path = exec_root / DIAGNOSTIC21_C02_ANSWER_COHORT_FILE
    if not path.is_file():
        raise OrchestrationError("C02 paired answer cohort artifact is missing: %s" % path)
    if sha256(path) != DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256:
        raise OrchestrationError("C02 paired answer cohort artifact hash mismatch")
    payload = read_json(path)
    assert_frozen_c02_answer_cohort(payload)
    return payload


def paired_c02_answer_cohort_score(per_question_path: Path, exec_root: Path) -> Dict[str, Any]:
    """Score exactly the frozen C02 ANSWER cohort from evaluator output, never from runtime policy."""
    cohort = load_frozen_c02_answer_cohort(exec_root)
    if not per_question_path.is_file():
        raise OrchestrationError("paired C02 score requires evaluator per_question.csv")
    try:
        with per_question_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"question_id", "status", "token_f1_at_800"}.issubset(reader.fieldnames):
                raise OrchestrationError("paired C02 score requires question_id/status/token_f1_at_800")
            by_question = {}
            for row in reader:
                question_id = str(row.get("question_id") or "")
                if question_id in DIAGNOSTIC21_C02_ANSWER_COHORT_QUESTION_IDS:
                    if question_id in by_question:
                        raise OrchestrationError("paired C02 score has duplicate cohort row: %s" % question_id)
                    by_question[question_id] = row
    except (OSError, csv.Error) as exc:
        raise OrchestrationError("paired C02 evaluator CSV is unreadable") from exc
    observed_rows = []
    for baseline in cohort["rows"]:
        question_id = str(baseline["question_id"])
        row = by_question.get(question_id)
        if row is None:
            raise OrchestrationError("paired C02 score is missing cohort row: %s" % question_id)
        status = row.get("status")
        if status == "EXECUTION_FAILURE":
            raise OrchestrationError("paired C02 score cohort execution failure: %s" % question_id)
        if status != "ANSWER":
            raise OrchestrationError("paired C02 score cohort row is not ANSWER: %s" % question_id)
        raw_score = row.get("token_f1_at_800")
        try:
            score = float(raw_score)
        except (TypeError, ValueError) as exc:
            raise OrchestrationError("paired C02 score is missing or invalid: %s" % question_id) from exc
        if not math.isfinite(score):
            raise OrchestrationError("paired C02 score is non-finite: %s" % question_id)
        observed_rows.append({"question_id": question_id, "status": status, "token_f1_at_800": score})
    if len(observed_rows) != DIAGNOSTIC21_ANSWER_YIELD_MINIMUM:
        raise OrchestrationError("paired C02 score denominator mismatch")
    return {
        "definition": "mean current token_f1_at_800 over the predeclared C02 ANSWER cohort",
        "denominator": len(observed_rows),
        "frozen_cohort_file": DIAGNOSTIC21_C02_ANSWER_COHORT_FILE,
        "frozen_cohort_sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
        "provenance": deepcopy(DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE),
        "rows": observed_rows,
        "token_f1_at_800": statistics.mean(row["token_f1_at_800"] for row in observed_rows),
    }


def write_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise OrchestrationError("refusing to overwrite immutable artifact: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl_new(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    if path.exists() or path.is_symlink():
        raise OrchestrationError("refusing to overwrite immutable artifact: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def chunks_for_entries(total: int = TOTAL_FULL226, size: int = CHUNK_SIZE) -> Tuple[Tuple[int, int], ...]:
    if total <= 0 or size <= 0:
        raise OrchestrationError("total and chunk size must be positive")
    return tuple((start, min(start + size - 1, total)) for start in range(1, total + 1, size))


def assert_full226_chunks(chunks: Sequence[Tuple[int, int]]) -> None:
    expected = chunks_for_entries()
    if tuple(chunks) != expected:
        raise OrchestrationError("full226 must use immutable 20-question checkpoints")


def _entry_signature(entries: Any) -> Tuple[Tuple[int, str, int], ...]:
    if not isinstance(entries, list):
        raise OrchestrationError("manifest.entries must be an array")
    result = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise OrchestrationError("manifest entry must be an object")
        try:
            result.append((int(entry["ordinal"]), str(entry["question_id"]), int(entry["n_hops"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise OrchestrationError("invalid frozen manifest entry") from exc
    if not result:
        raise OrchestrationError("manifest has no entries")
    return tuple(result)


def assert_kure_only(configuration: Mapping[str, Any]) -> None:
    if configuration.get("retriever") != "kure":
        raise OrchestrationError("V2 execution permits only the KURE retriever")
    for key, expected in (("model", EXPECTED_RUNTIME["model"]), ("seed", 0), ("num_ctx", 32768)):
        if configuration.get(key) != expected:
            raise OrchestrationError("frozen configuration %s mismatch" % key)
    if configuration.get("ollama_endpoint") != EXPECTED_RUNTIME["endpoint"]:
        raise OrchestrationError("V2 must use the offline endpoint on port 11435")
    runtime = configuration.get("runtime_determinism")
    if not isinstance(runtime, Mapping) or runtime.get("num_parallel") != 1:
        raise OrchestrationError("frozen runtime must declare num_parallel=1")


def assert_reference_is_read_only(primary: Mapping[str, Any], reference: Mapping[str, Any], primary_path: Path, reference_path: Path) -> Dict[str, Any]:
    """Validate the paired reference without scheduling any BM25 operation."""
    from runtime.comparison_guard import validate_retriever_comparison

    assert_kure_only(dict(primary.get("frozen_configuration") or {}))
    reference_configuration = reference.get("frozen_configuration")
    if not isinstance(reference_configuration, Mapping) or reference_configuration.get("retriever") != "bm25":
        raise OrchestrationError("comparison reference must be BM25 metadata only")
    comparison = validate_retriever_comparison(primary, reference, primary_path, reference_path)
    if comparison.get("primary_retriever") != "kure" or comparison.get("reference_retriever") != "bm25":
        raise OrchestrationError("comparison pair is not KURE primary / BM25 reference")
    return {
        **comparison,
        "bm25_execution": "FORBIDDEN",
        "bm25_reference_use": "READ_ONLY_CONFIGURATION_GUARD",
    }


def assert_no_external_score_injection(command: Sequence[str]) -> None:
    forbidden = [item for item in command if item == "--lf-eval-scores" or item.startswith("--lf-eval-scores=")]
    if forbidden:
        raise OrchestrationError("external LF-Eval score injection is forbidden")


def assert_kure_execution_command(command: Sequence[str]) -> None:
    values = list(command)
    if "--retriever" not in values:
        raise OrchestrationError("execution command must declare retriever")
    index = values.index("--retriever")
    if index + 1 >= len(values) or values[index + 1] != "kure":
        raise OrchestrationError("execution command must use KURE, never BM25")
    assert_no_external_score_injection(values)


def _safe_relative_artifact(exec_root: Path, declared: Any, label: str) -> Path:
    if not isinstance(declared, str) or not declared:
        raise OrchestrationError("missing local artifact path: %s" % label)
    relative = Path(declared)
    if relative.is_absolute() or ".." in relative.parts:
        raise OrchestrationError("artifact path must be relative without '..': %s" % label)
    return exec_root / relative


def verify_kure_artifacts(configuration: Mapping[str, Any], exec_root: Path) -> Dict[str, Any]:
    """Hash only local KURE files; this never initializes a searcher."""
    provenance = configuration.get("retriever_provenance")
    if not isinstance(provenance, Mapping):
        raise OrchestrationError("KURE retriever provenance is missing")
    verified: Dict[str, str] = {}
    for path_key, hash_key in (
        ("normalized_corpus_path", "normalized_corpus_sha256"),
        ("vectors_path", "vectors_sha256"),
        ("provision_ids_path", "provision_ids_sha256"),
    ):
        artifact = _safe_relative_artifact(exec_root, provenance.get(path_key), path_key)
        expected = provenance.get(hash_key)
        if not isinstance(expected, str) or len(expected) != 64:
            raise OrchestrationError("invalid KURE provenance hash: %s" % hash_key)
        if not artifact.is_file():
            raise OrchestrationError("KURE artifact is missing: %s" % artifact)
        if sha256(artifact) != expected:
            raise OrchestrationError("KURE artifact hash mismatch: %s" % path_key)
        verified[path_key] = expected
    model_root = _safe_relative_artifact(exec_root, provenance.get("model_path"), "model_path")
    model_weights = model_root / "model.safetensors"
    expected_weights = provenance.get("model_weights_sha256")
    if not isinstance(expected_weights, str) or len(expected_weights) != 64:
        raise OrchestrationError("invalid KURE model_weights_sha256")
    if not model_weights.is_file():
        raise OrchestrationError("KURE model.safetensors is missing: %s" % model_weights)
    if sha256(model_weights) != expected_weights:
        raise OrchestrationError("KURE model.safetensors hash mismatch")
    verified["model.safetensors"] = expected_weights
    return verified


def check_local_ollama_readiness(configuration: Mapping[str, Any], timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Non-generative local readiness check; it never calls /api/generate."""
    endpoint = str(configuration.get("ollama_endpoint") or "")
    model = str(configuration.get("model") or "")
    if not endpoint.startswith("http://127.0.0.1:") or not endpoint.endswith("/api/generate"):
        raise OrchestrationError("readiness requires the fixed local generate endpoint")
    if model != EXPECTED_RUNTIME["model"]:
        raise OrchestrationError("readiness model alias mismatch")
    tags_url = endpoint[: -len("/generate")] + "/tags"
    try:
        with urlopen(tags_url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise OrchestrationError("local Ollama readiness check failed") from exc
    provenance = configuration.get("model_provenance")
    if not isinstance(provenance, Mapping):
        raise OrchestrationError("readiness model provenance is missing")
    if provenance.get("alias") != model:
        raise OrchestrationError("readiness provenance alias mismatch")
    expected_digest = provenance.get("ollama_manifest_digest")
    expected_details = provenance.get("ollama_details")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise OrchestrationError("readiness manifest digest is missing")
    if not isinstance(expected_details, Mapping):
        raise OrchestrationError("readiness model details are missing")
    models = payload.get("models") if isinstance(payload, Mapping) else None
    aliases, matched = set(), []
    allowed_names = {model, model + ":latest"}
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, Mapping):
                continue
            names = {str(item[key]) for key in ("name", "model") if isinstance(item.get(key), str)}
            aliases.update(names)
            if names & allowed_names:
                matched.append(dict(item))
    if not matched:
        raise OrchestrationError("local Ollama alias is unavailable: %s" % model)
    for item in matched:
        details = item.get("details")
        if item.get("digest") != expected_digest:
            continue
        if isinstance(details, Mapping) and all(details.get(key) == expected_details.get(key) for key in ("family", "parameter_size", "quantization_level")):
            matched_name = sorted({str(item[key]) for key in ("name", "model") if item.get(key) in allowed_names})[0]
            return {
                "endpoint": endpoint,
                "tags_url": tags_url,
                "model_alias": model,
                "resolved_model_name": matched_name,
                "manifest_digest": expected_digest,
                "details": {key: details[key] for key in ("family", "parameter_size", "quantization_level")},
                "available_aliases": sorted(aliases),
            }
    raise OrchestrationError("local Ollama model provenance does not match the frozen alias")


def _copy_manifest(source: Mapping[str, Any], name: str, configuration: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], role: str) -> Dict[str, Any]:
    output = deepcopy(dict(source))
    output["name"] = name
    output["entries"] = [dict(entry) for entry in entries]
    output["frozen_configuration"] = dict(configuration)
    selection = dict(output.get("selection") or {})
    selection.update({
        "method": "V2 immutable frozen selection derived without reordering from the C5 full226 manifest",
        "entry_count": len(entries),
        "execution_role": role,
        "lf_eval": "excluded; no LF-Eval invocation or score injection",
    })
    output["selection"] = selection
    output["purpose"] = (
        "C34 type-aware redundant public projection and gap-anchor coverage preserve the C32 retry-only "
        "qualifying carry-forward and C31 shared public-answer "
        "contract and the V2 c08 offline KURE "
        "candidate with c04 core/auxiliary evidence roles, c05 repair-collision recovery, "
        "c06 S2 axis-canonical projection, and c08 S1 repair-induced retrieval-list dedupe. "
        "BM25 is reference-only metadata and must never be executed; BM25 search/index "
        "execution, ParSeR, and LF-Eval are prohibited."
    )
    return output


def _with_c31_condition(condition: str) -> str:
    if not isinstance(condition, str) or not condition:
        raise OrchestrationError("C31 condition must be non-empty")
    return condition if condition.endswith(DIAGNOSTIC21_C31_CONDITION_SUFFIX) else condition + DIAGNOSTIC21_C31_CONDITION_SUFFIX


def _full_to_smoke_c31_condition(condition: str) -> str:
    """Derive smoke from exactly one frozen full226 token, preserving all lineage."""
    base = condition[:-len(DIAGNOSTIC21_C31_CONDITION_SUFFIX)] if condition.endswith(DIAGNOSTIC21_C31_CONDITION_SUFFIX) else condition
    if base.count("full226") != 1:
        raise OrchestrationError("C31 smoke condition requires exactly one full226 token")
    return _with_c31_condition(base.replace("full226", "smoke3"))


def _apply_c31_public_answer_contract(configuration: Dict[str, Any]) -> None:
    """Freeze the runtime/harness/paired-manifest public answer contract together."""
    configuration.update(PUBLIC_ANSWER_FROZEN_CONFIGURATION)
    configuration["condition"] = _with_c31_condition(str(configuration.get("condition") or ""))


def _with_c32_condition(condition: str) -> str:
    if not isinstance(condition, str) or not condition:
        raise OrchestrationError("C32 condition must be non-empty")
    base = (
        condition[:-len(DIAGNOSTIC21_C32_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C32_CONDITION_SUFFIX)
        else condition
    )
    return _with_c31_condition(base) + DIAGNOSTIC21_C32_CONDITION_SUFFIX


def _full_to_smoke_c32_condition(condition: str) -> str:
    """Derive smoke from exactly one C32 full226 condition token."""
    base = (
        condition[:-len(DIAGNOSTIC21_C32_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C32_CONDITION_SUFFIX)
        else condition
    )
    return _with_c32_condition(_full_to_smoke_c31_condition(base))


def _apply_c32_public_answer_contract(configuration: Dict[str, Any]) -> None:
    condition = str(configuration.get("condition") or "")
    if condition.endswith(DIAGNOSTIC21_C32_CONDITION_SUFFIX):
        configuration["condition"] = condition[:-len(DIAGNOSTIC21_C32_CONDITION_SUFFIX)]
    _apply_c31_public_answer_contract(configuration)
    configuration["condition"] = _with_c32_condition(
        str(configuration.get("condition") or "")
    )


def _with_c33_condition(condition: str) -> str:
    if not isinstance(condition, str) or not condition:
        raise OrchestrationError("C33 condition must be non-empty")
    base = (
        condition[:-len(DIAGNOSTIC21_C33_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C33_CONDITION_SUFFIX)
        else condition
    )
    return _with_c32_condition(base) + DIAGNOSTIC21_C33_CONDITION_SUFFIX


def _full_to_smoke_c33_condition(condition: str) -> str:
    """Derive smoke from exactly one C33 full226 condition token."""
    base = (
        condition[:-len(DIAGNOSTIC21_C33_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C33_CONDITION_SUFFIX)
        else condition
    )
    return _with_c33_condition(_full_to_smoke_c32_condition(base))


def _apply_c33_public_answer_contract(configuration: Dict[str, Any]) -> None:
    condition = str(configuration.get("condition") or "")
    if condition.endswith(DIAGNOSTIC21_C33_CONDITION_SUFFIX):
        configuration["condition"] = condition[:-len(DIAGNOSTIC21_C33_CONDITION_SUFFIX)]
    _apply_c32_public_answer_contract(configuration)
    configuration["condition"] = _with_c33_condition(
        str(configuration.get("condition") or "")
    )


def _with_c34_condition(condition: str) -> str:
    if not isinstance(condition, str) or not condition:
        raise OrchestrationError("C34 condition must be non-empty")
    base = (
        condition[:-len(DIAGNOSTIC21_C34_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C34_CONDITION_SUFFIX)
        else condition
    )
    return _with_c33_condition(base) + DIAGNOSTIC21_C34_CONDITION_SUFFIX


def _full_to_smoke_c34_condition(condition: str) -> str:
    """Derive smoke from exactly one C34 full226 condition token."""
    base = (
        condition[:-len(DIAGNOSTIC21_C34_CONDITION_SUFFIX)]
        if condition.endswith(DIAGNOSTIC21_C34_CONDITION_SUFFIX)
        else condition
    )
    return _with_c34_condition(_full_to_smoke_c33_condition(base))


def _apply_c34_public_answer_contract(configuration: Dict[str, Any]) -> None:
    condition = str(configuration.get("condition") or "")
    if condition.endswith(DIAGNOSTIC21_C34_CONDITION_SUFFIX):
        configuration["condition"] = condition[:-len(DIAGNOSTIC21_C34_CONDITION_SUFFIX)]
    _apply_c33_public_answer_contract(configuration)
    configuration["condition"] = _with_c34_condition(
        str(configuration.get("condition") or "")
    )


def build_v2_manifests(primary_source: Mapping[str, Any], reference_source: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    source_entries = list(primary_source.get("entries") or [])
    if _entry_signature(source_entries) != _entry_signature(reference_source.get("entries")):
        raise OrchestrationError("source KURE/BM25 manifest order differs")
    if len(source_entries) != TOTAL_FULL226:
        raise OrchestrationError("V2 full run requires the exact frozen 226-entry order")
    if [int(entry["ordinal"]) for entry in source_entries] != list(range(1, TOTAL_FULL226 + 1)):
        raise OrchestrationError("frozen 226 ordinals must be contiguous")

    primary_configuration = deepcopy(dict(primary_source.get("frozen_configuration") or {}))
    reference_configuration = deepcopy(dict(reference_source.get("frozen_configuration") or {}))
    primary_source_condition = primary_configuration.get("condition")
    reference_source_condition = reference_configuration.get("condition")
    if not isinstance(primary_source_condition, str) or not primary_source_condition:
        raise OrchestrationError("primary frozen full condition is missing")
    if not isinstance(reference_source_condition, str) or not reference_source_condition:
        raise OrchestrationError("reference frozen full condition is missing")
    primary_configuration.update({
        "retriever": "kure",
        "model": EXPECTED_RUNTIME["model"],
        "seed": 0,
        "num_ctx": 32768,
        "ollama_endpoint": EXPECTED_RUNTIME["endpoint"],
    })
    runtime = dict(primary_configuration.get("runtime_determinism") or {})
    runtime.update({"num_parallel": 1, "seed_forwarding": "ollama_options_seed"})
    primary_configuration["runtime_determinism"] = runtime
    primary_configuration["model_provenance"] = deepcopy(QWEN_MODEL_PROVENANCE)
    _apply_c34_public_answer_contract(primary_configuration)
    assert_kure_only(primary_configuration)

    reference_configuration = deepcopy(primary_configuration)
    reference_configuration["condition"] = reference_source_condition
    reference_configuration["retriever"] = "bm25"
    reference_configuration.pop("retriever_provenance", None)
    _apply_c34_public_answer_contract(reference_configuration)
    full = _copy_manifest(primary_source, PRIMARY_FROZEN_NAME, primary_configuration, source_entries, "PRIMARY_KURE_EXECUTION")
    reference = _copy_manifest(reference_source, REFERENCE_FROZEN_NAME, reference_configuration, source_entries, "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED")

    smoke_entries: List[Mapping[str, Any]] = []
    seen_hops = set()
    for entry in source_entries:
        hop = int(entry["n_hops"])
        if hop in {1, 2, 3} and hop not in seen_hops:
            smoke_entries.append(entry)
            seen_hops.add(hop)
        if seen_hops == {1, 2, 3}:
            break
    if {int(item["n_hops"]) for item in smoke_entries} != {1, 2, 3}:
        raise OrchestrationError("frozen full226 has no deterministic 1/2/3-hop smoke trio")
    # Smoke execution ordinals are contiguous; source_ordinal preserves frozen full226 provenance.
    smoke_entries = [
        {**dict(entry), "source_ordinal": int(entry["ordinal"]), "ordinal": index}
        for index, entry in enumerate(smoke_entries, start=1)
    ]
    smoke_configuration = deepcopy(primary_configuration)
    smoke_configuration["condition"] = _full_to_smoke_c34_condition(str(primary_configuration["condition"]))
    smoke_reference_configuration = deepcopy(reference_configuration)
    smoke_reference_configuration["condition"] = _full_to_smoke_c34_condition(str(reference_configuration["condition"]))
    return {
        "full": full,
        "reference": reference,
        "smoke": _copy_manifest(primary_source, SMOKE_FROZEN_NAME, smoke_configuration, smoke_entries, "OPERATIONAL_SMOKE_ONLY_NOT_BENCHMARK_EVIDENCE"),
        "smoke_reference": _copy_manifest(reference_source, SMOKE_REFERENCE_FROZEN_NAME, smoke_reference_configuration, smoke_entries, "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED"),
    }



def _diagnostic21_entries(source_entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Reindex the approved C02 diagnostic roster without reordering it."""
    if len(source_entries) != TOTAL_FULL226:
        raise OrchestrationError("diagnostic21 requires the exact 226-entry source manifest")
    by_ordinal = {int(entry.get("ordinal", 0)): dict(entry) for entry in source_entries}
    if sorted(by_ordinal) != list(range(1, TOTAL_FULL226 + 1)):
        raise OrchestrationError("diagnostic21 source ordinals must be contiguous 1..226")
    selected: List[Dict[str, Any]] = []
    for ordinal, (source_ordinal, question_id) in enumerate(DIAGNOSTIC21_ROSTER, start=1):
        source = by_ordinal.get(source_ordinal)
        if source is None or str(source.get("question_id")) != question_id:
            raise OrchestrationError(
                "diagnostic21 source roster mismatch at source ordinal %d" % source_ordinal
            )
        cohort = DIAGNOSTIC21_COHORT_BY_SOURCE_ORDINAL.get(source_ordinal)
        if cohort is None:
            raise OrchestrationError("diagnostic21 source ordinal lacks a cohort: %d" % source_ordinal)
        selected.append({
            **source,
            "ordinal": ordinal,
            "source_ordinal": source_ordinal,
            "diagnostic_cohort": cohort,
        })
    if len(selected) != DIAGNOSTIC21_ENTRY_COUNT:
        raise OrchestrationError("diagnostic21 roster must contain exactly 21 entries")
    if len({entry["source_ordinal"] for entry in selected}) != DIAGNOSTIC21_ENTRY_COUNT:
        raise OrchestrationError("diagnostic21 source ordinals must be unique")
    if len({entry["question_id"] for entry in selected}) != DIAGNOSTIC21_ENTRY_COUNT:
        raise OrchestrationError("diagnostic21 question IDs must be unique")
    observed = {name: sum(entry["diagnostic_cohort"] == name for entry in selected) for name in DIAGNOSTIC21_COHORT_COUNTS}
    if observed != DIAGNOSTIC21_COHORT_COUNTS:
        raise OrchestrationError("diagnostic21 cohorts are not the approved 8/7/6 partition")
    return selected


def _diagnostic21_selection(
    entries: Sequence[Mapping[str, Any]],
    primary_source_sha256: str,
    reference_source_sha256: str,
    primary_source_condition: str,
    reference_source_condition: str,
) -> Dict[str, Any]:
    roster = [
        {
            "ordinal": int(entry["ordinal"]),
            "source_ordinal": int(entry["source_ordinal"]),
            "question_id": str(entry["question_id"]),
            "n_hops": int(entry["n_hops"]),
            "diagnostic_cohort": str(entry["diagnostic_cohort"]),
        }
        for entry in entries
    ]
    return {
        "candidate_id": DIAGNOSTIC21_CANDIDATE_ID,
        "method": (
            "C34 preserves the C30 paired C02 gate, C31 shared public-answer contract, "
            "and C32 validator-only qualifying carry-forward. It preserves repeated Korean "
            "gap result-object anchors in explicit query terms and deterministically chooses "
            "the redundant public projection role only for exact nonempty target/core-citation "
            "matches, with a bounded case-fact retry before legal-rule demotion. C30 adds the fixed "
            "four-item C02 ANSWER paired evaluation gate plus S3 bounded public "
            "conclusion recovery and first-invalid conditional-exception carry-forward "
            "on the C24 fixed roster reindexed from immutable C02 source ordinals"
        ),
        "source_frozen_conditions": {
            "primary": primary_source_condition,
            "reference": reference_source_condition,
        },
        "entry_count": DIAGNOSTIC21_ENTRY_COUNT,
        "source_primary_manifest_sha256": primary_source_sha256,
        "source_reference_manifest_sha256": reference_source_sha256,
        "roster": roster,
        "roster_sha256": canonical_sha256({"roster": roster}),
        "cohort_counts": dict(DIAGNOSTIC21_COHORT_COUNTS),
        "baseline": deepcopy(DIAGNOSTIC21_BASELINE),
        "baseline_sha256": canonical_sha256(DIAGNOSTIC21_BASELINE),
        "paired_c02_answer_cohort": deepcopy(DIAGNOSTIC21_C02_ANSWER_COHORT),
        "paired_c02_answer_cohort_sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
        "nonregression_minimums": dict(DIAGNOSTIC21_NONREGRESSION_MINIMUMS),
        "answer_yield_minimum": DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
        "condition_lineage": deepcopy(DIAGNOSTIC21_CONDITION_LINEAGE),
        "implementation_parent_commit": DIAGNOSTIC21_IMPLEMENTATION_PARENT_COMMIT,
        "c23_note": "C23 is static analysis only and changes no runtime behavior.",
        "skill_files": deepcopy(DIAGNOSTIC21_SKILL_FILES),
        "reranker_provenance": deepcopy(DIAGNOSTIC21_RERANKER_PROVENANCE),
        "round_merge_provenance": {
            "runtime_round_merge_mode": DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE,
            "c02_saved_stage_round_merge_mode": DIAGNOSTIC21_C02_ROUND_MERGE_MODE,
            "equivalence_claimed": False,
            "c23_candidate_replay": "STATIC_ANALYSIS_ONLY; no candidate replay rule is enabled at runtime.",
        },
        "c22_capability": deepcopy(DIAGNOSTIC21_C22_CAPABILITY),
        "c28_capabilities": deepcopy(DIAGNOSTIC21_C28_CAPABILITIES),
        "c29_capabilities": deepcopy(DIAGNOSTIC21_C29_CAPABILITIES),
        "c30_capabilities": deepcopy(DIAGNOSTIC21_C30_CAPABILITIES),
        "c30_source_provenance": deepcopy(DIAGNOSTIC21_C30_SOURCE_PROVENANCE),
        "c31_capabilities": deepcopy(DIAGNOSTIC21_C31_CAPABILITIES),
        "c31_source_provenance": deepcopy(DIAGNOSTIC21_C31_SOURCE_PROVENANCE),
        "c32_capabilities": deepcopy(DIAGNOSTIC21_C32_CAPABILITIES),
        "c32_source_provenance": deepcopy(DIAGNOSTIC21_C32_SOURCE_PROVENANCE),
        "c33_capabilities": deepcopy(DIAGNOSTIC21_C33_CAPABILITIES),
        "c33_source_provenance": deepcopy(DIAGNOSTIC21_C33_SOURCE_PROVENANCE),
        "c34_capabilities": deepcopy(DIAGNOSTIC21_C34_CAPABILITIES),
        "c34_source_provenance": deepcopy(DIAGNOSTIC21_C34_SOURCE_PROVENANCE),
        "semantic_authority": DIAGNOSTIC21_SEMANTIC_AUTHORITY,
        "runtime_artifact_path_provenance": {
            "repo_relative_required": ["source_dataset.path", "kure paths", "bge reranker path"],
            "qwen_ollama_blob_exact_local_runtime_exception": QWEN_MODEL_PROVENANCE["ollama_model_blob"],
        },
        "skill_sha256_recording": "ExperimentRecord automatically persists all runtime skill_sha256 values.",
        "execution_role": "PRIMARY_KURE_DIAGNOSTIC_EXECUTION",
        "lf_eval": "excluded; no LF-Eval invocation or score injection",
    }


def build_diagnostic21_manifests(
    primary_source: Mapping[str, Any],
    reference_source: Mapping[str, Any],
    primary_source_sha256: str,
    reference_source_sha256: str,
) -> Dict[str, Dict[str, Any]]:
    """Create the fixed 21-row KURE primary and metadata-only BM25 manifests."""
    if primary_source_sha256 != DIAGNOSTIC21_SOURCE_PRIMARY_SHA256:
        raise OrchestrationError("diagnostic21 primary source manifest hash mismatch")
    if reference_source_sha256 != DIAGNOSTIC21_SOURCE_REFERENCE_SHA256:
        raise OrchestrationError("diagnostic21 reference source manifest hash mismatch")
    source_entries = list(primary_source.get("entries") or [])
    if _entry_signature(source_entries) != _entry_signature(reference_source.get("entries")):
        raise OrchestrationError("diagnostic21 source KURE/BM25 manifest order differs")
    entries = _diagnostic21_entries(source_entries)
    primary_configuration = deepcopy(dict(primary_source.get("frozen_configuration") or {}))
    reference_configuration = deepcopy(dict(reference_source.get("frozen_configuration") or {}))
    primary_source_condition = primary_configuration.get("condition")
    reference_source_condition = reference_configuration.get("condition")
    if not isinstance(primary_source_condition, str) or not primary_source_condition:
        raise OrchestrationError("diagnostic21 primary source condition is missing")
    if not isinstance(reference_source_condition, str) or not reference_source_condition:
        raise OrchestrationError("diagnostic21 reference source condition is missing")
    for label, configuration in (("primary", primary_configuration), ("reference", reference_configuration)):
        if configuration.get("round_merge_mode") != DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE:
            raise OrchestrationError("diagnostic21 %s source round_merge_mode mismatch" % label)
        base_condition = configuration["condition"]
        if base_condition.endswith(DIAGNOSTIC21_C34_CONDITION_SUFFIX):
            base_condition = base_condition[:-len(DIAGNOSTIC21_C34_CONDITION_SUFFIX)]
        if base_condition.endswith(DIAGNOSTIC21_C33_CONDITION_SUFFIX):
            base_condition = base_condition[:-len(DIAGNOSTIC21_C33_CONDITION_SUFFIX)]
        if base_condition.endswith(DIAGNOSTIC21_C32_CONDITION_SUFFIX):
            base_condition = base_condition[:-len(DIAGNOSTIC21_C32_CONDITION_SUFFIX)]
        if base_condition.endswith(DIAGNOSTIC21_C31_CONDITION_SUFFIX):
            base_condition = base_condition[:-len(DIAGNOSTIC21_C31_CONDITION_SUFFIX)]
        configuration["condition"] = (
            base_condition + DIAGNOSTIC21_C30_CONDITION_SUFFIX + DIAGNOSTIC21_C31_CONDITION_SUFFIX
        )
        _apply_c34_public_answer_contract(configuration)
        configuration["reranker_provenance"] = deepcopy(DIAGNOSTIC21_RERANKER_PROVENANCE)
    assert_kure_only(primary_configuration)
    if reference_configuration.get("retriever") != "bm25":
        raise OrchestrationError("diagnostic21 reference source must remain BM25 metadata")
    selection = _diagnostic21_selection(
        entries,
        primary_source_sha256,
        reference_source_sha256,
        primary_configuration["condition"],
        reference_configuration["condition"],
    )
    primary = _copy_manifest(
        primary_source,
        DIAGNOSTIC21_PRIMARY_FROZEN_NAME,
        primary_configuration,
        entries,
        "PRIMARY_KURE_DIAGNOSTIC_EXECUTION",
    )
    primary["selection"] = selection
    primary["purpose"] = (
        "C34 preserves the C30 paired C02 gate, C31 shared one-to-four-sentence public-answer "
        "contract, and C32 exact qualifying carry-forward citations in validator-only retry context, "
        "then preserves repeated Korean gap result-object anchors in explicit query terms and applies "
        "only the exact type-aware redundant public projection with a bounded case-fact retry. "
        "C30 adds the fixed four-item "
        "C02 ANSWER paired evaluation gate plus S3 2-to-4 public-conclusion recovery "
        "with complete target/provision coverage and first-invalid conditional-exception "
        "carry-forward on the failure-and-coverage roster. KURE is the only executable "
        "retriever; BM25 remains paired read-only metadata. No BM25, ParSeR, or LF-Eval "
        "execution is permitted."
    )
    reference = _copy_manifest(
        reference_source,
        DIAGNOSTIC21_REFERENCE_FROZEN_NAME,
        reference_configuration,
        entries,
        "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED",
    )
    reference_selection = deepcopy(selection)
    reference_selection["execution_role"] = "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED"
    reference["selection"] = reference_selection
    reference["purpose"] = primary["purpose"]
    assert_diagnostic21_manifest_integrity(primary, reference)
    return {"diagnostic21": primary, "diagnostic21_reference": reference}


def _diagnostic21_entry_signature(entries: Sequence[Mapping[str, Any]]) -> Tuple[Tuple[int, int, str, int, str], ...]:
    try:
        return tuple(
            (
                int(entry["ordinal"]),
                int(entry["source_ordinal"]),
                str(entry["question_id"]),
                int(entry["n_hops"]),
                str(entry["diagnostic_cohort"]),
            )
            for entry in entries
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OrchestrationError("diagnostic21 entry lacks ordinal/source_ordinal/cohort fields") from exc


def assert_diagnostic21_manifest_integrity(
    primary: Mapping[str, Any], reference: Mapping[str, Any]
) -> None:
    """Fail closed on the exact roster, immutable baseline, and no-BM25 contract."""
    primary_entries = list(primary.get("entries") or [])
    reference_entries = list(reference.get("entries") or [])
    if _diagnostic21_entry_signature(primary_entries) != _diagnostic21_entry_signature(reference_entries):
        raise OrchestrationError("diagnostic21 primary/reference entries differ")
    if [int(entry.get("ordinal", 0)) for entry in primary_entries] != list(range(1, DIAGNOSTIC21_ENTRY_COUNT + 1)):
        raise OrchestrationError("diagnostic21 execution ordinals must be 1..21")
    expected = list(DIAGNOSTIC21_ROSTER)
    actual = [(int(entry.get("source_ordinal", 0)), str(entry.get("question_id") or "")) for entry in primary_entries]
    if actual != expected:
        raise OrchestrationError("diagnostic21 source roster differs from the approved exact roster")
    cohorts = {str(entry.get("diagnostic_cohort") or ""): 0 for entry in primary_entries}
    for entry in primary_entries:
        cohort = str(entry.get("diagnostic_cohort") or "")
        cohorts[cohort] = cohorts.get(cohort, 0) + 1
    if cohorts != DIAGNOSTIC21_COHORT_COUNTS:
        raise OrchestrationError("diagnostic21 cohort partition differs from 8 failures/7 accepted ABSTAINS/6 S2 losses")
    primary_configuration = dict(primary.get("frozen_configuration") or {})
    assert_kure_only(primary_configuration)
    if primary_configuration.get("reranker_provenance") != DIAGNOSTIC21_RERANKER_PROVENANCE:
        raise OrchestrationError("diagnostic21 primary reranker provenance mismatch")
    reference_configuration = reference.get("frozen_configuration")
    if not isinstance(reference_configuration, Mapping) or reference_configuration.get("retriever") != "bm25":
        raise OrchestrationError("diagnostic21 reference must be metadata-only BM25")
    if reference_configuration.get("reranker_provenance") != DIAGNOSTIC21_RERANKER_PROVENANCE:
        raise OrchestrationError("diagnostic21 reference reranker provenance mismatch")
    selection = primary.get("selection")
    if not isinstance(selection, Mapping):
        raise OrchestrationError("diagnostic21 selection metadata is missing")
    if selection.get("source_primary_manifest_sha256") != DIAGNOSTIC21_SOURCE_PRIMARY_SHA256:
        raise OrchestrationError("diagnostic21 recorded primary source hash mismatch")
    if selection.get("source_reference_manifest_sha256") != DIAGNOSTIC21_SOURCE_REFERENCE_SHA256:
        raise OrchestrationError("diagnostic21 recorded reference source hash mismatch")
    roster = [
        {
            "ordinal": int(entry["ordinal"]),
            "source_ordinal": int(entry["source_ordinal"]),
            "question_id": str(entry["question_id"]),
            "n_hops": int(entry["n_hops"]),
            "diagnostic_cohort": str(entry["diagnostic_cohort"]),
        }
        for entry in primary_entries
    ]
    if selection.get("roster") != roster or selection.get("roster_sha256") != canonical_sha256({"roster": roster}):
        raise OrchestrationError("diagnostic21 roster hash mismatch")
    if selection.get("baseline") != DIAGNOSTIC21_BASELINE or selection.get("baseline_sha256") != canonical_sha256(DIAGNOSTIC21_BASELINE):
        raise OrchestrationError("diagnostic21 baseline mismatch")
    if selection.get("paired_c02_answer_cohort") != DIAGNOSTIC21_C02_ANSWER_COHORT:
        raise OrchestrationError("diagnostic21 paired C02 answer cohort mismatch")
    if selection.get("paired_c02_answer_cohort_sha256") != DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256:
        raise OrchestrationError("diagnostic21 paired C02 answer cohort hash mismatch")
    if selection.get("answer_yield_minimum") != DIAGNOSTIC21_ANSWER_YIELD_MINIMUM:
        raise OrchestrationError("diagnostic21 answer yield minimum mismatch")
    if selection.get("cohort_counts") != DIAGNOSTIC21_COHORT_COUNTS:
        raise OrchestrationError("diagnostic21 cohort count metadata mismatch")
    if selection.get("nonregression_minimums") != DIAGNOSTIC21_NONREGRESSION_MINIMUMS:
        raise OrchestrationError("diagnostic21 numeric baseline gates mismatch")
    if selection.get("condition_lineage") != DIAGNOSTIC21_CONDITION_LINEAGE:
        raise OrchestrationError("diagnostic21 condition lineage mismatch")
    if selection.get("skill_files") != DIAGNOSTIC21_SKILL_FILES:
        raise OrchestrationError("diagnostic21 skill hash manifest mismatch")
    if selection.get("reranker_provenance") != DIAGNOSTIC21_RERANKER_PROVENANCE:
        raise OrchestrationError("diagnostic21 reranker selection provenance mismatch")
    expected_round_merge = {
        "runtime_round_merge_mode": DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE,
        "c02_saved_stage_round_merge_mode": DIAGNOSTIC21_C02_ROUND_MERGE_MODE,
        "equivalence_claimed": False,
        "c23_candidate_replay": "STATIC_ANALYSIS_ONLY; no candidate replay rule is enabled at runtime.",
    }
    if selection.get("round_merge_provenance") != expected_round_merge:
        raise OrchestrationError("diagnostic21 round-merge provenance mismatch")
    if selection.get("c22_capability") != DIAGNOSTIC21_C22_CAPABILITY:
        raise OrchestrationError("diagnostic21 C22 capability mismatch")
    if selection.get("c28_capabilities") != DIAGNOSTIC21_C28_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C28 capability mismatch")
    if selection.get("c29_capabilities") != DIAGNOSTIC21_C29_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C29 capability mismatch")
    if selection.get("c30_capabilities") != DIAGNOSTIC21_C30_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C30 capability mismatch")
    if selection.get("c30_source_provenance") != DIAGNOSTIC21_C30_SOURCE_PROVENANCE:
        raise OrchestrationError("diagnostic21 C30 source provenance mismatch")
    if selection.get("c31_capabilities") != DIAGNOSTIC21_C31_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C31 capability mismatch")
    if selection.get("c31_source_provenance") != DIAGNOSTIC21_C31_SOURCE_PROVENANCE:
        raise OrchestrationError("diagnostic21 C31 source provenance mismatch")
    if selection.get("c32_capabilities") != DIAGNOSTIC21_C32_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C32 capability mismatch")
    if selection.get("c32_source_provenance") != DIAGNOSTIC21_C32_SOURCE_PROVENANCE:
        raise OrchestrationError("diagnostic21 C32 source provenance mismatch")
    if selection.get("c33_capabilities") != DIAGNOSTIC21_C33_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C33 capability mismatch")
    if selection.get("c33_source_provenance") != DIAGNOSTIC21_C33_SOURCE_PROVENANCE:
        raise OrchestrationError("diagnostic21 C33 source provenance mismatch")
    if selection.get("c34_capabilities") != DIAGNOSTIC21_C34_CAPABILITIES:
        raise OrchestrationError("diagnostic21 C34 capability mismatch")
    if selection.get("c34_source_provenance") != DIAGNOSTIC21_C34_SOURCE_PROVENANCE:
        raise OrchestrationError("diagnostic21 C34 source provenance mismatch")
    if selection.get("semantic_authority") != DIAGNOSTIC21_SEMANTIC_AUTHORITY:
        raise OrchestrationError("diagnostic21 semantic authority mismatch")
    if selection.get("runtime_artifact_path_provenance") != {
        "repo_relative_required": ["source_dataset.path", "kure paths", "bge reranker path"],
        "qwen_ollama_blob_exact_local_runtime_exception": QWEN_MODEL_PROVENANCE["ollama_model_blob"],
    }:
        raise OrchestrationError("diagnostic21 runtime artifact path provenance mismatch")
    if selection.get("candidate_id") != DIAGNOSTIC21_CANDIDATE_ID:
        raise OrchestrationError("diagnostic21 candidate identifier mismatch")
    if selection.get("source_frozen_conditions") != {
        "primary": primary_configuration.get("condition"),
        "reference": reference_configuration.get("condition"),
    }:
        raise OrchestrationError("diagnostic21 source condition lineage mismatch")
    for label, configuration in (("primary", primary_configuration), ("reference", reference_configuration)):
        condition = configuration.get("condition")
        if not isinstance(condition, str) or not condition.endswith(DIAGNOSTIC21_C34_CONDITION_SUFFIX) or DIAGNOSTIC21_C30_CONDITION_SUFFIX not in condition or DIAGNOSTIC21_C31_CONDITION_SUFFIX not in condition or DIAGNOSTIC21_C32_CONDITION_SUFFIX not in condition or DIAGNOSTIC21_C33_CONDITION_SUFFIX not in condition:
            raise OrchestrationError("diagnostic21 %s C30/C31/C32/C33 source condition overlay mismatch: C34 required" % label)
        if any(configuration.get(key) != value for key, value in PUBLIC_ANSWER_FROZEN_CONFIGURATION.items()):
            raise OrchestrationError("diagnostic21 %s C31 public-answer contract mismatch" % label)
        if configuration.get("round_merge_mode") != DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE:
            raise OrchestrationError("diagnostic21 %s round_merge_mode mismatch" % label)
    _assert_diagnostic21_repo_relative_artifact_paths(primary, reference)


def _diagnostic21_is_repo_relative_path(value: Any) -> bool:
    path = Path(value) if isinstance(value, str) and value else None
    return path is not None and not path.is_absolute() and ".." not in path.parts


def _assert_diagnostic21_repo_relative_artifact_paths(primary: Mapping[str, Any], reference: Mapping[str, Any]) -> None:
    """Require repo-relative dataset, KURE, and BGE paths; Qwen's fixed local blob is separately recorded."""
    for label, manifest in (("primary", primary), ("reference", reference)):
        dataset = manifest.get("source_dataset")
        if not isinstance(dataset, Mapping) or not _diagnostic21_is_repo_relative_path(dataset.get("path")):
            raise OrchestrationError("diagnostic21 %s source dataset path is not repo-relative" % label)
        configuration = manifest.get("frozen_configuration")
        if not isinstance(configuration, Mapping):
            raise OrchestrationError("diagnostic21 %s frozen configuration is missing" % label)
        reranker = configuration.get("reranker_provenance")
        if not isinstance(reranker, Mapping) or not _diagnostic21_is_repo_relative_path(reranker.get("model_path")):
            raise OrchestrationError("diagnostic21 %s reranker path is not repo-relative" % label)
    primary_configuration = primary.get("frozen_configuration")
    if not isinstance(primary_configuration, Mapping):
        raise OrchestrationError("diagnostic21 primary frozen configuration is missing")
    kure = primary_configuration.get("retriever_provenance")
    if not isinstance(kure, Mapping):
        raise OrchestrationError("diagnostic21 KURE provenance is missing")
    for key in ("normalized_corpus_path", "vectors_path", "provision_ids_path", "model_path"):
        if not _diagnostic21_is_repo_relative_path(kure.get(key)):
            raise OrchestrationError("diagnostic21 KURE %s is not repo-relative" % key)


def write_v2_manifests(exec_root: Path, primary_source: Path, reference_source: Path) -> Dict[str, Path]:
    frozen_root = exec_root / "frozen_manifests"
    if frozen_root.exists() or frozen_root.is_symlink():
        raise OrchestrationError("refusing to overwrite existing frozen_manifests")
    primary = read_json(primary_source)
    reference = read_json(reference_source)
    primary_source_sha256 = sha256(primary_source)
    reference_source_sha256 = sha256(reference_source)
    manifests = build_v2_manifests(primary, reference)
    paths = {
        "full": frozen_root / "v2_kure_full226.json",
        "reference": frozen_root / "v2_bm25_reference_full226.json",
        "smoke": frozen_root / "v2_kure_smoke3.json",
        "smoke_reference": frozen_root / "v2_bm25_reference_smoke3.json",
    }
    diagnostic21_available = (
        primary_source_sha256 == DIAGNOSTIC21_SOURCE_PRIMARY_SHA256
        and reference_source_sha256 == DIAGNOSTIC21_SOURCE_REFERENCE_SHA256
    )
    if diagnostic21_available:
        manifests.update(build_diagnostic21_manifests(
            primary, reference, primary_source_sha256, reference_source_sha256
        ))
        paths.update({
            "diagnostic21": frozen_root / "v2_kure_diagnostic21.json",
            "diagnostic21_reference": frozen_root / "v2_bm25_reference_diagnostic21.json",
        })
        write_json_new(
            frozen_root / Path(DIAGNOSTIC21_C02_ANSWER_COHORT_FILE).name,
            DIAGNOSTIC21_C02_ANSWER_COHORT,
        )
    for key, path in paths.items():
        write_json_new(path, manifests[key])
    source_metadata = {
        **deepcopy(V2_SOURCE_METADATA_CARRY_FORWARD),
        "created_at_utc": utc_now(),
        "primary_source_manifest": str(primary_source.resolve()),
        "primary_source_manifest_sha256": primary_source_sha256,
        "reference_source_manifest": str(reference_source.resolve()),
        "reference_source_manifest_sha256": reference_source_sha256,
        "control_plane_release": DIAGNOSTIC21_C34_RELEASE,
        "public_answer_contract": dict(PUBLIC_ANSWER_FROZEN_CONFIGURATION),
        "generated": {key: {"path": str(path.relative_to(exec_root)), "sha256": sha256(path)} for key, path in paths.items()},
        "smoke_entries": [
            {"ordinal": int(entry["ordinal"]), "source_ordinal": int(entry.get("source_ordinal", entry["ordinal"])), "question_id": str(entry["question_id"]), "n_hops": int(entry["n_hops"])}
            for entry in manifests["smoke"]["entries"]
        ],
        "execution_policy": {
            "primary_retriever": "kure",
            "bm25_execution": "FORBIDDEN",
            "parser_execution": "FORBIDDEN",
            "lf_eval_score_injection": "FORBIDDEN",
            "network": "OFFLINE_ONLY",
            "repair_collision_failsafe": "REQUIRED",
            "repair_induced_list_dedupe": "REQUIRED",
            "s2_axis_canonical_projection": "REQUIRED",
        },
    }
    if diagnostic21_available:
        source_metadata["diagnostic21"] = {
            "name": DIAGNOSTIC21_PRIMARY_FROZEN_NAME,
            "primary_retriever": "kure",
            "bm25_execution": "FORBIDDEN",
            "reference_execution": "METADATA_ONLY_MUST_NEVER_BE_EXECUTED",
            "generated_primary_manifest_sha256": sha256(paths["diagnostic21"]),
            "generated_reference_manifest_sha256": sha256(paths["diagnostic21_reference"]),
            "primary_source_manifest_sha256": DIAGNOSTIC21_SOURCE_PRIMARY_SHA256,
            "reference_source_manifest_sha256": DIAGNOSTIC21_SOURCE_REFERENCE_SHA256,
            "roster_sha256": manifests["diagnostic21"]["selection"]["roster_sha256"],
            "baseline_sha256": canonical_sha256(DIAGNOSTIC21_BASELINE),
            "paired_c02_answer_cohort_sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            "paired_c02_answer_cohort_denominator": DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
            "paired_c02_answer_cohort_provenance": deepcopy(DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE),
            "condition_lineage": deepcopy(DIAGNOSTIC21_CONDITION_LINEAGE),
            "skill_files": deepcopy(DIAGNOSTIC21_SKILL_FILES),
            "reranker_provenance": deepcopy(DIAGNOSTIC21_RERANKER_PROVENANCE),
            "round_merge_provenance": deepcopy(manifests["diagnostic21"]["selection"]["round_merge_provenance"]),
            "c29_capabilities": deepcopy(DIAGNOSTIC21_C29_CAPABILITIES),
            "c30_capabilities": deepcopy(DIAGNOSTIC21_C30_CAPABILITIES),
            "c30_source_provenance": deepcopy(DIAGNOSTIC21_C30_SOURCE_PROVENANCE),
            "c31_capabilities": deepcopy(DIAGNOSTIC21_C31_CAPABILITIES),
            "c31_source_provenance": deepcopy(DIAGNOSTIC21_C31_SOURCE_PROVENANCE),
            "c32_capabilities": deepcopy(DIAGNOSTIC21_C32_CAPABILITIES),
            "c32_source_provenance": deepcopy(DIAGNOSTIC21_C32_SOURCE_PROVENANCE),
            "c33_capabilities": deepcopy(DIAGNOSTIC21_C33_CAPABILITIES),
            "c33_source_provenance": deepcopy(DIAGNOSTIC21_C33_SOURCE_PROVENANCE),
            "c34_capabilities": deepcopy(DIAGNOSTIC21_C34_CAPABILITIES),
            "c34_source_provenance": deepcopy(DIAGNOSTIC21_C34_SOURCE_PROVENANCE),
        }
    write_json_new(frozen_root / "source_metadata.json", source_metadata)
    assert_reference_is_read_only(manifests["full"], manifests["reference"], paths["full"], paths["reference"])
    assert_reference_is_read_only(manifests["smoke"], manifests["smoke_reference"], paths["smoke"], paths["smoke_reference"])
    if diagnostic21_available:
        assert_reference_is_read_only(manifests["diagnostic21"], manifests["diagnostic21_reference"], paths["diagnostic21"], paths["diagnostic21_reference"])
        assert_diagnostic21_manifest_integrity(manifests["diagnostic21"], manifests["diagnostic21_reference"])
    return paths


def offline_environment(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    result = dict(base or os.environ)
    result.update(OFFLINE_ENVIRONMENT)
    result["PYTHONPATH"] = str(PROJECT_ROOT) + (":" + result["PYTHONPATH"] if result.get("PYTHONPATH") else "")
    return result


def enforce_offline_environment() -> Dict[str, str]:
    """Force offline controls even when run is invoked without the launcher."""
    os.environ.update(OFFLINE_ENVIRONMENT)
    return {key: os.environ[key] for key in OFFLINE_ENVIRONMENT}


def query_gpu_state() -> Dict[str, Any]:
    """Read GPU occupancy only; never initializes CUDA or contacts a model."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise OrchestrationError("GPU idle gate cannot query nvidia-smi")
    samples = []
    for raw in result.stdout.splitlines():
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 2:
            raise OrchestrationError("GPU idle gate received malformed nvidia-smi output")
        try:
            samples.append({"utilization_percent": int(parts[0]), "used_memory_mib": int(parts[1])})
        except ValueError as exc:
            raise OrchestrationError("GPU idle gate received non-numeric nvidia-smi output") from exc
    if not samples:
        raise OrchestrationError("GPU idle gate found no GPUs")
    return {
        "gpus": samples,
        "max_utilization_percent": max(sample["utilization_percent"] for sample in samples),
        "max_used_memory_mib": max(sample["used_memory_mib"] for sample in samples),
    }


def wait_for_initial_gpu_idle(
    paths: Mapping[str, Path], *,
    utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX,
    used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX,
    poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS,
    stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
    required_stable_samples: int = DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES,
) -> Dict[str, Any]:
    """Fail closed until GPU utilization and memory are jointly idle twice."""
    if min(utilization_max, used_memory_mib_max, poll_seconds, stable_interval_seconds) < 0 or required_stable_samples < 2:
        raise OrchestrationError("invalid GPU idle gate configuration")
    stable_samples, checks = 0, 0
    while True:
        state = query_gpu_state()
        checks += 1
        idle = state["max_utilization_percent"] <= utilization_max and state["max_used_memory_mib"] <= used_memory_mib_max
        stable_samples = stable_samples + 1 if idle else 0
        event = append_progress(paths, {
            "event": "GPU_IDLE_CHECK", "check_number": checks, "idle": idle,
            "stable_samples": stable_samples, "required_stable_samples": required_stable_samples,
            "utilization_max_percent": utilization_max, "used_memory_max_mib": used_memory_mib_max, **state,
        })
        if stable_samples >= required_stable_samples:
            return event
        time.sleep(stable_interval_seconds if idle else poll_seconds)


def plan_paths(output_root: Path, mode: str) -> Dict[str, Path]:
    root = output_root / mode
    return {
        "root": root,
        "plan": root / "plan.json",
        "records": root / "records" / "runs",
        "batches": root / "batches",
        "checkpoints": root / "checkpoints",
        "evaluations": root / "evaluations",
        "progress_jsonl": root / "progress.jsonl",
        "progress_latest": root / "progress.latest.json",
        "gate": root / "gate.json",
    }


def manifest_paths(exec_root: Path, mode: str) -> Tuple[Path, Path]:
    frozen = exec_root / "frozen_manifests"
    if mode == "smoke":
        return frozen / "v2_kure_smoke3.json", frozen / "v2_bm25_reference_smoke3.json"
    if mode == "full226":
        return frozen / "v2_kure_full226.json", frozen / "v2_bm25_reference_full226.json"
    if mode == DIAGNOSTIC21_MODE:
        return frozen / "v2_kure_diagnostic21.json", frozen / "v2_bm25_reference_diagnostic21.json"
    raise OrchestrationError("unknown mode: %s" % mode)


def source_snapshot_dict(exec_root: Path) -> Dict[str, str]:
    from runtime.source_snapshot import capture_clean_source_snapshot
    return capture_clean_source_snapshot(exec_root).to_dict()


def make_plan(exec_root: Path, output_root: Path, mode: str) -> Dict[str, Any]:
    primary_path, reference_path = manifest_paths(exec_root, mode)
    primary, reference = read_json(primary_path), read_json(reference_path)
    comparison = assert_reference_is_read_only(primary, reference, primary_path, reference_path)
    entries = list(primary["entries"])
    if mode == "full226":
        if len(entries) != TOTAL_FULL226:
            raise OrchestrationError("full226 plan has wrong number of entries")
        chunks = chunks_for_entries()
        assert_full226_chunks(chunks)
    elif mode == DIAGNOSTIC21_MODE:
        assert_diagnostic21_manifest_integrity(primary, reference)
        if len(entries) != DIAGNOSTIC21_ENTRY_COUNT:
            raise OrchestrationError("diagnostic21 plan must contain exactly 21 entries")
        chunks = DIAGNOSTIC21_CHUNKS
    else:
        if len(entries) != 3 or {int(entry["n_hops"]) for entry in entries} != {1, 2, 3}:
            raise OrchestrationError("smoke plan must be exactly one frozen 1/2/3-hop trio")
        chunks = ((1, 3),)
    plan = {
        "orchestration_schema_version": "v2.0",
        "created_at_utc": utc_now(),
        "mode": mode,
        "exec_root": str(exec_root),
        "output_root": str(output_root),
        "source_snapshot": source_snapshot_dict(exec_root),
        "primary_manifest": str(primary_path),
        "primary_manifest_sha256": sha256(primary_path),
        "reference_manifest": str(reference_path),
        "reference_manifest_sha256": sha256(reference_path),
        "entry_count": len(entries),
        "chunks": [{"start_ordinal": start, "end_ordinal": end} for start, end in chunks],
        "frozen_configuration": primary["frozen_configuration"],
        "comparison_validation": comparison,
        "runtime": {**EXPECTED_RUNTIME, "warm_persistent": True, "offline_environment": OFFLINE_ENVIRONMENT},
        "execution_policy": {
            "primary_retriever": "kure",
            "bm25_execution": "FORBIDDEN",
            "bm25_reference_use": "READ_ONLY_CONFIGURATION_GUARD",
            "parser_execution": "FORBIDDEN",
            "lf_eval_score_injection": "FORBIDDEN",
            "source_snapshot_assertion": "BEFORE_AND_AFTER_EVERY_CHUNK_AND_QUESTION",
        },
        "smoke_score_not_benchmark_evidence": mode == "smoke",
    }
    if mode == DIAGNOSTIC21_MODE:
        plan["diagnostic21"] = {
            "enabled": True,
            "numeric_baseline_gates": dict(DIAGNOSTIC21_NONREGRESSION_MINIMUMS),
            "paired_c02_answer_cohort_sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            "paired_c02_answer_cohort_denominator": DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
            "evaluation_only": True,
        }
    return plan


def _jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OrchestrationError("invalid progress JSONL line %d" % number) from exc
            if not isinstance(row, dict):
                raise OrchestrationError("progress JSONL row must be an object")
            rows.append(dict(row))
    return rows


def completed_checkpoints(paths: Mapping[str, Path], plan: Mapping[str, Any]) -> Tuple[int, ...]:
    complete: List[int] = []
    for item in plan["chunks"]:
        end = int(item["end_ordinal"])
        checkpoint = paths["checkpoints"] / ("checkpoint-%03d.json" % end)
        if checkpoint.is_file():
            payload = read_json(checkpoint)
            if payload.get("checkpoint_status") != "PASS" or payload.get("completed_questions") != end:
                raise OrchestrationError("checkpoint is not a completed PASS boundary: %s" % checkpoint)
            complete.append(end)
    return tuple(complete)


def _attempt_prefix(start: int, end: int) -> str:
    return "chunk-%03d-%03d-attempt-" % (start, end)


def _completed_attempt(path: Path, start: int, end: int) -> bool:
    metadata_path, summary_path = path / "metadata.json", path / "summary.jsonl"
    if not metadata_path.is_file() or not summary_path.is_file():
        return False
    metadata = read_json(metadata_path)
    if not metadata.get("completed_at_utc") or metadata.get("start_ordinal") != start or metadata.get("end_ordinal") != end:
        return False
    rows = _jsonl_rows(summary_path)
    return [row.get("ordinal") for row in rows] == list(range(start, end + 1))


def completed_attempt_for(paths: Mapping[str, Path], start: int, end: int) -> Optional[Path]:
    candidates = [
        child for child in paths["batches"].iterdir()
        if child.is_dir() and child.name.startswith(_attempt_prefix(start, end)) and _completed_attempt(child, start, end)
    ] if paths["batches"].is_dir() else []
    if len(candidates) > 1:
        raise OrchestrationError("ambiguous completed chunk attempts for %03d-%03d" % (start, end))
    return candidates[0] if candidates else None


def assert_resume_state(paths: Mapping[str, Path], plan: Mapping[str, Any], resume: bool) -> int:
    exists = paths["root"].exists() or paths["root"].is_symlink()
    if not exists:
        if resume:
            raise OrchestrationError("cannot resume: output root does not exist")
        return 0
    if not paths["root"].is_dir() or not paths["plan"].is_file():
        raise OrchestrationError("output root is not a valid immutable V2 plan")
    existing = read_json(paths["plan"])
    stable_keys = ("mode", "exec_root", "source_snapshot", "primary_manifest_sha256", "reference_manifest_sha256", "chunks", "frozen_configuration")
    if any(existing.get(key) != plan.get(key) for key in stable_keys):
        raise OrchestrationError("existing output plan does not match this immutable source")
    if not resume:
        raise OrchestrationError("refusing to overwrite existing V2 output; use validated --resume")
    completed = completed_checkpoints(paths, plan)
    expected = [int(item["end_ordinal"]) for item in plan["chunks"]]
    if completed != tuple(expected[:len(completed)]):
        raise OrchestrationError("resume is permitted only after contiguous completed chunk boundaries")
    if plan.get("mode") == DIAGNOSTIC21_MODE:
        if completed == ():
            raise OrchestrationError("diagnostic21 resume requires a PASS checkpoint-020")
        if completed not in ((20,), (20, 21)):
            raise OrchestrationError("diagnostic21 resume permits only PASS checkpoint-020 or final-gate recovery")
        for item in plan["chunks"][:len(completed)]:
            start, end = int(item["start_ordinal"]), int(item["end_ordinal"])
            if completed_attempt_for(paths, start, end) is None:
                raise OrchestrationError("diagnostic21 PASS checkpoint lacks its completed attempt: %03d-%03d" % (start, end))
    # Incomplete attempts are immutable evidence of an interruption. They are
    # intentionally retained and a new attempt is created after the last PASS.
    for item in plan["chunks"]:
        completed_attempt_for(paths, int(item["start_ordinal"]), int(item["end_ordinal"]))
    return completed[-1] if completed else 0


def initialize_output(paths: Mapping[str, Path], plan: Mapping[str, Any], resume: bool) -> int:
    completed = assert_resume_state(paths, plan, resume)
    if completed:
        return completed
    if paths["root"].exists() or paths["root"].is_symlink():
        return 0
    paths["root"].mkdir(parents=True, exist_ok=False)
    write_json_new(paths["plan"], plan)
    for key in ("records", "batches", "checkpoints", "evaluations"):
        paths[key].mkdir(parents=True, exist_ok=False)
    return 0


def append_progress(paths: Mapping[str, Path], event: Mapping[str, Any]) -> Dict[str, Any]:
    payload = {"recorded_at_utc": utc_now(), **dict(event)}
    paths["progress_jsonl"].parent.mkdir(parents=True, exist_ok=True)
    with paths["progress_jsonl"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    paths["progress_latest"].write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PROGRESS_EVENT " + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    return payload


def _build_v2_run_args(question: str, question_id: str, configuration: Mapping[str, Any], record_root: Path, snapshot: Mapping[str, str]) -> Any:
    from scripts import run_local_harness
    return run_local_harness.build_frozen_run_args(question, question_id, configuration, record_root, str(snapshot["git_commit"]), str(snapshot["source_manifest_sha256"]))


def _load_questions(dataset_path: Path) -> Dict[str, Mapping[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise OrchestrationError("runtime Python must provide pyarrow for KoBLEX") from exc
    rows = pq.read_table(dataset_path, columns=["id", "background", "question", "n_hops"]).to_pylist()
    return {str(row["id"]): row for row in rows}


def _format_benchmark_input(question: Mapping[str, Any]) -> str:
    background = str(question.get("background") or "").strip()
    prompt = str(question.get("question") or "").strip()
    if not prompt:
        raise OrchestrationError("benchmark question text is empty")
    return "[질문]\n%s" % prompt if not background else "[배경 시나리오]\n%s\n\n[질문]\n%s" % (background, prompt)


def _record_directories(root: Path) -> set[Path]:
    return {path for path in root.iterdir() if path.is_dir()} if root.is_dir() else set()


def _read_result(created: Iterable[Path]) -> Dict[str, Any]:
    directories = sorted(created)
    if len(directories) != 1:
        return {"record_directory_count": len(directories), "status": "EXECUTION_FAILURE", "errors": ["NO_UNIQUE_RECORD"]}
    result_file = directories[0] / "result.json"
    if not result_file.is_file():
        return {"record_directory": str(directories[0]), "status": "EXECUTION_FAILURE", "errors": ["NO_FINAL_RESULT"]}
    payload = read_json(result_file)
    return {
        "record_directory": str(directories[0]),
        "status": payload.get("status"),
        "termination_reason": payload.get("termination_reason"),
        "abstention_reason": payload.get("abstention_reason"),
        "errors": payload.get("errors", []),
        "end_to_end_latency_ms": payload.get("end_to_end_latency_ms"),
        "run_id": payload.get("run_id"),
    }


def entries_for_chunk(primary: Mapping[str, Any], start: int, end: int) -> List[Dict[str, Any]]:
    entries = [dict(entry) for entry in primary.get("entries", []) if start <= int(entry.get("ordinal", 0)) <= end]
    if [int(entry["ordinal"]) for entry in entries] != list(range(start, end + 1)):
        raise OrchestrationError("frozen execution entries are not contiguous for chunk %03d-%03d" % (start, end))
    return entries


def execute_chunk(exec_root: Path, paths: Mapping[str, Path], plan: Mapping[str, Any], start: int, end: int, resources: Any, questions: Mapping[str, Mapping[str, Any]]) -> Tuple[Path, bool]:
    """Run one immutable KURE attempt; abandoned attempts are never overwritten."""
    from runtime.source_snapshot import assert_source_snapshot_unchanged, capture_clean_source_snapshot
    from scripts import run_local_harness

    primary = read_json(Path(str(plan["primary_manifest"])))
    configuration = dict(primary["frozen_configuration"])
    assert_kure_only(configuration)
    snapshot = capture_clean_source_snapshot(exec_root)
    if snapshot.to_dict() != dict(plan["source_snapshot"]):
        raise OrchestrationError("source snapshot changed before chunk %03d-%03d" % (start, end))
    entries = entries_for_chunk(primary, start, end)
    attempt_id = uuid.uuid4().hex
    chunk_dir = paths["batches"] / (_attempt_prefix(start, end) + attempt_id)
    chunk_dir.mkdir(parents=True, exist_ok=False)
    chunk_manifest = deepcopy(primary)
    chunk_manifest["name"] = "%s-chunk-%03d-%03d-attempt-%s" % (primary.get("name", PRIMARY_FROZEN_NAME), start, end, attempt_id)
    chunk_manifest["entries"] = entries
    selection = dict(chunk_manifest.get("selection") or {})
    selection.update({"method": "immutable V2 execution chunk %03d-%03d" % (start, end), "entry_count": len(entries), "ordinal_start": start, "ordinal_end": end})
    chunk_manifest["selection"] = selection
    write_json_new(chunk_dir / "manifest.json", chunk_manifest)
    metadata: Dict[str, Any] = {
        "batch_id": chunk_dir.name,
        "attempt_id": attempt_id,
        "started_at_utc": utc_now(),
        "entry_count": len(entries),
        "start_ordinal": start,
        "end_ordinal": end,
        "configuration": configuration,
        "source_snapshot": snapshot.to_dict(),
        "batch_manifest_sha256": sha256(chunk_dir / "manifest.json"),
        "record_root": str(paths["records"]),
        "execution_mode": "warm_persistent_kure_only",
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
    }
    write_json_new(chunk_dir / "metadata.json", metadata)
    rows: List[Dict[str, Any]] = []
    has_failure = False
    for entry in entries:
        assert_source_snapshot_unchanged(exec_root, snapshot)
        ordinal, question_id = int(entry["ordinal"]), str(entry["question_id"])
        question = questions.get(question_id)
        if question is None or int(question.get("n_hops", 0)) != int(entry["n_hops"]):
            raise OrchestrationError("frozen question is absent or hop-mismatched: %s" % question_id)
        before = _record_directories(paths["records"])
        log_path = chunk_dir / ("%03d_%s.log" % (ordinal, question_id))
        started = utc_now()
        exit_code = 1
        with log_path.open("x", encoding="utf-8") as log:
            try:
                run_args = _build_v2_run_args(_format_benchmark_input(question), question_id, configuration, paths["records"], snapshot.to_dict())
                execution = run_local_harness.run_question(run_args, source_snapshot=snapshot, resources=resources)
                print(execution.rendered_output, file=log)
                exit_code = execution.exit_code
            except Exception:
                traceback.print_exc(file=log)
        assert_source_snapshot_unchanged(exec_root, snapshot)
        outcome = _read_result(_record_directories(paths["records"]) - before)
        status = outcome.get("status")
        if status not in NORMAL_STATUSES:
            has_failure = True
        rows.append({
            "ordinal": ordinal,
            "source_ordinal": int(entry.get("source_ordinal", ordinal)),
            "question_id": question_id,
            "n_hops": int(entry["n_hops"]),
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "exit_code": exit_code,
            "log_file": str(log_path),
            **outcome,
        })
    write_jsonl_new(chunk_dir / "summary.jsonl", rows)
    assert_source_snapshot_unchanged(exec_root, snapshot)
    metadata["completed_at_utc"] = utc_now()
    metadata["has_execution_failure"] = has_failure
    (chunk_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return chunk_dir, has_failure


def _metric_projection(aggregate: Mapping[str, Any]) -> Dict[str, Any]:
    provision = dict(aggregate.get("provision") or {})
    macro, micro = dict(provision.get("macro") or {}), dict(provision.get("micro") or {})
    complete, exact = dict(provision.get("complete_evidence") or {}), dict(provision.get("exact_match") or {})
    quality, outcomes = dict(aggregate.get("answer_quality") or {}), dict(aggregate.get("outcomes") or {})
    latency = dict(dict(aggregate.get("efficiency") or {}).get("end_to_end_latency_ms") or {})
    return {
        "provision_macro_precision": macro.get("precision"),
        "provision_macro_recall": macro.get("recall"),
        "provision_macro_f1": macro.get("f1"),
        "provision_micro_f1": micro.get("f1"),
        "complete_evidence_count": complete.get("count"),
        "complete_evidence_rate": complete.get("rate"),
        "provision_exact_match_count": exact.get("count"),
        "provision_exact_match_rate": exact.get("rate"),
        "token_f1_end_to_end": quality.get("token_f1_at_800", {}).get("end_to_end") if isinstance(quality.get("token_f1_at_800"), Mapping) else None,
        "token_f1_answered_only": quality.get("token_f1_at_800", {}).get("answered_only") if isinstance(quality.get("token_f1_at_800"), Mapping) else None,
        "token_f1_candidate": quality.get("candidate_token_f1_at_800", {}).get("all_outcomes") if isinstance(quality.get("candidate_token_f1_at_800"), Mapping) else None,
        "answer_count": quality.get("answer_count"),
        "abstain_count": quality.get("abstain_count"),
        "execution_failure_count": quality.get("execution_failure_count"),
        "outcome_counts": {name: value.get("count") for name, value in outcomes.items() if isinstance(value, Mapping)},
        "citation_integrity": aggregate.get("citation_integrity"),
        "mean_latency_ms": latency.get("mean"),
        "median_latency_ms": latency.get("median"),
        "p95_latency_ms": latency.get("p95"),
    }


def evaluate_checkpoint(exec_root: Path, paths: Mapping[str, Path], plan: Mapping[str, Any], chunk_dirs: Sequence[Path], completed: int, runtime_python: Path) -> Dict[str, Any]:
    """Evaluate completed immutable attempts; failed evaluator attempts remain auditable."""
    from scripts.materialize_checkpoint_batch import materialize_cumulative_batch

    final_checkpoint = paths["checkpoints"] / ("checkpoint-%03d.json" % completed)
    if final_checkpoint.exists():
        payload = read_json(final_checkpoint)
        if payload.get("checkpoint_status") != "PASS":
            raise OrchestrationError("final checkpoint is not PASS: %s" % final_checkpoint)
        return payload
    attempt_id = uuid.uuid4().hex
    checkpoint_batch = paths["checkpoints"] / ("batch-%03d-attempt-%s" % (completed, attempt_id))
    evaluation_dir = paths["evaluations"] / ("checkpoint-%03d-attempt-%s" % (completed, attempt_id))
    primary_manifest_path = plan.get("primary_manifest")
    primary_manifest_name = PRIMARY_FROZEN_NAME
    if isinstance(primary_manifest_path, str) and primary_manifest_path:
        manifest_payload = read_json(Path(primary_manifest_path))
        manifest_name = manifest_payload.get("name")
        if isinstance(manifest_name, str) and manifest_name:
            primary_manifest_name = manifest_name
    materialize_cumulative_batch(
        chunk_dirs,
        checkpoint_batch,
        name="%s-checkpoint-%03d" % (primary_manifest_name, completed),
        through_ordinal=completed,
    )
    command = [str(runtime_python), str(exec_root / "scripts/evaluate_dev_runs.py"), "--batch-dir", str(checkpoint_batch), "--output-dir", str(evaluation_dir), "--require-stage-provenance"]
    assert_no_external_score_injection(command)
    started = time.monotonic()
    result = subprocess.run(command, cwd=exec_root, env=offline_environment(), check=False, text=True, capture_output=True)
    (paths["checkpoints"] / ("evaluator-%03d-attempt-%s.stdout.log" % (completed, attempt_id))).write_text(result.stdout, encoding="utf-8")
    (paths["checkpoints"] / ("evaluator-%03d-attempt-%s.stderr.log" % (completed, attempt_id))).write_text(result.stderr, encoding="utf-8")
    aggregate_path = evaluation_dir / "aggregate.json"
    aggregate = read_json(aggregate_path) if aggregate_path.is_file() else {}
    rows = _jsonl_rows(checkpoint_batch / "summary.jsonl")
    diagnostic21 = plan["mode"] == DIAGNOSTIC21_MODE
    public_abstain_leak_question_ids: List[str] = []
    public_abstain_missing_result_question_ids: List[str] = []
    public_abstain_invalid_result_question_ids: List[str] = []
    if diagnostic21:
        for row in rows:
            if row.get("status") != "ABSTAIN":
                continue
            question_id = str(row.get("question_id") or "")
            record_directory = row.get("record_directory")
            if not isinstance(record_directory, str) or not record_directory:
                public_abstain_missing_result_question_ids.append(question_id)
                continue
            result_path = Path(record_directory) / "result.json"
            if not result_path.is_file():
                public_abstain_missing_result_question_ids.append(question_id)
                continue
            try:
                result_payload = read_json(result_path)
            except (OSError, ValueError, OrchestrationError):
                public_abstain_invalid_result_question_ids.append(question_id)
                continue
            if not isinstance(result_payload, Mapping):
                public_abstain_invalid_result_question_ids.append(question_id)
                continue
            if result_payload.get("answer") is not None or result_payload.get("final_answer") is not None:
                public_abstain_leak_question_ids.append(question_id)
    abnormal = [str(row.get("question_id")) for row in rows if row.get("status") not in NORMAL_STATUSES]
    unexpected_exit = [
        str(row.get("question_id")) for row in rows
        if (row.get("status") == "ANSWER" and row.get("exit_code") not in (0, None))
        or (row.get("status") == "ABSTAIN" and row.get("exit_code") not in (0, 1, None))
    ]
    recorded_errors = {str(row.get("question_id")): row.get("errors") for row in rows if row.get("errors")}
    citation = dict(aggregate.get("citation_integrity") or {})
    provenance_missing = [
        name for name in ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30")
        if (aggregate.get("retrieval", {}).get(name, {}) if isinstance(aggregate.get("retrieval"), Mapping) else {}).get("available") is not True
    ]
    errors = []
    if result.returncode:
        errors.append("evaluator_exit=%d" % result.returncode)
    if abnormal:
        errors.append("abnormal_outcomes=%d" % len(abnormal))
    if unexpected_exit:
        errors.append("unexpected_exit=%d" % len(unexpected_exit))
    if recorded_errors:
        errors.append("recorded_errors=%d" % len(recorded_errors))
    if citation.get("attempted", 0) and citation.get("pass_rate") != 1.0:
        errors.append("citation_integrity=%s" % citation.get("pass_rate"))
    if provenance_missing:
        errors.append("stage_provenance_missing=" + ",".join(provenance_missing))
    if public_abstain_missing_result_question_ids:
        errors.append("public_abstain_result_missing=" + ",".join(public_abstain_missing_result_question_ids))
    if public_abstain_invalid_result_question_ids:
        errors.append("public_abstain_result_invalid=" + ",".join(public_abstain_invalid_result_question_ids))
    if public_abstain_leak_question_ids:
        errors.append("public_abstain_leak=" + ",".join(public_abstain_leak_question_ids))
    projection = _metric_projection(aggregate)
    if diagnostic21:
        try:
            projection["paired_c02_answer_cohort"] = paired_c02_answer_cohort_score(
                evaluation_dir / "per_question.csv", exec_root
            )
        except OrchestrationError as exc:
            projection["paired_c02_answer_cohort"] = None
            errors.append("paired_c02_answer_cohort=%s" % exc)
        projection = {
            key: value for key, value in projection.items()
            if key not in {"mean_latency_ms", "median_latency_ms", "p95_latency_ms"}
        }
    event = {
        "event": (
            "FULL226_COMPLETED" if plan["mode"] == "full226" and completed == TOTAL_FULL226
            else "DIAGNOSTIC21_CHECKPOINT20_COMPLETED" if diagnostic21 and completed == 20
            else "DIAGNOSTIC21_COMPLETED" if diagnostic21 and completed == DIAGNOSTIC21_ENTRY_COUNT
            else "CHECKPOINT_COMPLETED"
        ),
        "checkpoint_status": "PASS" if not errors else "ERRORS_FOUND",
        "completed_questions": completed,
        "total_questions": int(plan["entry_count"]),
        "checkpoint_range": [int(chunk_dirs[-1].name.split("-")[1]), int(chunk_dirs[-1].name.split("-")[2])],
        "validation_errors": errors,
        "abnormal_question_ids": abnormal,
        "unexpected_exit_question_ids": unexpected_exit,
        "recorded_errors": recorded_errors,
        "stage_provenance_missing": provenance_missing,
        "metrics": projection,
        "evaluator_command": command,
        "batch_directory": str(checkpoint_batch),
        "evaluation_directory": str(evaluation_dir),
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
    }
    if diagnostic21:
        event.update({
            "diagnostic21_checkpoint_role": (
                "FIRST_CHUNK_COVERAGE_CHECKPOINT_NOT_A_FINAL_GATE" if completed == 20
                else "FINAL_GATE_CANDIDATE" if completed == DIAGNOSTIC21_ENTRY_COUNT
                else None
            ),
            "public_abstain_leak_question_ids": public_abstain_leak_question_ids,
            "public_abstain_missing_result_question_ids": public_abstain_missing_result_question_ids,
            "public_abstain_invalid_result_question_ids": public_abstain_invalid_result_question_ids,
        })
    else:
        mean_latency_ms = projection.get("mean_latency_ms")
        remaining_ms = (
            (TOTAL_FULL226 - completed) * float(mean_latency_ms)
            if isinstance(mean_latency_ms, (int, float)) and plan["mode"] == "full226"
            else None
        )
        event.update({
            "evaluator_elapsed_seconds": time.monotonic() - started,
            "remaining_eta_ms": remaining_ms,
            "remaining_eta_seconds": remaining_ms / 1000.0 if remaining_ms is not None else None,
            "remaining_eta_utc": (
                datetime.now(timezone.utc) + timedelta(seconds=remaining_ms / 1000.0)
            ).isoformat() if remaining_ms is not None else None,
        })
    if errors:
        write_json_new(paths["checkpoints"] / ("checkpoint-%03d-attempt-%s.json" % (completed, attempt_id)), event)
    else:
        write_json_new(final_checkpoint, event)
    return event



def diagnostic21_gate(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail closed on the fixed 21-row diagnostic’s integrity and score gates."""
    metrics_value = event.get("metrics")
    metrics = dict(metrics_value) if isinstance(metrics_value, Mapping) else {}
    reasons: List[str] = []
    validation_errors = event.get("validation_errors")
    if not isinstance(validation_errors, list):
        reasons.append("validation_errors_missing_or_nonlist")
    elif validation_errors:
        reasons.extend("validation_error:%s" % value for value in validation_errors)
    if type(event.get("completed_questions")) is not int or event.get("completed_questions") != DIAGNOSTIC21_ENTRY_COUNT:
        reasons.append("completed_questions_not_21")
    if event.get("checkpoint_status") != "PASS":
        reasons.append("checkpoint_status_not_pass")
    if event.get("bm25_execution") != "FORBIDDEN":
        reasons.append("bm25_execution_not_forbidden")
    if event.get("lf_eval_score_injection") != "FORBIDDEN":
        reasons.append("lf_eval_score_injection_not_forbidden")
    normal_counts: Dict[str, int] = {}
    for metric_name in ("execution_failure_count", "answer_count", "abstain_count"):
        observed = metrics.get(metric_name)
        if type(observed) is not int:
            reasons.append("normal_outcome_metric_missing_or_noninteger:%s" % metric_name)
        else:
            normal_counts[metric_name] = observed
    if len(normal_counts) == 3:
        if normal_counts["execution_failure_count"] != 0:
            reasons.append("execution_failure_count")
        if normal_counts["answer_count"] + normal_counts["abstain_count"] != DIAGNOSTIC21_ENTRY_COUNT:
            reasons.append("normal_outcome_count")
        if normal_counts["answer_count"] < DIAGNOSTIC21_ANSWER_YIELD_MINIMUM:
            reasons.append("answer_yield_below_c02_cohort_denominator")
    for field_name, reason in (
        ("stage_provenance_missing", "stage_provenance"),
        ("public_abstain_missing_result_question_ids", "public_abstain_result_missing"),
        ("public_abstain_invalid_result_question_ids", "public_abstain_result_invalid"),
        ("public_abstain_leak_question_ids", "public_abstain_leak"),
    ):
        values = event.get(field_name)
        if not isinstance(values, list):
            reasons.append("%s_missing_or_nonlist" % reason)
        elif values:
            reasons.append(reason)
    citation = metrics.get("citation_integrity")
    if not isinstance(citation, Mapping):
        reasons.append("citation_integrity")
    else:
        attempted, passed, pass_rate = citation.get("attempted"), citation.get("passed"), citation.get("pass_rate")
        if type(attempted) is not int or type(passed) is not int or attempted < 0 or passed < 0:
            reasons.append("citation_integrity")
        elif attempted == 0 or (
            type(pass_rate) not in (int, float)
            or not math.isfinite(float(pass_rate))
            or passed != attempted
            or float(pass_rate) != 1.0
        ):
            reasons.append("citation_integrity")
    paired = metrics.get("paired_c02_answer_cohort")
    if not isinstance(paired, Mapping):
        reasons.append("paired_c02_answer_cohort_missing")
    elif (
        paired.get("denominator") != DIAGNOSTIC21_ANSWER_YIELD_MINIMUM
        or paired.get("frozen_cohort_file") != DIAGNOSTIC21_C02_ANSWER_COHORT_FILE
        or paired.get("frozen_cohort_sha256") != DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256
        or paired.get("provenance") != DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE
    ):
        reasons.append("paired_c02_answer_cohort_provenance_or_denominator")
    else:
        paired_rows = paired.get("rows")
        if not isinstance(paired_rows, list) or tuple(
            str(row.get("question_id") or "") for row in paired_rows if isinstance(row, Mapping)
        ) != DIAGNOSTIC21_C02_ANSWER_COHORT_QUESTION_IDS or any(
            row.get("status") != "ANSWER" for row in paired_rows if isinstance(row, Mapping)
        ):
            reasons.append("paired_c02_answer_cohort_rows")
        paired_score = paired.get("token_f1_at_800")
        if (
            type(paired_score) not in (int, float)
            or not math.isfinite(float(paired_score))
            or float(paired_score) < DIAGNOSTIC21_BASELINE["token_f1_answered_only"]
        ):
            reasons.append("paired_c02_answer_cohort_token_f1_at_800")
    for metric_name, minimum in DIAGNOSTIC21_NONREGRESSION_MINIMUMS.items():
        observed = metrics.get(metric_name)
        if (
            type(observed) not in (int, float)
            or not math.isfinite(float(observed))
            or float(observed) + DIAGNOSTIC21_FLOAT_TOLERANCE < float(minimum)
        ):
            reasons.append("numeric_regression:%s" % metric_name)
    return {
        "stage": "diagnostic21",
        "status": "PASS" if not reasons else "FAIL",
        "required_checks": [
            "zero_execution_failures",
            "normal_outcomes_without_abstain_answer_leakage",
            "abstain_result_json_present_and_public_answer_free",
            "citation_integrity_100_percent",
            "c02_answer_yield_nonregression",
            "paired_c02_answer_cohort_token_f1_at_800",
            "stage_provenance",
            "fixed_numeric_baseline_nonregression",
            "bm25_execution_forbidden",
            "lf_eval_score_injection_forbidden",
            "evaluator_success",
        ],
        "baseline": deepcopy(DIAGNOSTIC21_BASELINE),
        "nonregression_minimums": dict(DIAGNOSTIC21_NONREGRESSION_MINIMUMS),
        "paired_c02_answer_cohort": deepcopy(DIAGNOSTIC21_C02_ANSWER_COHORT),
        "paired_c02_answer_cohort_sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
        "answer_yield_minimum": DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
        "reasons": sorted(set(reasons)),
        "source_checkpoint": dict(event),
    }


def _finished_diagnostic21_gate(paths: Mapping[str, Path], completed: int) -> Optional[int]:
    if completed != DIAGNOSTIC21_ENTRY_COUNT:
        return None
    if paths["gate"].is_file():
        return 0 if read_json(paths["gate"]).get("status") == "PASS" else 1
    checkpoint = read_json(paths["checkpoints"] / "checkpoint-021.json")
    gate = diagnostic21_gate(checkpoint)
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "DIAGNOSTIC21_GATE_RECOVERED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def smoke_gate(event: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = dict(event.get("metrics") or {})
    reasons = list(event.get("validation_errors") or [])
    if metrics.get("answer_count") is None or int(metrics.get("answer_count") or 0) < 1:
        reasons.append("answer_count_below_one")
    if metrics.get("execution_failure_count") != 0:
        reasons.append("execution_failure_count")
    citation = metrics.get("citation_integrity")
    if not isinstance(citation, Mapping) or int(citation.get("attempted") or 0) < 1 or citation.get("pass_rate") != 1.0:
        reasons.append("citation_integrity")
    if event.get("stage_provenance_missing"):
        reasons.append("stage_provenance")
    return {
        "stage": "operational_smoke3",
        "status": "PASS" if not reasons else "FAIL",
        "score_is_benchmark_evidence": False,
        "required_checks": ["schema_execution", "at_least_one_answer_s3_path", "citation_integrity", "stage_provenance", "zero_execution_failures", "evaluator_success"],
        "reasons": sorted(set(reasons)),
        "source_checkpoint": dict(event),
    }


def _finished_smoke_gate(paths: Mapping[str, Path], completed: int) -> Optional[int]:
    if completed != 3:
        return None
    if paths["gate"].is_file():
        return 0 if read_json(paths["gate"]).get("status") == "PASS" else 1
    checkpoint = read_json(paths["checkpoints"] / "checkpoint-003.json")
    gate = smoke_gate(checkpoint)
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "SMOKE_GATE_RECOVERED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def full226_gate(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Require the approved C02 public-answer/candidate proof thresholds on all 226 rows."""
    metrics_value = event.get("metrics")
    metrics = dict(metrics_value) if isinstance(metrics_value, Mapping) else {}
    reasons: List[str] = []
    validation_errors = event.get("validation_errors")
    if not isinstance(validation_errors, list):
        reasons.append("validation_errors_missing_or_nonlist")
    elif validation_errors:
        reasons.extend("validation_error:%s" % value for value in validation_errors)
    if event.get("checkpoint_status") != "PASS":
        reasons.append("checkpoint_status_not_pass")
    if type(event.get("completed_questions")) is not int or event.get("completed_questions") != TOTAL_FULL226:
        reasons.append("completed_questions_not_226")
    if event.get("bm25_execution") != "FORBIDDEN":
        reasons.append("bm25_execution_not_forbidden")
    if event.get("lf_eval_score_injection") != "FORBIDDEN":
        reasons.append("lf_eval_score_injection_not_forbidden")
    provenance_missing = event.get("stage_provenance_missing")
    if not isinstance(provenance_missing, list):
        reasons.append("stage_provenance_missing_or_nonlist")
    elif provenance_missing:
        reasons.append("stage_provenance")
    citation = metrics.get("citation_integrity")
    if not isinstance(citation, Mapping):
        reasons.append("citation_integrity")
    else:
        attempted, passed, pass_rate = citation.get("attempted"), citation.get("passed"), citation.get("pass_rate")
        if (
            type(attempted) is not int
            or type(passed) is not int
            or attempted <= 0
            or passed != attempted
            or type(pass_rate) not in (int, float)
            or not math.isfinite(float(pass_rate))
            or float(pass_rate) != 1.0
        ):
            reasons.append("citation_integrity")
    for metric_name, minimum in FULL226_C02_NONREGRESSION_MINIMUMS.items():
        observed = metrics.get(metric_name)
        if (
            type(observed) not in (int, float)
            or not math.isfinite(float(observed))
            or float(observed) < float(minimum)
        ):
            reasons.append("numeric_regression:%s" % metric_name)
    return {
        "stage": "full226",
        "status": "PASS" if not reasons else "FAIL",
        "required_checks": [
            "public_answered_only_token_f1_at_800_c02_nonregression",
            "candidate_integrated_token_f1_at_800_c02_nonregression",
            "citation_integrity_100_percent",
            "stage_provenance",
            "bm25_execution_forbidden",
            "lf_eval_score_injection_forbidden",
            "evaluator_success",
        ],
        "nonregression_minimums": dict(FULL226_C02_NONREGRESSION_MINIMUMS),
        "baseline_provenance": deepcopy(FULL226_C02_BASELINE_PROVENANCE),
        "reasons": sorted(set(reasons)),
        "final_checkpoint": dict(event),
    }


def _finished_full_gate(paths: Mapping[str, Path], completed: int) -> Optional[int]:
    if completed != TOTAL_FULL226:
        return None
    if paths["gate"].is_file():
        return 0 if read_json(paths["gate"]).get("status") == "PASS" else 1
    checkpoint = read_json(paths["checkpoints"] / "checkpoint-%03d.json" % TOTAL_FULL226)
    gate = full226_gate(checkpoint)
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "FULL_GATE_RECOVERED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def execute_plan(
    exec_root: Path, output_root: Path, mode: str, runtime_python: Path, resume: bool, *,
    skip_gpu_idle_gate: bool = False, gpu_utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX,
    gpu_used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX, gpu_poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS,
    gpu_stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
    warm_state: Optional[Dict[str, Any]] = None,
) -> int:
    if mode == DIAGNOSTIC21_MODE and skip_gpu_idle_gate:
        raise OrchestrationError("diagnostic21 does not accept --skip-gpu-idle-gate")
    if not os.environ.get("TMUX"):
        raise OrchestrationError("execution requires a detached tmux session")
    enforce_offline_environment()
    if not runtime_python.is_file():
        raise OrchestrationError("workspace runtime Python is unavailable: %s" % runtime_python)
    plan = make_plan(exec_root, output_root, mode)
    paths = plan_paths(output_root, mode)
    completed_before = initialize_output(paths, plan, resume)
    if mode == "full226":
        smoke = read_json(plan_paths(output_root, "smoke")["gate"]) if plan_paths(output_root, "smoke")["gate"].is_file() else {}
        if smoke.get("status") != "PASS":
            raise OrchestrationError("full226 cannot start until the isolated smoke3 gate passes")
    if mode == "smoke":
        finished = _finished_smoke_gate(paths, completed_before)
        if finished is not None:
            return finished
    if mode == "full226":
        finished = _finished_full_gate(paths, completed_before)
        if finished is not None:
            return finished
    if mode == DIAGNOSTIC21_MODE:
        finished = _finished_diagnostic21_gate(paths, completed_before)
        if finished is not None:
            return finished
    append_progress(paths, {"event": "RUN_STARTED" if not completed_before else "RUN_RESUMED", "completed_questions": completed_before, "source_snapshot": plan["source_snapshot"], "offline_environment": OFFLINE_ENVIRONMENT})
    if mode == "smoke" and not completed_before:
        if skip_gpu_idle_gate:
            append_progress(paths, {"event": "GPU_IDLE_GATE_BYPASSED", "reason": "explicit_flag"})
        else:
            wait_for_initial_gpu_idle(paths, utilization_max=gpu_utilization_max, used_memory_mib_max=gpu_used_memory_mib_max, poll_seconds=gpu_poll_seconds, stable_interval_seconds=gpu_stable_interval_seconds)
    primary = read_json(Path(str(plan["primary_manifest"])))
    dataset_path = exec_root / str(primary["source_dataset"]["path"])
    if sha256(dataset_path) != primary["source_dataset"]["sha256"]:
        raise OrchestrationError("KoBLEX dataset hash does not match frozen manifest")
    state = warm_state if warm_state is not None else {}
    if "preflight" not in state:
        state["preflight"] = preflight(exec_root, mode, runtime_python)
        append_progress(paths, {"event": "ARTIFACT_PREFLIGHT_PASS", "preflight": state["preflight"]})
        state["ollama_readiness"] = check_local_ollama_readiness(primary["frozen_configuration"])
        append_progress(paths, {"event": "OLLAMA_NON_GENERATIVE_READY", "readiness": state["ollama_readiness"]})
    # Imports below this line are the only retrieval/model-capable path.
    from scripts import run_local_harness
    from runtime.source_snapshot import assert_source_snapshot_unchanged, capture_clean_source_snapshot
    snapshot = capture_clean_source_snapshot(exec_root)
    if {"resources", "questions", "snapshot"}.issubset(state):
        if state["snapshot"].to_dict() != snapshot.to_dict():
            raise OrchestrationError("warm persistent state does not match the immutable source snapshot")
        resources, questions = state["resources"], state["questions"]
    else:
        questions = _load_questions(dataset_path)
        bootstrap_args = _build_v2_run_args("", "", primary["frozen_configuration"], paths["records"], snapshot.to_dict())
        resources = run_local_harness.PersistentHarnessResources(bootstrap_args)
        state.update({"resources": resources, "questions": questions, "snapshot": snapshot})
    all_chunks = [(int(item["start_ordinal"]), int(item["end_ordinal"])) for item in plan["chunks"]]
    prior_chunks: List[Path] = []
    for start, end in all_chunks:
        if end <= completed_before:
            attempt = completed_attempt_for(paths, start, end)
            if attempt is None:
                raise OrchestrationError("PASS checkpoint lacks its immutable completed attempt: %03d-%03d" % (start, end))
            prior_chunks.append(attempt)
            continue
        assert_source_snapshot_unchanged(exec_root, snapshot)
        attempt = completed_attempt_for(paths, start, end)
        if attempt is None:
            attempt, failed = execute_chunk(exec_root, paths, plan, start, end, resources, questions)
            append_progress(paths, {"event": "CHUNK_EXECUTED", "range": [start, end], "completed_questions": end, "chunk_directory": str(attempt), "chunk_execution_failure": failed})
        else:
            append_progress(paths, {"event": "CHUNK_REUSED_FOR_EVALUATOR_RETRY", "range": [start, end], "chunk_directory": str(attempt)})
        prior_chunks.append(attempt)
        checkpoint = evaluate_checkpoint(exec_root, paths, plan, prior_chunks, end, runtime_python)
        append_progress(paths, checkpoint)
        if checkpoint["checkpoint_status"] != "PASS":
            return 1
    final_checkpoint = read_json(paths["checkpoints"] / ("checkpoint-%03d.json" % int(plan["entry_count"])))
    if mode == "smoke":
        gate = smoke_gate(final_checkpoint)
        write_json_new(paths["gate"], gate)
        append_progress(paths, {"event": "SMOKE_GATE", **gate})
        return 0 if gate["status"] == "PASS" else 1
    if mode == DIAGNOSTIC21_MODE:
        gate = diagnostic21_gate(final_checkpoint)
        write_json_new(paths["gate"], gate)
        append_progress(paths, {"event": "DIAGNOSTIC21_GATE", **gate})
        return 0 if gate["status"] == "PASS" else 1
    gate = full226_gate(final_checkpoint)
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "RUN_COMPLETED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def execute_smoke_then_full(
    exec_root: Path, output_root: Path, runtime_python: Path, *, resume: bool = False, skip_gpu_idle_gate: bool = False,
    gpu_utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX, gpu_used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX,
    gpu_poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS, gpu_stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
) -> int:
    """One detached flow: resume smoke safely, then continue immediately into full226."""
    warm_state: Dict[str, Any] = {}
    smoke_exists = plan_paths(output_root, "smoke")["root"].exists()
    smoke_exit = execute_plan(exec_root, output_root, "smoke", runtime_python, resume=resume if smoke_exists else False, skip_gpu_idle_gate=skip_gpu_idle_gate, gpu_utilization_max=gpu_utilization_max, gpu_used_memory_mib_max=gpu_used_memory_mib_max, gpu_poll_seconds=gpu_poll_seconds, gpu_stable_interval_seconds=gpu_stable_interval_seconds, warm_state=warm_state)
    if smoke_exit != 0:
        return smoke_exit
    full_exists = plan_paths(output_root, "full226")["root"].exists()
    return execute_plan(exec_root, output_root, "full226", runtime_python, resume=resume if full_exists else False, warm_state=warm_state)



def verify_diagnostic21_reranker_artifact(configuration: Mapping[str, Any], exec_root: Path) -> Dict[str, str]:
    """CPU-only hash check for the frozen BGE reranker weights; never load the model."""
    provenance = configuration.get("reranker_provenance")
    if provenance != DIAGNOSTIC21_RERANKER_PROVENANCE:
        raise OrchestrationError("diagnostic21 BGE reranker provenance mismatch")
    model_root = _safe_relative_artifact(exec_root, provenance.get("model_path"), "reranker model_path")
    model_weights = model_root / "model.safetensors"
    if not model_weights.is_file():
        raise OrchestrationError("diagnostic21 BGE model.safetensors is missing: %s" % model_weights)
    expected = str(provenance.get("model_weights_sha256") or "")
    if sha256(model_weights) != expected:
        raise OrchestrationError("diagnostic21 BGE model.safetensors hash mismatch")
    return {
        "model_id": str(provenance["model_id"]),
        "model_path": str(provenance["model_path"]),
        "model_weights_sha256": expected,
        "device": str(provenance["device"]),
    }


def verify_diagnostic21_skill_files(exec_root: Path) -> Dict[str, Dict[str, str]]:
    """Hash the frozen S1/S2/S3 instructions and validators before a diagnostic run."""
    verified: Dict[str, Dict[str, str]] = {}
    for skill_id, expected in DIAGNOSTIC21_SKILL_FILES.items():
        item: Dict[str, str] = {}
        for path_key, hash_key in (("skill_path", "skill_sha256"), ("validator_path", "validator_sha256")):
            relative = Path(str(expected[path_key]))
            if relative.is_absolute() or ".." in relative.parts:
                raise OrchestrationError("diagnostic21 skill artifact path is unsafe: %s" % relative)
            artifact = exec_root / relative
            if not artifact.is_file():
                raise OrchestrationError("diagnostic21 skill artifact is missing: %s" % artifact)
            observed = sha256(artifact)
            if observed != expected[hash_key]:
                raise OrchestrationError("diagnostic21 skill artifact hash mismatch: %s" % relative)
            item[hash_key] = observed
        verified[skill_id] = item
    return verified


def diagnostic21_preflight_details(
    clean_source_snapshot: Mapping[str, str],
    skill_file_hashes: Mapping[str, Mapping[str, str]],
    reranker_provenance: Mapping[str, str],
) -> Dict[str, Any]:
    """Diagnostic-only preflight facts, intentionally with no idle/ETA fields."""
    return {
        "clean_source_snapshot": dict(clean_source_snapshot),
        "skill_file_hashes": {key: dict(value) for key, value in skill_file_hashes.items()},
        "reranker_provenance": dict(reranker_provenance),
        "semantic_authority": DIAGNOSTIC21_SEMANTIC_AUTHORITY,
        "bm25_execution": "FORBIDDEN",
        "paired_c02_answer_cohort": {
            "file": DIAGNOSTIC21_C02_ANSWER_COHORT_FILE,
            "sha256": DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            "denominator": DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
            "evaluation_only": True,
        },
    }


def preflight(exec_root: Path, mode: str, runtime_python: Path) -> Dict[str, Any]:
    """CPU-only file/hash preflight. It never contacts Ollama or loads KURE."""
    if not runtime_python.is_file():
        raise OrchestrationError("workspace runtime Python is unavailable: %s" % runtime_python)
    primary_path, reference_path = manifest_paths(exec_root, mode)
    primary, reference = read_json(primary_path), read_json(reference_path)
    comparison = assert_reference_is_read_only(primary, reference, primary_path, reference_path)
    diagnostic21 = mode == DIAGNOSTIC21_MODE
    if diagnostic21:
        assert_diagnostic21_manifest_integrity(primary, reference)
        skill_files = verify_diagnostic21_skill_files(exec_root)
        reranker = verify_diagnostic21_reranker_artifact(primary["frozen_configuration"], exec_root)
        load_frozen_c02_answer_cohort(exec_root)
        clean_snapshot = source_snapshot_dict(exec_root)
    else:
        skill_files = None
        reranker = None
        clean_snapshot = None
    verify_kure_artifacts(primary["frozen_configuration"], exec_root)
    model = primary["frozen_configuration"].get("model_provenance")
    if not isinstance(model, Mapping):
        raise OrchestrationError("model provenance is missing")
    for key, expected_value in QWEN_MODEL_PROVENANCE.items():
        if model.get(key) != expected_value:
            raise OrchestrationError("frozen Qwen model provenance mismatch: %s" % key)
    blob = Path(str(model.get("ollama_model_blob") or ""))
    if not blob.is_file():
        raise OrchestrationError("offline Qwen model blob is missing: %s" % blob)
    expected = str(model.get("sha256") or "")
    if len(expected) != 64 or sha256(blob) != expected:
        raise OrchestrationError("offline Qwen model blob hash mismatch")
    result = {"status": "PASS", "mode": mode, "runtime_python": str(runtime_python), "comparison": comparison, "offline_environment": OFFLINE_ENVIRONMENT, "model_blob": str(blob), "model_blob_sha256": expected}
    if diagnostic21:
        result["diagnostic21"] = diagnostic21_preflight_details(clean_snapshot, skill_files, reranker)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "run", "preflight"))
    parser.add_argument("--exec-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--mode", choices=("smoke", "full226", DIAGNOSTIC21_MODE, "all"), default="smoke")
    parser.add_argument("--primary-source-manifest", type=Path)
    parser.add_argument("--reference-source-manifest", type=Path)
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-gpu-idle-gate", action="store_true", help="explicitly bypass the initial smoke-only GPU idle gate")
    parser.add_argument("--gpu-utilization-max", type=int, default=DEFAULT_GPU_IDLE_UTILIZATION_MAX)
    parser.add_argument("--gpu-used-memory-mib-max", type=int, default=DEFAULT_GPU_IDLE_USED_MIB_MAX)
    parser.add_argument("--gpu-poll-seconds", type=int, default=DEFAULT_GPU_IDLE_POLL_SECONDS)
    parser.add_argument("--gpu-stable-interval-seconds", type=int, default=DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exec_root = args.exec_root.resolve()
    runtime_python = (args.runtime_python or exec_root / ".venv/bin/python").resolve()
    if args.command == "bootstrap":
        if args.output_root is not None or not args.primary_source_manifest or not args.reference_source_manifest:
            raise OrchestrationError("bootstrap requires exactly both source manifests and no output root")
        paths = write_v2_manifests(exec_root, args.primary_source_manifest.resolve(), args.reference_source_manifest.resolve())
        print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.output_root is None:
        raise OrchestrationError("run/preflight require --output-root")
    if args.mode == DIAGNOSTIC21_MODE and args.skip_gpu_idle_gate:
        raise OrchestrationError("diagnostic21 does not accept --skip-gpu-idle-gate")
    output_root = args.output_root.resolve()
    if args.command == "preflight":
        if args.mode == "all":
            raise OrchestrationError("preflight requires smoke, full226, or diagnostic21 mode")
        print(json.dumps(preflight(exec_root, args.mode, runtime_python), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    plans = [make_plan(exec_root, output_root, name) for name in (("smoke", "full226") if args.mode == "all" else (args.mode,))]
    if args.dry_run:
        payload = {"status": "DRY_RUN", "plans": plans, "runtime_python": str(runtime_python), "would_require_tmux": True}
        if args.mode != DIAGNOSTIC21_MODE:
            payload["gpu_idle_gate"] = {"smoke_only": True, "bypass_requested": args.skip_gpu_idle_gate, "utilization_max": args.gpu_utilization_max, "used_memory_mib_max": args.gpu_used_memory_mib_max, "poll_seconds": args.gpu_poll_seconds, "stable_interval_seconds": args.gpu_stable_interval_seconds, "required_stable_samples": DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.mode == "all":
        return execute_smoke_then_full(exec_root, output_root, runtime_python, resume=args.resume, skip_gpu_idle_gate=args.skip_gpu_idle_gate, gpu_utilization_max=args.gpu_utilization_max, gpu_used_memory_mib_max=args.gpu_used_memory_mib_max, gpu_poll_seconds=args.gpu_poll_seconds, gpu_stable_interval_seconds=args.gpu_stable_interval_seconds)
    return execute_plan(exec_root, output_root, args.mode, runtime_python, args.resume, skip_gpu_idle_gate=args.skip_gpu_idle_gate, gpu_utilization_max=args.gpu_utilization_max, gpu_used_memory_mib_max=args.gpu_used_memory_mib_max, gpu_poll_seconds=args.gpu_poll_seconds, gpu_stable_interval_seconds=args.gpu_stable_interval_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrchestrationError as exc:
        print("orchestration error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
