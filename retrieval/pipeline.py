"""BM25-or-KURE -> within-retriever RRF -> broad-pool BGE reranking."""

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple

from harness.contracts import (
    ArticleFamilyExpansionRecord,
    CandidateProvision,
    CandidateStageRecord,
    RetrievalRequest,
)

from .corpus import ArticleFamilyMember, ProvisionDocument, legal_text_alias_key
from .reranker import Reranker
from .rrf import reciprocal_rank_fusion
from .types import FusedHit, RetrievalHit


@dataclass(frozen=True)
class _RequestRerankObservation:
    hit: FusedHit
    rerank_score: float
    rerank_rank: int


@dataclass(frozen=True)
class _ArticleFamilyExpansion:
    hit: FusedHit
    root_hit: FusedHit
    root_baseline_rerank_score: float
    family_key: str
    baseline_rerank_rank: int


class FirstStageSearcher(Protocol):
    def search(self, request: RetrievalRequest) -> List[RetrievalHit]:
        ...


class RetrievalPipeline:
    """Use exactly one first-stage searcher per experimental condition.

    The pipeline deliberately has one `first_stage` instance: BM25+KURE hybrid
    retrieval is excluded by the frozen study design.
    """

    def __init__(
        self,
        first_stage: FirstStageSearcher,
        reranker: Reranker = None,
        rrf_k: int = 60,
        rerank_pool_k: int = 100,
        final_top_k: int = 10,
        rerank_query_mode: str = "combined_issue",
        candidate_selection: str = "global_top_k",
        per_evidence_min_k: int = 1,
        dedup_mode: str = "none",
        candidate_budget_scope: str = "per_issue",
        round_merge_mode: str = "raw_score",
        article_family_sibling_rerank_expansion: bool = False,
        article_family_expansion_trigger_top_k: int = 3,
        article_family_expansion_max_siblings_per_root: int = 4,
        article_family_expansion_max_siblings_per_request: int = 8,
        article_family_expansion_max_family_members_scored: int = 128,
    ):
        if rrf_k < 1:
            raise ValueError("RRF k must be positive")
        if rerank_pool_k < 1 or final_top_k < 1:
            raise ValueError("rerank pool and final cutoff must be positive")
        if rerank_query_mode not in {"combined_issue", "per_request"}:
            raise ValueError("unsupported rerank query mode: %s" % rerank_query_mode)
        if candidate_selection not in {"global_top_k", "evidence_balanced"}:
            raise ValueError("unsupported candidate selection: %s" % candidate_selection)
        if dedup_mode not in {"none", "legal_text_alias"}:
            raise ValueError("unsupported dedup mode: %s" % dedup_mode)
        if candidate_budget_scope not in {"per_issue", "per_round"}:
            raise ValueError(
                "unsupported candidate budget scope: %s" % candidate_budget_scope
            )
        if round_merge_mode not in {
            "raw_score",
            "request_rank_top1_guarded_swap",
            "single_issue_fusion_top_k",
        }:
            raise ValueError("unsupported round merge mode: %s" % round_merge_mode)
        if (
            round_merge_mode == "request_rank_top1_guarded_swap"
            and rerank_query_mode != "per_request"
        ):
            raise ValueError(
                "request-rank guarded swapping requires per_request reranking"
            )
        if (
            round_merge_mode == "request_rank_top1_guarded_swap"
            and candidate_budget_scope != "per_round"
        ):
            raise ValueError(
                "request-rank guarded swapping requires per_round candidate budgeting"
            )
        if (
            round_merge_mode == "single_issue_fusion_top_k"
            and rerank_query_mode != "per_request"
        ):
            raise ValueError(
                "single-issue fusion retention requires per_request reranking"
            )
        if (
            round_merge_mode == "single_issue_fusion_top_k"
            and candidate_budget_scope != "per_round"
        ):
            raise ValueError(
                "single-issue fusion retention requires per_round candidate budgeting"
            )
        if per_evidence_min_k < 1:
            raise ValueError("per_evidence_min_k must be positive")
        if final_top_k > rerank_pool_k:
            raise ValueError("final cutoff cannot exceed the rerank pool")
        expansion_values = (
            article_family_expansion_trigger_top_k,
            article_family_expansion_max_siblings_per_root,
            article_family_expansion_max_siblings_per_request,
            article_family_expansion_max_family_members_scored,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in expansion_values
        ):
            raise ValueError("article-family expansion bounds must be positive integers")
        if not isinstance(article_family_sibling_rerank_expansion, bool):
            raise ValueError("article-family sibling expansion must be a boolean")
        article_family_provider = None
        if article_family_sibling_rerank_expansion:
            if rerank_query_mode != "per_request":
                raise ValueError(
                    "article-family sibling expansion requires per_request reranking"
                )
            if getattr(
                first_stage,
                "article_family_sibling_expansion_capability",
                None,
            ) != "kure_exact":
                raise ValueError(
                    "article-family sibling expansion requires KURE corpus capability"
                )
            if not callable(getattr(first_stage, "article_family_members", None)):
                raise ValueError(
                    "article-family sibling expansion requires KURE family members"
                )
            article_family_provider = first_stage
        self.first_stage = first_stage
        if reranker is None:
            raise ValueError("a BGE-compatible reranker must be configured")
        self.reranker = reranker
        self.rrf_k = rrf_k
        self.rerank_pool_k = rerank_pool_k
        self.final_top_k = final_top_k
        self.rerank_query_mode = rerank_query_mode
        self.candidate_selection = candidate_selection
        self.per_evidence_min_k = per_evidence_min_k
        self.dedup_mode = dedup_mode
        self.candidate_budget_scope = candidate_budget_scope
        self.round_merge_mode = round_merge_mode
        self.article_family_sibling_rerank_expansion = (
            article_family_sibling_rerank_expansion
        )
        self.article_family_expansion_trigger_top_k = (
            article_family_expansion_trigger_top_k
        )
        self.article_family_expansion_max_siblings_per_root = (
            article_family_expansion_max_siblings_per_root
        )
        self.article_family_expansion_max_siblings_per_request = (
            article_family_expansion_max_siblings_per_request
        )
        self.article_family_expansion_max_family_members_scored = (
            article_family_expansion_max_family_members_scored
        )
        self._article_family_provider = article_family_provider
        self._request_rerank_ranks_by_candidate: Dict[
            Tuple[str, str], Dict[str, int]
        ] = {}
        self._prior_round_selected_provision_ids: Set[str] = set()
        self._last_retrieval_round = 0
        self.last_stage_records: List[object] = []
        self.last_unsatisfied_critical_evidence_item_ids: List[str] = []
        self.last_dedup_removed_count = 0

    @staticmethod
    def _request_query_text(request: RetrievalRequest, field_name: str) -> str:
        return getattr(request, field_name, None) or request.query_text

    def _first_stage_request(self, request: RetrievalRequest) -> RetrievalRequest:
        first_stage_query_text = self._request_query_text(
            request, "first_stage_query_text"
        )
        if first_stage_query_text == request.query_text:
            return request
        # Persistent BM25 otherwise gives legacy query_terms precedence over
        # query_text, which would silently defeat the explicit recall query.
        return replace(
            request,
            query_text=first_stage_query_text,
            query_terms=[],
        )

    @staticmethod
    def _alias_provision_ids(hit: FusedHit) -> List[str]:
        return list(
            dict.fromkeys([hit.document.provision_id] + hit.alias_provision_ids)
        )

    def _collapse_legal_text_aliases(
        self,
        reranked: Sequence[Tuple[FusedHit, float]],
    ) -> List[Tuple[FusedHit, float]]:
        if self.dedup_mode == "none":
            return list(reranked)

        grouped: Dict[Tuple[str, str], List[Tuple[FusedHit, float]]] = {}
        for hit, rerank_score in reranked:
            grouped.setdefault(legal_text_alias_key(hit.document), []).append(
                (hit, rerank_score)
            )

        collapsed: List[Tuple[FusedHit, float]] = []
        for aliases in grouped.values():
            representative, rerank_score = aliases[0]
            source_request_ids: List[str] = []
            source_first_stage_ranks: Dict[str, int] = {}
            alias_provision_ids: List[str] = []
            for hit, _ in aliases:
                for request_id in hit.source_request_ids:
                    if request_id not in source_request_ids:
                        source_request_ids.append(request_id)
                    rank = hit.source_first_stage_ranks.get(request_id)
                    previous_rank = source_first_stage_ranks.get(request_id)
                    if rank is not None and (
                        previous_rank is None or rank < previous_rank
                    ):
                        source_first_stage_ranks[request_id] = rank
                for provision_id in self._alias_provision_ids(hit):
                    if provision_id not in alias_provision_ids:
                        alias_provision_ids.append(provision_id)
            collapsed.append(
                (
                    replace(
                        representative,
                        first_stage_score=self._maximum_first_stage_score(
                            hit for hit, _ in aliases
                        ),
                        source_request_ids=source_request_ids,
                        source_first_stage_ranks=source_first_stage_ranks,
                        first_stage_rank=(
                            min(source_first_stage_ranks.values())
                            if source_first_stage_ranks
                            else None
                        ),
                        alias_provision_ids=alias_provision_ids,
                    ),
                    rerank_score,
                )
            )
            self.last_dedup_removed_count += len(aliases) - 1
        return collapsed

    def _record_alias_collapse(
        self,
        hit: FusedHit,
        rerank_score: float,
        retrieval_round: int,
        requests_by_id: Dict[str, RetrievalRequest],
    ) -> None:
        alias_provision_ids = self._alias_provision_ids(hit)
        if len(alias_provision_ids) < 2:
            return
        self.last_stage_records.append(
            CandidateStageRecord(
                provision_id=hit.document.provision_id,
                retrieval_round=retrieval_round,
                candidate_stage="dedup_collapse",
                source_request_ids=list(hit.source_request_ids),
                target_evidence_item_ids=self._target_evidence_ids(
                    hit.source_request_ids, requests_by_id
                ),
                first_stage_rank=hit.first_stage_rank,
                fusion_rank=hit.fusion_rank,
                first_stage_score=hit.first_stage_score,
                rerank_score=rerank_score,
                selection_reason="legal_text_alias",
                alias_provision_ids=alias_provision_ids,
            )
        )

    @staticmethod
    def _alias_groups_by_provision_id(
        hits: Sequence[FusedHit],
    ) -> Dict[str, List[str]]:
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for hit in hits:
            aliases = grouped.setdefault(legal_text_alias_key(hit.document), [])
            for provision_id in RetrievalPipeline._alias_provision_ids(hit):
                if provision_id not in aliases:
                    aliases.append(provision_id)
        return {
            provision_id: aliases
            for aliases in grouped.values()
            for provision_id in aliases
        }

    def _collapse_ranked_ids_by_alias(
        self,
        ranked_ids: Sequence[str],
        alias_groups_by_id: Dict[str, List[str]],
    ) -> List[str]:
        if self.dedup_mode == "none":
            return list(ranked_ids)
        selected: List[str] = []
        seen_representatives: Set[str] = set()
        for provision_id in ranked_ids:
            aliases = alias_groups_by_id[provision_id]
            representative_id = min(aliases)
            if representative_id not in seen_representatives:
                selected.append(representative_id)
                seen_representatives.add(representative_id)
        return selected

    @staticmethod
    def _observations_for_aliases(
        issue_requests: Sequence[RetrievalRequest],
        observations_by_request: Dict[str, Dict[str, _RequestRerankObservation]],
        alias_provision_ids: Sequence[str],
    ) -> Tuple[List[str], List[_RequestRerankObservation]]:
        aliases = set(alias_provision_ids)
        source_request_ids: List[str] = []
        observations: List[_RequestRerankObservation] = []
        for request in issue_requests:
            request_observations = [
                observation
                for observation in observations_by_request[request.request_id].values()
                if aliases.intersection(
                    RetrievalPipeline._alias_provision_ids(observation.hit)
                )
            ]
            if request_observations:
                source_request_ids.append(request.request_id)
                observations.extend(request_observations)
        return source_request_ids, observations

    def _round_ranked_candidates(
        self,
        candidates: Sequence[CandidateProvision],
    ) -> List[CandidateProvision]:
        """Merge repeated candidates before an opt-in round-wide final cutoff."""
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.rerank_score,
                candidate.fusion_rank,
                candidate.provision_id,
                candidate.issue_id,
            ),
        )
        grouped: Dict[object, List[CandidateProvision]] = {}
        for candidate in ranked:
            key: object = candidate.provision_id
            if self.dedup_mode == "legal_text_alias":
                key = legal_text_alias_key(
                    ProvisionDocument(
                        candidate.provision_id,
                        candidate.statute_name,
                        candidate.provision_text,
                    )
                )
            grouped.setdefault(key, []).append(candidate)

        merged: List[CandidateProvision] = []
        for equivalents in grouped.values():
            representative = equivalents[0]
            if self.dedup_mode == "legal_text_alias":
                self.last_dedup_removed_count += len(equivalents) - 1
            source_request_ids: List[str] = []
            target_evidence_item_ids: List[str] = []
            alias_provision_ids: List[str] = []
            for candidate in equivalents:
                for request_id in candidate.source_request_ids:
                    if request_id not in source_request_ids:
                        source_request_ids.append(request_id)
                for evidence_id in candidate.target_evidence_item_ids:
                    if evidence_id not in target_evidence_item_ids:
                        target_evidence_item_ids.append(evidence_id)
                for provision_id in [
                    candidate.provision_id,
                    *candidate.alias_provision_ids,
                ]:
                    if provision_id not in alias_provision_ids:
                        alias_provision_ids.append(provision_id)
            request_rerank_ranks: Dict[str, int] = {}
            for candidate in equivalents:
                for request_id, rank in self._request_rerank_ranks_by_candidate.get(
                    (candidate.issue_id, candidate.provision_id),
                    {},
                ).items():
                    request_rerank_ranks[request_id] = min(
                        request_rerank_ranks.get(request_id, rank),
                        rank,
                    )
            self._request_rerank_ranks_by_candidate[
                (representative.issue_id, representative.provision_id)
            ] = request_rerank_ranks
            merged.append(
                replace(
                    representative,
                    first_stage_score=(
                        max(
                            score
                            for candidate in equivalents
                            if (score := candidate.first_stage_score) is not None
                        )
                        if any(
                            candidate.first_stage_score is not None
                            for candidate in equivalents
                        )
                        else None
                    ),
                    source_request_ids=source_request_ids,
                    target_evidence_item_ids=target_evidence_item_ids,
                    alias_provision_ids=alias_provision_ids,
                )
            )
        return merged

    def _request_rank_round_robin(
        self,
        candidates: Sequence[CandidateProvision],
        request_ids: Sequence[str],
    ) -> List[Tuple[CandidateProvision, str, int]]:
        """Return a deterministic fair ordering from request-local BGE ranks.

        The ranks are kept outside ``CandidateProvision`` because its public
        ``rerank_rank`` is the issue-fusion rank in per-request mode. Keeping
        this transient provenance separate avoids changing legacy records.
        """
        queues: Dict[str, List[Tuple[CandidateProvision, int]]] = {}
        for request_id in request_ids:
            queue: List[Tuple[CandidateProvision, int]] = []
            for candidate in candidates:
                request_ranks = self._request_rerank_ranks_by_candidate.get(
                    (candidate.issue_id, candidate.provision_id),
                    {},
                )
                request_rank = request_ranks.get(request_id)
                if request_rank is not None:
                    queue.append((candidate, request_rank))
            queues[request_id] = sorted(
                queue,
                key=lambda item: (
                    item[1],
                    -item[0].rerank_score,
                    item[0].fusion_rank,
                    item[0].provision_id,
                    item[0].issue_id,
                ),
            )

        offsets = {request_id: 0 for request_id in request_ids}
        ordered: List[Tuple[CandidateProvision, str, int]] = []
        seen_provision_ids: Set[Tuple[str, str]] = set()
        while True:
            made_progress = False
            for request_id in request_ids:
                queue = queues[request_id]
                while offsets[request_id] < len(queue):
                    candidate, request_rank = queue[offsets[request_id]]
                    offsets[request_id] += 1
                    candidate_key = (candidate.issue_id, candidate.provision_id)
                    if candidate_key in seen_provision_ids:
                        continue
                    seen_provision_ids.add(candidate_key)
                    ordered.append((candidate, request_id, request_rank))
                    made_progress = True
                    break
            if not made_progress:
                return ordered

    def _apply_request_rank_guarded_swap(
        self,
        selected: List[CandidateProvision],
        quota_selected: Set[int],
        candidates: Sequence[CandidateProvision],
        request_ids: Sequence[str],
    ) -> Dict[int, str]:
        """Allow one fair, request-rank-one proposal to replace raw slot N."""
        if (
            self.round_merge_mode != "request_rank_top1_guarded_swap"
            or len(selected) != self.final_top_k
            or self.final_top_k < 2
            or id(selected[-1]) in quota_selected
        ):
            return {}

        selected_provision_ids = {
            provision_id
            for candidate in selected
            for provision_id in self._candidate_provision_ids(candidate)
        }
        for candidate, request_id, request_rank in self._request_rank_round_robin(
            candidates,
            request_ids,
        ):
            candidate_provision_ids = self._candidate_provision_ids(candidate)
            if (
                candidate_provision_ids.intersection(selected_provision_ids)
                or candidate_provision_ids.intersection(
                    self._prior_round_selected_provision_ids
                )
                or request_rank != 1
            ):
                continue
            selected[-1] = candidate
            return {
                id(candidate): (
                    "round_request_rank_top1_guarded_swap:"
                    "request_id=%s;rerank_rank=1" % request_id
                )
            }
        return {}

    @staticmethod
    def _candidate_provision_ids(candidate: CandidateProvision) -> Set[str]:
        return {
            candidate.provision_id,
            *candidate.alias_provision_ids,
        }

    def _select_round_candidates(
        self,
        candidates: Sequence[CandidateProvision],
        critical_evidence_item_ids: Sequence[str],
        retrieval_round: int,
        request_ids: Sequence[str] = (),
    ) -> List[CandidateProvision]:
        ranked = self._round_ranked_candidates(candidates)
        selected: List[CandidateProvision] = []
        quota_selected: Set[int] = set()
        critical_ids = []
        if self.candidate_selection == "evidence_balanced":
            critical_ids = list(dict.fromkeys(critical_evidence_item_ids))
            for quota_target in range(1, self.per_evidence_min_k + 1):
                for evidence_id in critical_ids:
                    current_count = sum(
                        evidence_id in candidate.target_evidence_item_ids
                        for candidate in selected
                    )
                    if current_count >= quota_target or len(selected) >= self.final_top_k:
                        continue
                    candidate = next(
                        (
                            candidate
                            for candidate in ranked
                            if evidence_id in candidate.target_evidence_item_ids
                            and candidate not in selected
                        ),
                        None,
                    )
                    if candidate is not None:
                        selected.append(candidate)
                        quota_selected.add(id(candidate))

        for candidate in ranked:
            if len(selected) >= self.final_top_k:
                break
            if candidate not in selected:
                selected.append(candidate)

        swap_reasons = self._apply_request_rank_guarded_swap(
            selected,
            quota_selected,
            ranked,
            request_ids,
        )

        unsatisfied = []
        if self.candidate_selection == "evidence_balanced":
            unsatisfied = [
                evidence_id
                for evidence_id in critical_ids
                if sum(
                    evidence_id in candidate.target_evidence_item_ids
                    for candidate in selected
                ) < self.per_evidence_min_k
            ]
        self.last_unsatisfied_critical_evidence_item_ids.extend(unsatisfied)
        final_candidates: List[CandidateProvision] = []
        for selection_rank, candidate in enumerate(selected, start=1):
            if id(candidate) in swap_reasons:
                selection_reason = swap_reasons[id(candidate)]
            elif id(candidate) in quota_selected:
                matched_evidence = [
                    evidence_id
                    for evidence_id in critical_ids
                    if evidence_id in candidate.target_evidence_item_ids
                ]
                selection_reason = "critical_quota:%s" % ",".join(matched_evidence)
            else:
                selection_reason = (
                    "round_global_top_k"
                    if self.candidate_selection == "global_top_k"
                    else "round_global_score_fill"
                )
            final_candidate = replace(
                candidate,
                selection_rank=selection_rank,
                candidate_stage="selected",
                selection_reason=selection_reason,
            )
            final_candidates.append(final_candidate)
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=final_candidate.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="round_selected",
                    source_request_ids=final_candidate.source_request_ids,
                    target_evidence_item_ids=final_candidate.target_evidence_item_ids,
                    first_stage_rank=final_candidate.first_stage_rank,
                    fusion_rank=final_candidate.fusion_rank,
                    rerank_rank=final_candidate.rerank_rank,
                    selection_rank=selection_rank,
                    first_stage_score=final_candidate.first_stage_score,
                    rerank_score=final_candidate.rerank_score,
                    selection_reason=selection_reason,
                    alias_provision_ids=final_candidate.alias_provision_ids,
                )
            )
        return final_candidates

    def _select_single_issue_later_round_candidates(
        self,
        candidates: Sequence[CandidateProvision],
        critical_evidence_item_ids: Sequence[str],
        retrieval_round: int,
    ) -> List[CandidateProvision]:
        """Retain the issue-fusion cutoff when a later round has one issue.

        Per-request reranking creates scores on separate query scales. Once a
        gap-repair round has only one issue, sorting those raw scores a second
        time cannot arbitrate between issues; it can only discard the
        issue-level fusion ordering already established above. Preserve that
        ordering at the ordinary final cutoff instead. Round one and
        multi-issue rounds continue through the existing round-wide selector.
        """
        # ``selection_rank`` is the issue-level ``_select_ids`` order: critical
        # evidence quota picks precede the issue-fusion fill. Keep that order,
        # rather than rebuilding it from raw cross-request scores or from the
        # fusion rank alone.
        ranked = sorted(
            self._round_ranked_candidates(candidates),
            key=lambda candidate: (
                candidate.selection_rank or self.rerank_pool_k + 1,
                candidate.fusion_rank,
                candidate.provision_id,
                candidate.issue_id,
            ),
        )
        selected = ranked[: self.final_top_k]
        if self.candidate_selection == "evidence_balanced":
            critical_ids = list(dict.fromkeys(critical_evidence_item_ids))
            unsatisfied = [
                evidence_id
                for evidence_id in critical_ids
                if sum(
                    evidence_id in candidate.target_evidence_item_ids
                    for candidate in selected
                )
                < self.per_evidence_min_k
            ]
            self.last_unsatisfied_critical_evidence_item_ids.extend(unsatisfied)
        final_candidates: List[CandidateProvision] = []
        for selection_rank, candidate in enumerate(selected, start=1):
            if candidate.selection_reason.startswith("critical_quota:"):
                selection_reason = "round_single_issue_%s" % candidate.selection_reason
            else:
                selection_reason = "round_single_issue_fusion_top_k"
            final_candidate = replace(
                candidate,
                selection_rank=selection_rank,
                candidate_stage="selected",
                selection_reason=selection_reason,
            )
            final_candidates.append(final_candidate)
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=final_candidate.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="round_selected",
                    source_request_ids=final_candidate.source_request_ids,
                    target_evidence_item_ids=final_candidate.target_evidence_item_ids,
                    first_stage_rank=final_candidate.first_stage_rank,
                    fusion_rank=final_candidate.fusion_rank,
                    rerank_rank=final_candidate.rerank_rank,
                    selection_rank=selection_rank,
                    first_stage_score=final_candidate.first_stage_score,
                    rerank_score=final_candidate.rerank_score,
                    selection_reason=selection_reason,
                    alias_provision_ids=final_candidate.alias_provision_ids,
                )
            )
        return final_candidates

    @staticmethod
    def _target_evidence_ids(
        source_request_ids: Sequence[str],
        requests_by_id: Dict[str, RetrievalRequest],
    ) -> List[str]:
        return list(
            dict.fromkeys(
                requests_by_id[request_id].evidence_item_id
                for request_id in source_request_ids
            )
        )

    def _rank_fuse_ids(
        self,
        ranked_id_lists: Sequence[Sequence[str]],
    ) -> List[Tuple[str, float]]:
        scores: Dict[str, float] = defaultdict(float)
        for ranked_ids in ranked_id_lists:
            seen: Set[str] = set()
            for rank, provision_id in enumerate(ranked_ids, start=1):
                if provision_id in seen:
                    continue
                seen.add(provision_id)
                scores[provision_id] += 1.0 / (self.rrf_k + rank)
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))

    def _rerank(
        self,
        query_text: str,
        pool: Sequence[FusedHit],
    ) -> List[Tuple[FusedHit, float]]:
        raw_scores = list(self.reranker.rerank(query_text, pool, len(pool)))
        if len(raw_scores) != len(pool):
            raise ValueError("reranker must score every hit in the rerank pool")
        scores: List[float] = []
        for raw_score in raw_scores:
            if isinstance(raw_score, bool):
                raise ValueError("reranker scores must be finite numbers")
            try:
                score = float(raw_score)
            except (TypeError, ValueError) as exc:
                raise ValueError("reranker scores must be finite numbers") from exc
            if not math.isfinite(score):
                raise ValueError("reranker scores must be finite numbers")
            scores.append(score)
        return sorted(
            zip(pool, scores),
            key=lambda pair: (-pair[1], pair[0].document.provision_id),
        )

    @staticmethod
    def _maximum_first_stage_score(
        hits: Sequence[FusedHit],
    ) -> Optional[float]:
        scores = [hit.first_stage_score for hit in hits if hit.first_stage_score is not None]
        return max(scores) if scores else None

    @staticmethod
    def _minimum_first_stage_rank(
        observations: Sequence[_RequestRerankObservation],
    ) -> Optional[int]:
        ranks = [
            observation.hit.first_stage_rank
            for observation in observations
            if observation.hit.first_stage_rank is not None
        ]
        return min(ranks) if ranks else None

    def _expand_request_article_family_siblings(
        self,
        request: RetrievalRequest,
        baseline_reranked: Sequence[Tuple[FusedHit, float]],
        retrieval_round: int,
    ) -> List[Tuple[FusedHit, float]]:
        """Score every bounded KURE family before applying selection caps."""
        if not self.article_family_sibling_rerank_expansion:
            return list(baseline_reranked)
        provider = self._article_family_provider
        if provider is None:
            raise RuntimeError("article-family expansion capability was not initialized")

        known_provision_ids = {
            provision_id
            for hit, _ in baseline_reranked
            for provision_id in self._alias_provision_ids(hit)
        }
        seen_family_keys: Set[str] = set()
        root_contexts: List[Tuple[FusedHit, float, str, int]] = []
        expansions_by_root: Dict[str, List[_ArticleFamilyExpansion]] = {}
        all_expansions: List[_ArticleFamilyExpansion] = []
        for baseline_rerank_rank, (root_hit, root_rerank_score) in enumerate(
            baseline_reranked[: self.article_family_expansion_trigger_top_k],
            start=1,
        ):
            members = list(provider.article_family_members(root_hit.document.provision_id))
            if not members:
                continue
            if not all(isinstance(member, ArticleFamilyMember) for member in members):
                raise ValueError("KURE article-family members are invalid")
            if len(members) > self.article_family_expansion_max_family_members_scored:
                raise ValueError(
                    "article-family member count exceeds max_family_members_scored"
                )
            family_key = members[0].family_key
            if (
                not isinstance(family_key, str)
                or not family_key
                or any(member.family_key != family_key for member in members)
            ):
                raise ValueError("KURE article-family key is invalid")
            if family_key in seen_family_keys:
                continue
            seen_family_keys.add(family_key)
            root_id = root_hit.document.provision_id
            root_contexts.append(
                (root_hit, root_rerank_score, family_key, baseline_rerank_rank)
            )
            expansions_by_root[root_id] = []
            for member in sorted(members, key=lambda item: item.document.provision_id):
                alias_provision_ids = tuple(member.alias_provision_ids)
                if (
                    not alias_provision_ids
                    or member.document.provision_id not in alias_provision_ids
                    or len(alias_provision_ids) != len(set(alias_provision_ids))
                ):
                    raise ValueError("KURE article-family aliases are invalid")
                if known_provision_ids.intersection(alias_provision_ids):
                    continue
                expanded_hit = FusedHit(
                    document=member.document,
                    rrf_score=None,
                    first_stage_score=None,
                    source_request_ids=[request.request_id],
                    source_first_stage_ranks={},
                    first_stage_rank=None,
                    fusion_rank=None,
                    alias_provision_ids=list(alias_provision_ids),
                )
                expansion = _ArticleFamilyExpansion(
                    hit=expanded_hit,
                    root_hit=root_hit,
                    root_baseline_rerank_score=root_rerank_score,
                    family_key=family_key,
                    baseline_rerank_rank=baseline_rerank_rank,
                )
                expansions_by_root[root_id].append(expansion)
                all_expansions.append(expansion)

        scored_expansions: List[Tuple[_ArticleFamilyExpansion, float, int]] = []
        if all_expansions:
            rerank_query = self._request_query_text(request, "rerank_query_text")
            expansion_by_id = {
                expansion.hit.document.provision_id: expansion
                for expansion in all_expansions
            }
            for rerank_rank, (hit, rerank_score) in enumerate(
                self._rerank(rerank_query, [expansion.hit for expansion in all_expansions]),
                start=1,
            ):
                scored_expansions.append(
                    (expansion_by_id[hit.document.provision_id], rerank_score, rerank_rank)
                )

        selected_by_id: Dict[str, int] = {}
        dropped_reason_by_id: Dict[str, str] = {}
        selected_per_root: Dict[str, int] = defaultdict(int)
        selected_expansions: List[Tuple[_ArticleFamilyExpansion, float]] = []
        for expansion, rerank_score, _ in scored_expansions:
            provision_id = expansion.hit.document.provision_id
            root_id = expansion.root_hit.document.provision_id
            if (
                selected_per_root[root_id]
                >= self.article_family_expansion_max_siblings_per_root
            ):
                dropped_reason_by_id[provision_id] = "per_root_cap"
                continue
            if (
                len(selected_expansions)
                >= self.article_family_expansion_max_siblings_per_request
            ):
                dropped_reason_by_id[provision_id] = "per_request_cap"
                continue
            selected_per_root[root_id] += 1
            selected_by_id[provision_id] = len(selected_expansions) + 1
            selected_expansions.append((expansion, rerank_score))

        for root_hit, root_rerank_score, family_key, baseline_rerank_rank in root_contexts:
            root_id = root_hit.document.provision_id
            root_expansions = expansions_by_root[root_id]
            candidate_count = len(root_expansions)
            selected_count = selected_per_root[root_id]
            self.last_stage_records.append(
                ArticleFamilyExpansionRecord(
                    provision_id=root_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="article_family_expansion_trigger",
                    source_request_ids=[request.request_id],
                    target_evidence_item_ids=[request.evidence_item_id],
                    article_family_key=family_key,
                    article_family_root_provision_id=root_id,
                    article_family_sibling_candidate_count=candidate_count,
                    article_family_sibling_scored_count=candidate_count,
                    article_family_sibling_selected_count=selected_count,
                    article_family_sibling_dropped_count=(
                        candidate_count - selected_count
                    ),
                    article_family_sibling_per_root_cap=(
                        self.article_family_expansion_max_siblings_per_root
                    ),
                    article_family_sibling_per_request_cap=(
                        self.article_family_expansion_max_siblings_per_request
                    ),
                    article_family_max_members_scored=(
                        self.article_family_expansion_max_family_members_scored
                    ),
                    article_family_root_first_stage_rank=root_hit.first_stage_rank,
                    article_family_root_fusion_rank=root_hit.fusion_rank,
                    article_family_root_first_stage_score=root_hit.first_stage_score,
                    article_family_root_fusion_score=root_hit.rrf_score,
                    article_family_root_baseline_rerank_rank=baseline_rerank_rank,
                    article_family_root_baseline_rerank_score=root_rerank_score,
                    selection_reason=(
                        "article_family_score_before_select_trigger:baseline_rerank_rank=%d"
                        % baseline_rerank_rank
                    ),
                    alias_provision_ids=self._alias_provision_ids(root_hit),
                )
            )

        for expansion, rerank_score, rerank_rank in scored_expansions:
            hit = expansion.hit
            root_id = expansion.root_hit.document.provision_id
            root_expansions = expansions_by_root[root_id]
            selected_count = selected_per_root[root_id]
            provision_id = hit.document.provision_id
            selection_rank = selected_by_id.get(provision_id)
            dropped_reason = dropped_reason_by_id.get(provision_id, "")
            self.last_stage_records.append(
                ArticleFamilyExpansionRecord(
                    provision_id=provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="article_family_sibling_rerank",
                    source_request_ids=[request.request_id],
                    target_evidence_item_ids=[request.evidence_item_id],
                    article_family_key=expansion.family_key,
                    article_family_root_provision_id=root_id,
                    article_family_sibling_candidate_count=len(root_expansions),
                    article_family_sibling_scored_count=len(root_expansions),
                    article_family_sibling_selected_count=selected_count,
                    article_family_sibling_dropped_count=(
                        len(root_expansions) - selected_count
                    ),
                    article_family_sibling_per_root_cap=(
                        self.article_family_expansion_max_siblings_per_root
                    ),
                    article_family_sibling_per_request_cap=(
                        self.article_family_expansion_max_siblings_per_request
                    ),
                    article_family_max_members_scored=(
                        self.article_family_expansion_max_family_members_scored
                    ),
                    article_family_sibling_selected=selection_rank is not None,
                    article_family_sibling_selection_rank=selection_rank,
                    article_family_sibling_dropped_reason=dropped_reason,
                    article_family_root_first_stage_rank=(
                        expansion.root_hit.first_stage_rank
                    ),
                    article_family_root_fusion_rank=expansion.root_hit.fusion_rank,
                    article_family_root_first_stage_score=(
                        expansion.root_hit.first_stage_score
                    ),
                    article_family_root_fusion_score=expansion.root_hit.rrf_score,
                    article_family_root_baseline_rerank_rank=(
                        expansion.baseline_rerank_rank
                    ),
                    article_family_root_baseline_rerank_score=(
                        expansion.root_baseline_rerank_score
                    ),
                    rerank_rank=rerank_rank,
                    rerank_score=rerank_score,
                    selection_reason=(
                        "article_family_sibling_selected:score_order"
                        if selection_rank is not None
                        else "article_family_sibling_dropped:%s" % dropped_reason
                    ),
                    alias_provision_ids=self._alias_provision_ids(hit),
                )
            )

        return sorted(
            [*baseline_reranked, *( (hit.hit, score) for hit, score in selected_expansions)],
            key=lambda pair: (-pair[1], pair[0].document.provision_id),
        )

    def _select_ids(
        self,
        global_ranking: Sequence[str],
        evidence_rankings: Dict[str, List[str]],
        critical_evidence_item_ids: Sequence[str],
    ) -> Tuple[List[str], Dict[str, str]]:
        if self.candidate_selection == "global_top_k":
            selected = list(global_ranking[: self.final_top_k])
            return selected, {
                provision_id: "global_top_k" for provision_id in selected
            }

        critical_ids = [
            evidence_id
            for evidence_id in evidence_rankings
            if evidence_id in set(critical_evidence_item_ids)
        ]
        evidence_members = {
            evidence_id: set(ranking)
            for evidence_id, ranking in evidence_rankings.items()
        }
        selected: List[str] = []
        quota_selected: Set[str] = set()
        for quota_target in range(1, self.per_evidence_min_k + 1):
            for evidence_id in critical_ids:
                current_count = sum(
                    provision_id in evidence_members[evidence_id]
                    for provision_id in selected
                )
                if current_count >= quota_target:
                    continue
                if len(selected) >= self.final_top_k:
                    continue
                provision_id = next(
                    (
                        candidate_id
                        for candidate_id in evidence_rankings[evidence_id]
                        if candidate_id not in selected
                    ),
                    None,
                )
                if provision_id is not None:
                    selected.append(provision_id)
                    quota_selected.add(provision_id)

        for provision_id in global_ranking:
            if len(selected) >= self.final_top_k:
                break
            if provision_id not in selected:
                selected.append(provision_id)

        unsatisfied = [
            evidence_id
            for evidence_id in critical_ids
            if sum(
                provision_id in evidence_members[evidence_id]
                for provision_id in selected
            ) < self.per_evidence_min_k
        ]
        self.last_unsatisfied_critical_evidence_item_ids.extend(unsatisfied)
        reasons: Dict[str, str] = {}
        for provision_id in selected:
            if provision_id in quota_selected:
                satisfied = [
                    evidence_id
                    for evidence_id in critical_ids
                    if provision_id in evidence_members[evidence_id]
                ]
                reasons[provision_id] = "critical_quota:%s" % ",".join(satisfied)
            else:
                reasons[provision_id] = "rank_fusion_fill"
        return selected, reasons

    def _record_first_stage(
        self,
        request: RetrievalRequest,
        hits: Sequence[RetrievalHit],
        retrieval_round: int,
    ) -> None:
        for first_stage_rank, hit in enumerate(hits, start=1):
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="first_stage",
                    source_request_ids=[request.request_id],
                    target_evidence_item_ids=[request.evidence_item_id],
                    first_stage_rank=first_stage_rank,
                    first_stage_score=hit.score,
                    selection_reason="request_top_k",
                )
            )

    def _retrieve_combined_issue(
        self,
        issue_id: str,
        issue_requests: Sequence[RetrievalRequest],
        hits_by_request: Dict[str, List[RetrievalHit]],
        requests_by_id: Dict[str, RetrievalRequest],
        retrieval_round: int,
        critical_evidence_item_ids: Sequence[str],
    ) -> List[CandidateProvision]:
        fused_hits = reciprocal_rank_fusion(
            [hits_by_request[request.request_id] for request in issue_requests],
            k=self.rrf_k,
        )
        for hit in fused_hits[:100]:
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="rrf",
                    source_request_ids=list(hit.source_request_ids),
                    target_evidence_item_ids=self._target_evidence_ids(
                        hit.source_request_ids, requests_by_id
                    ),
                    first_stage_rank=hit.first_stage_rank,
                    fusion_rank=hit.fusion_rank,
                    first_stage_score=hit.first_stage_score,
                    fusion_score=hit.rrf_score,
                    selection_reason="rrf_top_100",
                )
            )

        query_text = " ".join(
            self._request_query_text(request, "rerank_query_text")
            for request in issue_requests
        )
        raw_reranked = self._rerank(
            query_text,
            fused_hits[: self.rerank_pool_k],
        )
        reranked_by_id: Dict[str, Tuple[FusedHit, float, int]] = {}
        for rerank_rank, (hit, rerank_score) in enumerate(raw_reranked, start=1):
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="bge_rerank",
                    source_request_ids=list(hit.source_request_ids),
                    target_evidence_item_ids=self._target_evidence_ids(
                        hit.source_request_ids, requests_by_id
                    ),
                    first_stage_rank=hit.first_stage_rank,
                    fusion_rank=hit.fusion_rank,
                    rerank_rank=rerank_rank,
                    first_stage_score=hit.first_stage_score,
                    fusion_score=hit.rrf_score,
                    rerank_score=rerank_score,
                    selection_reason="rerank_pool",
                )
            )

        reranked_all = self._collapse_legal_text_aliases(raw_reranked)
        for rerank_rank, (hit, rerank_score) in enumerate(reranked_all, start=1):
            reranked_by_id[hit.document.provision_id] = (
                hit,
                rerank_score,
                rerank_rank,
            )
            self._record_alias_collapse(
                hit,
                rerank_score,
                retrieval_round,
                requests_by_id,
            )

        evidence_order = list(
            dict.fromkeys(request.evidence_item_id for request in issue_requests)
        )
        evidence_rankings = {
            evidence_id: [
                hit.document.provision_id
                for hit, _ in reranked_all
                if evidence_id
                in self._target_evidence_ids(hit.source_request_ids, requests_by_id)
            ]
            for evidence_id in evidence_order
        }
        global_ranking = [hit.document.provision_id for hit, _ in reranked_all]
        selected_ids, selection_reasons = self._select_ids(
            global_ranking,
            evidence_rankings,
            critical_evidence_item_ids,
        )

        candidates: List[CandidateProvision] = []
        for selection_rank, provision_id in enumerate(selected_ids, start=1):
            hit, rerank_score, rerank_rank = reranked_by_id[provision_id]
            source_request_ids = list(hit.source_request_ids)
            target_evidence_item_ids = self._target_evidence_ids(
                source_request_ids, requests_by_id
            )
            reason = selection_reasons[provision_id]
            candidate = CandidateProvision(
                provision_id=hit.document.provision_id,
                statute_name=hit.document.statute_name,
                provision_text=hit.document.provision_text,
                issue_id=issue_id,
                source_request_id=source_request_ids[0],
                retrieval_round=retrieval_round,
                first_stage_score=hit.first_stage_score,
                fusion_rank=hit.fusion_rank or 0,
                rerank_score=rerank_score,
                source_request_ids=source_request_ids,
                target_evidence_item_ids=target_evidence_item_ids,
                first_stage_rank=hit.first_stage_rank,
                rerank_rank=rerank_rank,
                selection_rank=selection_rank,
                candidate_stage="selected",
                selection_reason=reason,
                alias_provision_ids=self._alias_provision_ids(hit),
            )
            candidates.append(candidate)
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="selected",
                    source_request_ids=source_request_ids,
                    target_evidence_item_ids=target_evidence_item_ids,
                    first_stage_rank=hit.first_stage_rank,
                    fusion_rank=hit.fusion_rank,
                    rerank_rank=rerank_rank,
                    selection_rank=selection_rank,
                    first_stage_score=hit.first_stage_score,
                    fusion_score=hit.rrf_score,
                    rerank_score=rerank_score,
                    selection_reason=reason,
                    alias_provision_ids=self._alias_provision_ids(hit),
                )
            )
        return candidates

    def _retrieve_per_request(
        self,
        issue_id: str,
        issue_requests: Sequence[RetrievalRequest],
        hits_by_request: Dict[str, List[RetrievalHit]],
        requests_by_id: Dict[str, RetrievalRequest],
        retrieval_round: int,
        critical_evidence_item_ids: Sequence[str],
    ) -> List[CandidateProvision]:
        observations_by_request: Dict[
            str, Dict[str, _RequestRerankObservation]
        ] = {}
        ranked_ids_by_request: Dict[str, List[str]] = {}

        audit_fused_hits = reciprocal_rank_fusion(
            [hits_by_request[request.request_id] for request in issue_requests],
            k=self.rrf_k,
        )
        for hit in audit_fused_hits[:100]:
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="rrf",
                    source_request_ids=list(hit.source_request_ids),
                    target_evidence_item_ids=self._target_evidence_ids(
                        hit.source_request_ids, requests_by_id
                    ),
                    first_stage_rank=hit.first_stage_rank,
                    fusion_rank=hit.fusion_rank,
                    first_stage_score=hit.first_stage_score,
                    fusion_score=hit.rrf_score,
                    selection_reason="audit_issue_rrf_top_100",
                )
            )

        for request in issue_requests:
            request_hits = reciprocal_rank_fusion(
                [hits_by_request[request.request_id]],
                k=self.rrf_k,
            )
            raw_reranked = self._rerank(
                self._request_query_text(request, "rerank_query_text"),
                request_hits[: self.rerank_pool_k],
            )
            observations: Dict[str, _RequestRerankObservation] = {}
            ranked_ids: List[str] = []
            for rerank_rank, (hit, rerank_score) in enumerate(raw_reranked, start=1):
                self.last_stage_records.append(
                    CandidateStageRecord(
                        provision_id=hit.document.provision_id,
                        retrieval_round=retrieval_round,
                        candidate_stage="request_rerank",
                        source_request_ids=[request.request_id],
                        target_evidence_item_ids=[request.evidence_item_id],
                        first_stage_rank=hit.first_stage_rank,
                        fusion_rank=hit.fusion_rank,
                        rerank_rank=rerank_rank,
                        first_stage_score=hit.first_stage_score,
                        fusion_score=hit.rrf_score,
                        rerank_score=rerank_score,
                        selection_reason="request_rerank_pool",
                    )
                )
            reranked = self._collapse_legal_text_aliases(
                self._expand_request_article_family_siblings(
                    request,
                    raw_reranked,
                    retrieval_round,
                )
            )
            for rerank_rank, (hit, rerank_score) in enumerate(reranked, start=1):
                observation = _RequestRerankObservation(
                    hit=hit,
                    rerank_score=rerank_score,
                    rerank_rank=rerank_rank,
                )
                observations[hit.document.provision_id] = observation
                ranked_ids.append(hit.document.provision_id)
                self._record_alias_collapse(
                    hit,
                    rerank_score,
                    retrieval_round,
                    requests_by_id,
                )
            observations_by_request[request.request_id] = observations
            ranked_ids_by_request[request.request_id] = ranked_ids

        evidence_order = list(
            dict.fromkeys(request.evidence_item_id for request in issue_requests)
        )
        alias_groups_by_id = self._alias_groups_by_provision_id(
            [
                observation.hit
                for observations in observations_by_request.values()
                for observation in observations.values()
            ]
        )
        evidence_rankings: Dict[str, List[str]] = {}
        for evidence_id in evidence_order:
            evidence_requests = [
                request
                for request in issue_requests
                if request.evidence_item_id == evidence_id
            ]
            fused = self._rank_fuse_ids(
                [
                    self._collapse_ranked_ids_by_alias(
                        ranked_ids_by_request[request.request_id],
                        alias_groups_by_id,
                    )
                    for request in evidence_requests
                ]
            )
            evidence_rankings[evidence_id] = self._collapse_ranked_ids_by_alias(
                [provision_id for provision_id, _ in fused],
                alias_groups_by_id,
            )
            evidence_fusion_by_id = dict(fused)
            for fusion_rank, provision_id in enumerate(
                evidence_rankings[evidence_id][:100],
                start=1,
            ):
                alias_provision_ids = alias_groups_by_id[provision_id]
                source_request_ids, observations = self._observations_for_aliases(
                    evidence_requests,
                    observations_by_request,
                    alias_provision_ids,
                )
                self.last_stage_records.append(
                    CandidateStageRecord(
                        provision_id=provision_id,
                        retrieval_round=retrieval_round,
                        candidate_stage="evidence_fusion",
                        source_request_ids=source_request_ids,
                        target_evidence_item_ids=[evidence_id],
                        first_stage_rank=self._minimum_first_stage_rank(
                            observations
                        ),
                        fusion_rank=fusion_rank,
                        rerank_rank=min(
                            observation.rerank_rank
                            for observation in observations
                        ),
                        first_stage_score=observations[0].hit.first_stage_score,
                        fusion_score=evidence_fusion_by_id[provision_id],
                        selection_reason="evidence_rank_fusion",
                        alias_provision_ids=alias_provision_ids,
                    )
                )

        issue_fused = self._rank_fuse_ids(
            [evidence_rankings[evidence_id] for evidence_id in evidence_order]
        )
        global_ranking = self._collapse_ranked_ids_by_alias(
            [provision_id for provision_id, _ in issue_fused],
            alias_groups_by_id,
        )
        issue_fusion_scores_by_id = dict(issue_fused)
        issue_fusion_by_id = {
            provision_id: (rank, issue_fusion_scores_by_id[provision_id])
            for rank, provision_id in enumerate(global_ranking, start=1)
        }
        for rerank_rank, provision_id in enumerate(
            global_ranking[: self.rerank_pool_k], start=1
        ):
            alias_provision_ids = alias_groups_by_id[provision_id]
            source_request_ids, observations = self._observations_for_aliases(
                issue_requests,
                observations_by_request,
                alias_provision_ids,
            )
            primary = min(
                observations,
                key=lambda observation: (
                    observation.rerank_rank,
                    observation.hit.document.provision_id,
                ),
            )
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=primary.hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="bge_rerank",
                    source_request_ids=source_request_ids,
                    target_evidence_item_ids=self._target_evidence_ids(
                        source_request_ids, requests_by_id
                    ),
                    first_stage_rank=self._minimum_first_stage_rank(observations),
                    fusion_rank=rerank_rank,
                    rerank_rank=rerank_rank,
                    fusion_score=issue_fusion_scores_by_id[provision_id],
                    selection_reason="issue_rank_fusion_after_request_rerank",
                    alias_provision_ids=alias_provision_ids,
                )
            )
            if len(alias_provision_ids) > 1:
                self._record_alias_collapse(
                    replace(
                        primary.hit,
                        source_request_ids=source_request_ids,
                        alias_provision_ids=alias_provision_ids,
                    ),
                    primary.rerank_score,
                    retrieval_round,
                    requests_by_id,
                )
        selected_ids, selection_reasons = self._select_ids(
            global_ranking,
            evidence_rankings,
            critical_evidence_item_ids,
        )

        candidates: List[CandidateProvision] = []
        for selection_rank, provision_id in enumerate(selected_ids, start=1):
            alias_provision_ids = alias_groups_by_id[provision_id]
            source_request_ids, observations = self._observations_for_aliases(
                issue_requests,
                observations_by_request,
                alias_provision_ids,
            )
            target_evidence_item_ids = self._target_evidence_ids(
                source_request_ids, requests_by_id
            )
            primary = min(
                observations,
                key=lambda observation: (
                    observation.rerank_rank,
                    observation.hit.document.provision_id,
                ),
            )
            fusion_rank, fusion_score = issue_fusion_by_id[provision_id]
            reason = selection_reasons[provision_id]
            candidate = CandidateProvision(
                provision_id=primary.hit.document.provision_id,
                statute_name=primary.hit.document.statute_name,
                provision_text=primary.hit.document.provision_text,
                issue_id=issue_id,
                source_request_id=source_request_ids[0],
                retrieval_round=retrieval_round,
                first_stage_score=primary.hit.first_stage_score,
                fusion_rank=fusion_rank,
                rerank_score=primary.rerank_score,
                source_request_ids=source_request_ids,
                target_evidence_item_ids=target_evidence_item_ids,
                first_stage_rank=self._minimum_first_stage_rank(observations),
                rerank_rank=fusion_rank,
                selection_rank=selection_rank,
                candidate_stage="selected",
                selection_reason=reason,
                alias_provision_ids=alias_provision_ids,
            )
            alias_ids = set(alias_provision_ids)
            self._request_rerank_ranks_by_candidate[
                (issue_id, candidate.provision_id)
            ] = {
                request_id: min(
                    observation.rerank_rank
                    for observation in observations_by_request[request_id].values()
                    if alias_ids.intersection(
                        self._alias_provision_ids(observation.hit)
                    )
                )
                for request_id in source_request_ids
            }
            candidates.append(candidate)
            self.last_stage_records.append(
                CandidateStageRecord(
                    provision_id=primary.hit.document.provision_id,
                    retrieval_round=retrieval_round,
                    candidate_stage="selected",
                    source_request_ids=source_request_ids,
                    target_evidence_item_ids=target_evidence_item_ids,
                    first_stage_rank=candidate.first_stage_rank,
                    fusion_rank=fusion_rank,
                    rerank_rank=fusion_rank,
                    selection_rank=selection_rank,
                    first_stage_score=primary.hit.first_stage_score,
                    fusion_score=fusion_score,
                    rerank_score=primary.rerank_score,
                    selection_reason=reason,
                    alias_provision_ids=alias_provision_ids,
                )
            )
        return candidates

    def retrieve(
        self,
        requests: Sequence[RetrievalRequest],
        retrieval_round: int,
        *,
        critical_evidence_item_ids: Sequence[str] = (),
    ) -> List[CandidateProvision]:
        if retrieval_round <= self._last_retrieval_round:
            self._prior_round_selected_provision_ids = set()
            self._last_retrieval_round = 0
        self.last_stage_records = []
        self.last_unsatisfied_critical_evidence_item_ids = []
        self.last_dedup_removed_count = 0
        self._request_rerank_ranks_by_candidate = {}
        requests_by_id = {request.request_id: request for request in requests}
        if len(requests_by_id) != len(requests):
            raise ValueError("retrieval request IDs must be unique")
        requests_by_issue: Dict[str, List[RetrievalRequest]] = defaultdict(list)
        for request in requests:
            requests_by_issue[request.issue_id].append(request)

        candidates: List[CandidateProvision] = []
        final_top_k = self.final_top_k
        if self.candidate_budget_scope == "per_round":
            self.final_top_k = self.rerank_pool_k
        try:
            for issue_id, issue_requests in sorted(requests_by_issue.items()):
                hits_by_request: Dict[str, List[RetrievalHit]] = {}
                for request in issue_requests:
                    hits = list(self.first_stage.search(self._first_stage_request(request)))
                    hits_by_request[request.request_id] = hits
                    self._record_first_stage(request, hits, retrieval_round)

                if self.rerank_query_mode == "combined_issue":
                    issue_candidates = self._retrieve_combined_issue(
                        issue_id,
                        issue_requests,
                        hits_by_request,
                        requests_by_id,
                        retrieval_round,
                        critical_evidence_item_ids,
                    )
                else:
                    issue_candidates = self._retrieve_per_request(
                        issue_id,
                        issue_requests,
                        hits_by_request,
                        requests_by_id,
                        retrieval_round,
                        critical_evidence_item_ids,
                    )
                candidates.extend(issue_candidates)
        finally:
            self.final_top_k = final_top_k
        if self.candidate_budget_scope == "per_round":
            if (
                self.round_merge_mode == "single_issue_fusion_top_k"
                and retrieval_round > 1
                and len(requests_by_issue) == 1
            ):
                candidates = self._select_single_issue_later_round_candidates(
                    candidates,
                    critical_evidence_item_ids,
                    retrieval_round,
                )
            else:
                candidates = self._select_round_candidates(
                    candidates,
                    critical_evidence_item_ids,
                    retrieval_round,
                    [request.request_id for request in requests],
                )
            self._prior_round_selected_provision_ids.update(
                provision_id
                for candidate in candidates
                for provision_id in self._candidate_provision_ids(candidate)
            )
            self._last_retrieval_round = retrieval_round
        self.last_unsatisfied_critical_evidence_item_ids = list(
            dict.fromkeys(self.last_unsatisfied_critical_evidence_item_ids)
        )
        return candidates
