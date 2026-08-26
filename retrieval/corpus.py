"""Minimal immutable provision corpus abstraction."""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ProvisionDocument:
    provision_id: str
    statute_name: str
    provision_text: str
    source_index: Optional[str] = None


@dataclass(frozen=True)
class ArticleFamilyMember:
    """One deterministic legal-text representative within a source-index family."""

    family_key: str
    document: ProvisionDocument
    alias_provision_ids: Tuple[str, ...]


def legal_text_alias_key(document: ProvisionDocument) -> tuple[str, str]:
    """Return the exact legal-text identity used for snapshot alias collapse.

    The statute hierarchy is part of ``statute_name`` in the normalized corpus,
    so identical body text from different statutes remains distinct.
    """
    return (
        re.sub(r"\s+", " ", unicodedata.normalize("NFC", document.statute_name)).strip(),
        re.sub(r"\s+", " ", unicodedata.normalize("NFC", document.provision_text)).strip(),
    )


class InMemoryProvisionCorpus:
    def __init__(self, documents: Iterable[ProvisionDocument]):
        self._documents: Dict[str, ProvisionDocument] = {}
        for document in documents:
            if not document.provision_id or not document.provision_text:
                raise ValueError("provision_id and provision_text are required")
            if document.provision_id in self._documents:
                raise ValueError("duplicate provision_id: %s" % document.provision_id)
            self._documents[document.provision_id] = document
        # The default retrieval path never needs source-index families. Build
        # this potentially large index only when the opt-in KURE expansion asks.
        self._article_family_members_by_id: Optional[
            Dict[str, ArticleFamilyMember]
        ] = None
        self._article_family_members_by_key: Optional[
            Dict[str, Tuple[ArticleFamilyMember, ...]]
        ] = None

    @property
    def article_family_index_built(self) -> bool:
        return self._article_family_members_by_id is not None

    def _ensure_article_family_index(self) -> None:
        if self._article_family_members_by_id is not None:
            return
        members_by_id: Dict[str, ArticleFamilyMember] = {}
        members_by_key: Dict[str, Tuple[ArticleFamilyMember, ...]] = {}
        aliases_by_family: Dict[
            str, Dict[Tuple[str, str], List[ProvisionDocument]]
        ] = {}
        for document in self._documents.values():
            source_index = document.source_index
            if not isinstance(source_index, str) or not source_index.strip():
                continue
            family_key = source_index.strip()
            aliases_by_family.setdefault(family_key, {}).setdefault(
                legal_text_alias_key(document), []
            ).append(document)
        for family_key, alias_groups in aliases_by_family.items():
            members: List[ArticleFamilyMember] = []
            for aliases in alias_groups.values():
                ordered_aliases = sorted(aliases, key=lambda item: item.provision_id)
                member = ArticleFamilyMember(
                    family_key=family_key,
                    document=ordered_aliases[0],
                    alias_provision_ids=tuple(
                        item.provision_id for item in ordered_aliases
                    ),
                )
                members.append(member)
                for alias in ordered_aliases:
                    members_by_id[alias.provision_id] = member
            members_by_key[family_key] = tuple(
                sorted(members, key=lambda item: item.document.provision_id)
            )
        self._article_family_members_by_id = members_by_id
        self._article_family_members_by_key = members_by_key

    def get(self, provision_id: str) -> Optional[ProvisionDocument]:
        return self._documents.get(provision_id)

    def all(self) -> List[ProvisionDocument]:
        return list(self._documents.values())

    def article_family_members(
        self, provision_id: str
    ) -> List[ArticleFamilyMember]:
        """Return source-index siblings with snapshot aliases already collapsed."""
        self._ensure_article_family_index()
        assert self._article_family_members_by_id is not None
        assert self._article_family_members_by_key is not None
        member = self._article_family_members_by_id.get(provision_id)
        if member is None:
            return []
        return list(self._article_family_members_by_key[member.family_key])

    @classmethod
    def from_jsonl(cls, path: Path) -> "InMemoryProvisionCorpus":
        documents: List[ProvisionDocument] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    documents.append(
                        ProvisionDocument(
                            provision_id=record["provision_id"],
                            statute_name=record["statute_name"],
                            provision_text=record["provision_text"],
                            source_index=(
                                record.get("source_index")
                                if isinstance(record.get("source_index"), str)
                                else None
                            ),
                        )
                    )
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid corpus JSONL at line %d" % line_number) from exc
        return cls(documents)
