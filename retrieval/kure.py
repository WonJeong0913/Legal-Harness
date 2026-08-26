"""Exact-vector retrieval adapter for an externally supplied KURE encoder."""

import math
from typing import Callable, Dict, List, Sequence

from harness.contracts import RetrievalRequest

from .corpus import InMemoryProvisionCorpus
from .types import RetrievalHit


VectorEncoder = Callable[[str], Sequence[float]]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("vectors must be non-empty and have the same dimension")
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class KureExactVectorRetriever:
    """Exact cosine search; model loading stays outside this reproducible layer."""

    def __init__(
        self,
        corpus: InMemoryProvisionCorpus,
        document_vectors: Dict[str, Sequence[float]],
        query_encoder: VectorEncoder,
    ):
        corpus_ids = {document.provision_id for document in corpus.all()}
        if set(document_vectors) != corpus_ids:
            raise ValueError("document_vectors must contain exactly the corpus provision IDs")
        self.corpus = corpus
        self.document_vectors = document_vectors
        self.query_encoder = query_encoder

    article_family_sibling_expansion_capability = "kure_exact"

    def article_family_members(self, provision_id: str):
        return self.corpus.article_family_members(provision_id)

    def search(self, request: RetrievalRequest) -> List[RetrievalHit]:
        query_vector = self.query_encoder(request.query_text)
        hits = [
            RetrievalHit(
                document=document,
                score=_cosine_similarity(query_vector, self.document_vectors[document.provision_id]),
                source_request_id=request.request_id,
            )
            for document in self.corpus.all()
        ]
        return sorted(hits, key=lambda hit: (-hit.score, hit.document.provision_id))[: request.top_k]
