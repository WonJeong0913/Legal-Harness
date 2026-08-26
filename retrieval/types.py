"""Internal ranked-hit types for first-stage retrieval and fusion."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .corpus import ProvisionDocument


@dataclass(frozen=True)
class RetrievalHit:
    document: ProvisionDocument
    score: float
    source_request_id: str


@dataclass(frozen=True)
class FusedHit:
    document: ProvisionDocument
    # Opt-in family siblings did not participate in first-stage/RRF retrieval.
    rrf_score: Optional[float]
    first_stage_score: Optional[float]
    source_request_ids: List[str] = field(default_factory=list)
    source_first_stage_ranks: Dict[str, int] = field(default_factory=dict)
    first_stage_rank: Optional[int] = None
    fusion_rank: Optional[int] = None
    alias_provision_ids: List[str] = field(default_factory=list)
