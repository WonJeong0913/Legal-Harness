"""Search adapters for the on-disk KoBLEX BM25 and KURE exact indexes."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from harness.contracts import RetrievalRequest

from .bm25 import baseline_korean_tokenize
from .corpus import InMemoryProvisionCorpus, ProvisionDocument
from .types import RetrievalHit


PARSER_BM25S_TOP_K = 100


def _bm25s_corpus_mapping_sha256(
    rows: Sequence[Tuple[str, ProvisionDocument, str]],
) -> str:
    """Hash the immutable parquet-row-to-normalized-ID mapping in row order."""
    digest = hashlib.sha256()
    for source_index, document, text in rows:
        payload = {
            "source_index": source_index,
            "provision_id": document.provision_id,
            "text": text,
        }
        digest.update(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def load_bm25s_parser_rows(
    statute_parquet_path: Path,
    normalized_corpus_path: Path,
) -> List[Tuple[str, ProvisionDocument, str]]:
    """Load ParSeR text and validate its positional normalized-ID mapping."""
    if not statute_parquet_path.is_file():
        raise FileNotFoundError("ParSeR statute parquet is missing: %s" % statute_parquet_path)
    if not normalized_corpus_path.is_file():
        raise FileNotFoundError("normalized provision corpus is missing: %s" % normalized_corpus_path)
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required for the C02 bm25s corpus") from exc
    table = pq.read_table(
        str(statute_parquet_path), columns=["index", "hierarchy", "content"]
    )
    columns = {
        name: table.column(name).to_pylist()
        for name in ("index", "hierarchy", "content")
    }
    normalized_rows: List[Dict[str, Any]] = []
    with normalized_corpus_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                normalized_rows.append({
                    "provision_id": str(value["provision_id"]),
                    "source_index": str(value["source_index"]),
                    "statute_name": str(value["statute_name"]),
                    "provision_text": str(value["provision_text"]),
                })
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "invalid normalized provision corpus at line %d" % number
                ) from exc
    row_count = len(columns["index"])
    if row_count != len(normalized_rows):
        raise ValueError("ParSeR parquet and normalized corpus row counts differ")
    rows: List[Tuple[str, ProvisionDocument, str]] = []
    for index in range(row_count):
        source_index = str(columns["index"][index])
        hierarchy = str(columns["hierarchy"][index])
        content = str(columns["content"][index])
        normalized = normalized_rows[index]
        if (
            normalized["source_index"] != source_index
            or normalized["statute_name"] != hierarchy
            or normalized["provision_text"] != content
        ):
            raise ValueError(
                "ParSeR parquet row and normalized corpus mapping differ at row %d"
                % index
            )
        rows.append((
            source_index,
            ProvisionDocument(
                provision_id=normalized["provision_id"],
                statute_name=hierarchy,
                provision_text=content,
            ),
            hierarchy + content,
        ))
    return rows


# The SQLite unicode61 tokenizer keeps Korean particles and endings attached to
# nouns (for example, ``운송인의`` and ``인도일로부터``). These endings occur
# frequently in both natural-language questions and statutory prose, so exact
# token matching alone can miss the relevant provision entirely. Keep this
# list deliberately small and deterministic: it is a recall channel, while the
# BGE cross-encoder remains responsible for final Top-k precision.
_KOREAN_QUERY_SUFFIXES = (
    "으로부터",
    "로부터",
    "에서부터",
    "하는가",
    "되는가",
    "있는가",
    "하여야",
    "해야",
    "하는",
    "되는",
    "에게서",
    "에게",
    "된",
    "한",
    "할",
    "으로",
    "에서",
    "부터",
    "까지",
    "로",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "과",
    "와",
)

_QUERY_PREFIX_STOPWORDS = {
    "관련",
    "경우",
    "대한",
    "따라",
    "어느",
    "무엇",
    "위한",
    "인한",
    "해당",
}

_PLANNED_ACTOR_SUFFIXES = ("인", "자", "주", "기관", "위원회")


def _deduplicate(values: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def _korean_prefix_roots(token: str) -> List[str]:
    """Return conservative FTS prefix roots for one normalized token."""
    roots: List[str] = []
    for suffix in _KOREAN_QUERY_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            stem = token[: -len(suffix)]
            roots.append(stem)
            # Legal time expressions commonly compound an event with 일/날,
            # while the statute uses a conjugated verb: 인도일 ↔ 인도한 날.
            if stem.endswith(("일", "날")) and len(stem) >= 3:
                roots.append(stem[:-1])
            break
    return _deduplicate(roots)


def _query_terms_and_prefixes(request: RetrievalRequest) -> tuple[List[str], List[str]]:
    planned_terms = baseline_korean_tokenize(" ".join(request.query_terms))
    query_text_terms = baseline_korean_tokenize(request.query_text)
    focus_text = request.query_text.partition("[원문 맥락]")[0]
    focus_terms = baseline_korean_tokenize(focus_text)
    exact_terms = _deduplicate(planned_terms or query_text_terms)
    prefix_terms: List[str] = []
    for term in query_text_terms:
        prefix_terms.extend(_korean_prefix_roots(term))
    planned_set = set(planned_terms)
    for term in focus_terms:
        if (
            term not in planned_set
            and term not in _QUERY_PREFIX_STOPWORDS
            and 2 <= len(term) <= 4
            and not _korean_prefix_roots(term)
        ):
            prefix_terms.append(term)
    for term in planned_terms:
        if 2 <= len(term) <= 6 and term.endswith(_PLANNED_ACTOR_SUFFIXES):
            prefix_terms.append(term)

    return exact_terms, _deduplicate(term for term in prefix_terms if len(term) >= 2)


class SqliteFts5Bm25Searcher:
    """Read-only BM25 search over the reproducible SQLite FTS5 artifact."""

    def __init__(self, database_path: Path):
        if not database_path.is_file():
            raise FileNotFoundError("BM25 index is missing: %s" % database_path)
        self.database_path = database_path

    def search(self, request: RetrievalRequest) -> List[RetrievalHit]:
        terms, prefix_terms = _query_terms_and_prefixes(request)
        if not terms:
            return []
        # Tokenizer output is restricted to letters and numbers, making each
        # quoted literal safe for FTS5. Prefix literals bridge Korean
        # particles/endings without changing the fixed BM25 -> BGE design.
        # OR implements the recall-first Top-100 stage.
        exact_literals = ['"%s"' % term for term in terms]
        prefix_literals = ['"%s"*' % term for term in prefix_terms]
        match_expression = " OR ".join(_deduplicate(exact_literals + prefix_literals))
        connection = sqlite3.connect("file:%s?mode=ro" % self.database_path, uri=True)
        try:
            rows = connection.execute(
                "SELECT provision_id, statute_name, provision_text, -bm25(provision_fts) AS score "
                "FROM provision_fts WHERE provision_fts MATCH ? "
                "ORDER BY score DESC, provision_id ASC LIMIT ?",
                (match_expression, request.top_k),
            ).fetchall()
            rows = self._merge_statute_hint_hits(
                connection,
                rows,
                request.statute_hints,
                prefix_terms,
                request.top_k,
            )
        finally:
            connection.close()
        return [
            RetrievalHit(
                document=ProvisionDocument(provision_id=provision_id, statute_name=statute_name, provision_text=provision_text),
                score=float(score),
                source_request_id=request.request_id,
            )
            for provision_id, statute_name, provision_text, score in rows
        ]

    @staticmethod
    def _statute_prefix(hint: str) -> str:
        prefix = re.split(r"\s+제?\d+\s*조", hint, maxsplit=1)[0].strip()
        return prefix or hint.strip()

    def _merge_statute_hint_hits(
        self,
        connection: sqlite3.Connection,
        lexical_rows: Sequence[tuple],
        statute_hints: Sequence[str],
        query_prefixes: Sequence[str],
        top_k: int,
    ) -> List[tuple]:
        """Add high-recall hits from an exact statute-name prefix channel.

        The FTS artifact indexes provision text but stores statute names as
        UNINDEXED metadata. A bounded metadata scan lets reliable S1 hints
        contribute candidates without mutating the index.
        """
        if not statute_hints or not query_prefixes:
            return list(lexical_rows)
        hinted_candidates = {}
        for raw_hint in statute_hints:
            statute_prefix = self._statute_prefix(raw_hint)
            if len(statute_prefix) < 2:
                continue
            hinted_rows = connection.execute(
                "SELECT provision_id, statute_name, provision_text "
                "FROM provision_fts WHERE statute_name = ? OR statute_name LIKE ? LIMIT 2000",
                (statute_prefix, statute_prefix + " %"),
            ).fetchall()
            for provision_id, statute_name, provision_text in hinted_rows:
                document_terms = baseline_korean_tokenize(
                    "%s %s" % (statute_name, provision_text)
                )
                overlap = sum(
                    1
                    for query_prefix in query_prefixes
                    if any(term.startswith(query_prefix) for term in document_terms)
                )
                if overlap == 0:
                    continue
                row = (provision_id, statute_name, provision_text, float(overlap))
                previous = hinted_candidates.get(provision_id)
                if previous is None or overlap > float(previous[3]):
                    hinted_candidates[provision_id] = row

        # Keep most of the lexical ranking intact and reserve a bounded 20%
        # quota for the statute-hint recall channel. Previously every hinted
        # row was boosted above BM25, which could evict relevant lexical hits
        # before the BGE reranker saw them.
        hint_quota = min(top_k, max(1, top_k // 5))
        lexical_quota = max(0, top_k - hint_quota)
        selected = list(lexical_rows[:lexical_quota])
        seen = {row[0] for row in selected}
        ranked_hints = sorted(
            hinted_candidates.values(),
            key=lambda row: (-float(row[3]), row[0]),
        )
        for row in ranked_hints:
            if row[0] not in seen:
                selected.append(row)
                seen.add(row[0])
            if len(selected) >= top_k:
                return selected
        for row in lexical_rows[lexical_quota:]:
            if row[0] not in seen:
                selected.append(row)
                seen.add(row[0])
            if len(selected) >= top_k:
                break
        return selected


class Bm25sParSeRFirstStageSearcher:
    """ParSeR-compatible bm25s first stage for the isolated C02 ablation.

    This adapter intentionally does *not* share the harness SQLite BM25
    query expansion, statute-hint channel, or any first-stage ID deduplication.
    It mirrors the released ParSeR retrieval call shape: parquet
    ``hierarchy + content`` corpus text, English-stopword corpus tokenization,
    default query tokenization, and a fixed top-100 retrieval result.
    """

    def __init__(
        self,
        rows: Sequence[Tuple[str, ProvisionDocument, str]],
        *,
        bm25s_module: Optional[Any] = None,
    ):
        if not rows:
            raise ValueError("bm25s corpus must not be empty")
        self.source_indexes = [source_index for source_index, _document, _text in rows]
        self.documents = [document for _source_index, document, _text in rows]
        self.texts = [text for _source_index, _document, text in rows]
        if len(self.documents) != len(set(document.provision_id for document in self.documents)):
            raise ValueError("bm25s corpus provision IDs must be unique")
        if any(not text for text in self.texts):
            raise ValueError("bm25s corpus text must not be empty")
        if bm25s_module is None:
            try:
                import bm25s as bm25s_module
            except ImportError as exc:
                raise RuntimeError(
                    "bm25s is required for the C02 ParSeR first-stage ablation"
                ) from exc
        self._bm25s = bm25s_module
        self.corpus_size = len(self.documents)
        self.corpus_mapping_sha256 = _bm25s_corpus_mapping_sha256(rows)
        corpus_tokens = self._bm25s.tokenize(
            self.texts,
            stopwords="en",
            show_progress=False,
        )
        self._retriever = self._bm25s.BM25()
        self._retriever.index(corpus_tokens, show_progress=False)

    @classmethod
    def from_parquet(
        cls,
        statute_parquet_path: Path,
        normalized_corpus_path: Path,
        *,
        bm25s_module: Optional[Any] = None,
    ) -> "Bm25sParSeRFirstStageSearcher":
        """Load immutable ParSeR text plus the normalized unique-ID mapping.

        The ParSeR parquet ``index`` field is not unique.  The harness keeps
        the one-to-one normalized provision IDs by validating the two source
        files positionally before constructing retrieval hits.
        """
        return cls(
            load_bm25s_parser_rows(statute_parquet_path, normalized_corpus_path),
            bm25s_module=bm25s_module,
        )

    def search(self, request: RetrievalRequest) -> List[RetrievalHit]:
        if request.top_k != PARSER_BM25S_TOP_K:
            raise ValueError(
                "C02 ParSeR bm25s first stage requires top_k=%d" % PARSER_BM25S_TOP_K
            )
        query_tokens = self._bm25s.tokenize([request.query_text], show_progress=False)
        indexes, scores = self._retriever.retrieve(
            query_tokens,
            k=PARSER_BM25S_TOP_K,
            show_progress=False,
        )
        return [
            RetrievalHit(
                document=self.documents[int(index)],
                score=float(score),
                source_request_id=request.request_id,
            )
            for index, score in zip(indexes[0], scores[0])
        ]


class KureExactIndexSearcher:
    """GPU exact cosine search over a normalized KURE vector matrix.

    The full 233,544 x 1,024 float32 matrix is about 0.9 GB and fits
    comfortably on the H200. It is loaded into GPU once at construction, then
    every query is a full matrix-vector product rather than approximate ANN.
    """

    @staticmethod
    def _deterministic_top_k_indexes(scores, provision_id_ranks, top_k):
        """Rank every finite score by score DESC, then provision ID ASC.

        ``torch.topk`` does not define which items it returns when equal scores
        straddle the cutoff. Sorting the complete score vector on CPU is the
        explicit tie-break required for reproducible exact KURE output.
        """
        import numpy as np

        score_array = np.asarray(scores)
        rank_array = np.asarray(provision_id_ranks)
        if score_array.ndim != 1 or rank_array.ndim != 1 or len(score_array) != len(rank_array):
            raise ValueError("KURE scores and provision ID ranks must be equally sized vectors")
        if not np.isfinite(score_array).all():
            raise ValueError("KURE similarity scores must be finite")
        return np.lexsort((rank_array, -score_array))[:top_k]

    def __init__(
        self,
        vectors_path: Path,
        provision_ids_path: Path,
        normalized_corpus_path: Path,
        model_path: Path,
        device: str = "cuda",
    ):
        try:
            import numpy as np
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("install the project GPU retrieval dependencies first") from exc
        if not all(path.is_file() for path in (vectors_path, provision_ids_path, normalized_corpus_path)):
            raise FileNotFoundError("KURE vectors, ID mapping, and normalized corpus are required")
        if not model_path.is_dir():
            raise FileNotFoundError("local KURE model is missing: %s" % model_path)

        vectors = np.load(vectors_path)
        with provision_ids_path.open("r", encoding="utf-8") as handle:
            provision_ids = [line.rstrip("\n") for line in handle]
        if vectors.shape[0] != len(provision_ids):
            raise ValueError("KURE vectors and provision IDs have different lengths")
        if len(set(provision_ids)) != len(provision_ids):
            raise ValueError("KURE provision IDs must be unique")
        corpus = InMemoryProvisionCorpus.from_jsonl(normalized_corpus_path)
        documents = corpus.all()
        documents_by_id: Dict[str, object] = {
            document.provision_id: document for document in documents
        }
        if any(provision_id not in documents_by_id for provision_id in provision_ids):
            raise ValueError("KURE ID mapping references a missing normalized provision")

        self._torch = torch
        self.device = device
        self.model = SentenceTransformer(str(model_path), device=device)
        self.provision_ids = provision_ids
        provision_id_order = np.argsort(np.asarray(provision_ids), kind="stable")
        self._provision_id_ranks = np.empty(len(provision_ids), dtype=np.int64)
        self._provision_id_ranks[provision_id_order] = np.arange(len(provision_ids))
        self.documents_by_id = documents_by_id
        self.vectors = torch.from_numpy(vectors).to(device=device, dtype=torch.float32)

    def search(self, request: RetrievalRequest) -> List[RetrievalHit]:
        query = self.model.encode(
            [request.query_text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        query_tensor = self._torch.as_tensor(query, dtype=self._torch.float32, device=self.device)
        top_k = min(request.top_k, len(self.provision_ids))
        scores = (self.vectors @ query_tensor).detach().cpu().numpy()
        indexes = self._deterministic_top_k_indexes(scores, self._provision_id_ranks, top_k)
        return [
            RetrievalHit(
                document=self.documents_by_id[self.provision_ids[index]],
                score=float(score),
                source_request_id=request.request_id,
            )
            for index, score in ((int(index), scores[index]) for index in indexes)
        ]
