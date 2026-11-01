from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import Book
from .text import normalize_text, similarity, tokenize


COMMON_QUERY_WORDS = {
    "автор",
    "часть",
    "читать",
    "дайте",
    "история",
    "ищу",
    "книга",
    "книгу",
    "мне",
    "нужна",
    "нужно",
    "помню",
    "посоветуй",
    "почитать",
    "про",
    "роман",
    "хочу",
    "что",
    "нибудь",
}


@dataclass(frozen=True, slots=True)
class ResolvedTitle:
    catalog_id: int
    title: str
    score: float
    margin: float


class FuzzyTitleResolver:
    """Conservative indexed resolver for multiword catalogue titles."""

    def __init__(self, books: list[Book]) -> None:
        self.books = books
        self._title_tokens = [self._informative(book.title) for book in books]
        self._prefix_index: dict[str, set[int]] = defaultdict(set)
        self._cache: dict[str, ResolvedTitle | None] = {}
        for position, tokens in enumerate(self._title_tokens):
            for token in set(tokens):
                self._prefix_index[token[:3]].add(position)

    def resolve(self, query: str) -> ResolvedTitle | None:
        query_norm = normalize_text(query)
        if query_norm in self._cache:
            return self._cache[query_norm]

        query_tokens = self._informative(query_norm)
        if len(query_tokens) < 2:
            self._cache[query_norm] = None
            return None

        candidates: set[int] = set()
        for prefix in {token[:3] for token in query_tokens}:
            candidates.update(self._prefix_index.get(prefix, ()))
        if not candidates:
            self._cache[query_norm] = None
            return None

        scored = sorted(
            (
                self._title_score(query_tokens, self._title_tokens[position]),
                self.books[position].catalog_id,
                self.books[position].title,
            )
            for position in candidates
        )
        first = scored[-1]
        second_score = scored[-2][0] if len(scored) > 1 else 0.0
        margin = first[0] - second_score
        resolved = None
        if (first[0] >= 0.80 and margin >= 0.045) or (
            first[0] >= 0.66 and margin >= 0.12
        ):
            resolved = ResolvedTitle(
                catalog_id=first[1],
                title=first[2],
                score=first[0],
                margin=margin,
            )
        self._cache[query_norm] = resolved
        return resolved

    @staticmethod
    def _informative(value: str) -> list[str]:
        return [
            token
            for token in tokenize(normalize_text(value))
            if len(token) >= 3 and token not in COMMON_QUERY_WORDS
        ]

    @classmethod
    def _title_score(
        cls, query_tokens: list[str], title_tokens: list[str]
    ) -> float:
        if len(query_tokens) < 2 or len(title_tokens) < 2:
            return 0.0
        matched: list[float] = []
        start = 0
        for query_token in query_tokens:
            best_position = -1
            best_score = 0.0
            for position in range(start, len(title_tokens)):
                score = cls._token_score(query_token, title_tokens[position])
                if score > best_score:
                    best_position = position
                    best_score = score
            if best_score >= 0.74:
                matched.append(best_score)
                start = best_position + 1
        if len(matched) < 2:
            return 0.0
        query_coverage = len(matched) / len(query_tokens)
        title_coverage = len(matched) / len(title_tokens)
        quality = sum(matched) / len(matched)
        return quality * (0.68 * query_coverage + 0.32 * title_coverage)

    @staticmethod
    def _token_score(left: str, right: str) -> float:
        if left == right:
            return 1.0
        if min(len(left), len(right)) >= 5:
            prefix_length = max(4, min(len(left), len(right)) - 2)
            if left.startswith(right[:prefix_length]) or right.startswith(
                left[:prefix_length]
            ):
                return similarity(left, right)
        return similarity(left, right) if min(len(left), len(right)) >= 4 else 0.0
