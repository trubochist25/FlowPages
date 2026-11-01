from __future__ import annotations

import re
from collections import Counter

from .models import Book
from .text import (
    contains_latin,
    cyrillic_to_latin_variants,
    keyboard_layout_to_russian,
    latin_to_cyrillic,
    normalize_text,
    similarity,
    tokenize,
)
from .title_resolver import FuzzyTitleResolver


BASE_VOCABULARY = {
    "автор",
    "без",
    "быстрый",
    "вдумчивый",
    "веселый",
    "грустный",
    "детектив",
    "детективный",
    "длинный",
    "добрый",
    "жуткий",
    "интересный",
    "классика",
    "короткий",
    "книга",
    "легкий",
    "медленный",
    "мистика",
    "мрачный",
    "напряженный",
    "новый",
    "познавательный",
    "приключение",
    "роман",
    "романтический",
    "современный",
    "страшный",
    "триллер",
    "ужасы",
    "фантастика",
    "фэнтези",
}
TRANSLIT_FUNCTION_WORDS = {
    "a": "а",
    "bez": "без",
    "dlya": "для",
    "i": "и",
    "ili": "или",
    "iz": "из",
    "k": "к",
    "na": "на",
    "o": "о",
    "ob": "об",
    "ot": "от",
    "po": "по",
    "pro": "про",
    "s": "с",
    "so": "со",
    "u": "у",
    "v": "в",
    "vo": "во",
}
ENTITY_STOPWORDS = {
    "а", "без", "в", "во", "для", "и", "из", "или", "к", "книга",
    "книги", "на", "о", "об", "от", "по", "про", "роман", "с", "со",
    "the", "у",
}
GRAMMATICAL_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ую",
    "юю",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ый",
    "ий",
    "ой",
    "ом",
    "ем",
    "ах",
    "ях",
    "ам",
    "ям",
    "а",
    "я",
    "ы",
    "и",
    "у",
    "ю",
    "е",
)


class QueryCorrector:
    def __init__(
        self, books: list[Book], enable_fuzzy_title_resolver: bool = False
    ) -> None:
        self.books = books
        self.fuzzy_title_resolver = (
            FuzzyTitleResolver(books) if enable_fuzzy_title_resolver else None
        )
        frequency: Counter[str] = Counter(BASE_VOCABULARY)
        for book in books:
            frequency.update(tokenize(book.title))
            frequency.update(tokenize(book.author))
            for value in (
                *book.genres,
                *book.themes,
                *book.moods,
                book.pace,
                book.series,
            ):
                frequency.update(tokenize(value))
        self.frequency = frequency
        self.vocabulary = tuple(frequency)
        self.by_length: dict[int, tuple[str, ...]] = {}
        self._match_cache: dict[tuple[str, float], str | None] = {}
        self._latin_match_cache: dict[str, str | None] = {}
        for length in {len(word) for word in self.vocabulary}:
            self.by_length[length] = tuple(
                word for word in self.vocabulary if len(word) == length
            )

        latin_aliases: dict[str, Counter[str]] = {}
        for word in self.vocabulary:
            if len(word) < 3 or not re.search(r"[а-яё]", word):
                continue
            for alias in cyrillic_to_latin_variants(word):
                latin_aliases.setdefault(alias, Counter())[word] += frequency[word]
        self._latin_aliases = latin_aliases
        self._latin_alias_keys = tuple(latin_aliases)

        source_aliases: dict[str, list[Book]] = {}
        for book in books:
            if book.source_title_norm:
                source_aliases.setdefault(book.source_title_norm, []).append(book)
        self._source_aliases = source_aliases

    def variants(self, query: str) -> list[str]:
        normalized = normalize_text(query)
        result = [normalized]
        if contains_latin(normalized):
            source_match = self._source_aliases.get(normalized, [])
            result.extend(
                [
                    *(
                        [
                            max(
                                source_match,
                                key=lambda book: book.popularity,
                            ).title_norm
                        ]
                        if source_match
                        else []
                    ),
                    keyboard_layout_to_russian(normalized),
                    latin_to_cyrillic(normalized),
                    latin_to_cyrillic(
                        normalized, h_as_g=True, y_as_i=True
                    ),
                    self._transliterate_with_vocabulary(normalized),
                ]
            )
        return list(dict.fromkeys(value for value in result if value))

    def correct(self, query: str) -> tuple[str, list[str]]:
        variants = self.variants(query)
        if not variants:
            return "", []

        normalized = normalize_text(query)
        # A catalogue vocabulary is suitable for resolving titles and names,
        # but it must not rewrite valid words in a free-form Russian query.
        if not contains_latin(normalized):
            return normalized, [normalized]

        best_variant = max(variants, key=self._variant_score)
        corrected_tokens = [
            self._correct_token(token) for token in tokenize(best_variant)
        ]
        corrected = " ".join(corrected_tokens)
        all_variants = list(dict.fromkeys([*variants, corrected]))
        return corrected, all_variants

    def title_match(self, book: Book, query: str) -> tuple[float, str | None]:
        best = (0.0, None)
        for alias in (book.title_norm, book.source_title_norm):
            score, kind = self._title_alias_match(book, query, alias)
            if score > best[0]:
                best = (score, kind)
        if best[1] is None and self.fuzzy_title_resolver is not None:
            resolved = self.fuzzy_title_resolver.resolve(query)
            if resolved is not None and resolved.catalog_id == book.catalog_id:
                return 0.94, "fuzzy_title"
        return best

    def author_match(self, book: Book, query: str) -> tuple[float, str | None]:
        query_norm = normalize_text(query)
        if not query_norm or not book.author_norm:
            return 0.0, None
        if query_norm == book.author_norm:
            return 0.98, "exact_author"

        query_tokens = tokenize(query_norm)
        author_tokens = tokenize(book.author_norm)
        if self._contains_sequence(query_tokens, author_tokens):
            return 0.92, "author"

        significant = {
            token for token in author_tokens if len(token) >= 4
        }.intersection(query_tokens)
        informative_query = self._informative(query_tokens)
        if significant and len(informative_query) <= 5:
            return 0.9, "author"
        return 0.0, None

    def split_entities(
        self, corrected_query: str
    ) -> tuple[str, list[str], list[str]]:
        """Separate catalogue entities from the text used for preference parsing."""
        query_tokens = tokenize(corrected_query)
        if not query_tokens:
            return "", [], []
        removed: set[str] = set()
        matched_titles: list[str] = []
        matched_authors: list[str] = []
        for book in self.books:
            _, title_kind = self.title_match(book, corrected_query)
            if title_kind:
                matched_titles.append(book.title)
                if title_kind == "fuzzy_title":
                    removed.update(query_tokens)
                    continue
                removed.update(
                    set(query_tokens).intersection(tokenize(book.title_norm))
                )
                removed.update(
                    set(query_tokens).intersection(
                        tokenize(book.source_title_norm)
                    )
                )
                removed.update(
                    set(query_tokens).intersection(tokenize(book.author_norm))
                )
                continue
            _, author_kind = self.author_match(book, corrected_query)
            if author_kind:
                matched_authors.append(book.author)
                removed.update(
                    set(query_tokens).intersection(tokenize(book.author_norm))
                )
        taxonomy_query = " ".join(
            token for token in query_tokens if token not in removed
        )
        return (
            taxonomy_query,
            list(dict.fromkeys(matched_titles)),
            list(dict.fromkeys(matched_authors)),
        )

    def intent_query(self, corrected_query: str) -> str:
        """Backward-compatible entity-free view used by preference parsers."""
        return self.split_entities(corrected_query)[0]

    def _title_alias_match(
        self, book: Book, query: str, alias: str
    ) -> tuple[float, str | None]:
        query_norm = normalize_text(query)
        alias_norm = normalize_text(alias)
        if not query_norm or not alias_norm:
            return 0.0, None
        if query_norm == alias_norm:
            return 1.0, "exact_title"

        query_tokens = tokenize(query_norm)
        alias_tokens = tokenize(alias_norm)
        if len(alias_tokens) == 1:
            if (
                alias_tokens[0] in query_tokens
                and self._has_author_evidence(book, query_tokens)
            ):
                return 0.94, "title"
            return 0.0, None

        informative_alias = self._informative(alias_tokens)
        if (
            len(informative_alias) >= 2
            and self._contains_sequence(query_tokens, alias_tokens)
        ):
            return 0.94, "title"

        common_run = self._longest_common_run(query_tokens, alias_tokens)
        informative_run = self._informative(common_run)
        if len(informative_run) < 2:
            return 0.0, None

        informative_query = self._informative(query_tokens)
        alias_set = set(informative_alias)
        author_set = set(self._informative(tokenize(book.author_norm)))
        leftovers = [
            token for token in informative_query if token not in alias_set
        ]
        if not leftovers or all(token in author_set for token in leftovers):
            return 0.92, "title"
        return 0.0, None

    @staticmethod
    def _contains_sequence(container: list[str], sequence: list[str]) -> bool:
        if not sequence or len(sequence) > len(container):
            return False
        width = len(sequence)
        return any(
            container[index : index + width] == sequence
            for index in range(len(container) - width + 1)
        )

    @staticmethod
    def _longest_common_run(left: list[str], right: list[str]) -> list[str]:
        best: list[str] = []
        for left_index in range(len(left)):
            for right_index in range(len(right)):
                run: list[str] = []
                while (
                    left_index + len(run) < len(left)
                    and right_index + len(run) < len(right)
                    and left[left_index + len(run)] == right[right_index + len(run)]
                ):
                    run.append(left[left_index + len(run)])
                if len(run) > len(best):
                    best = run
        return best

    @staticmethod
    def _informative(tokens: list[str]) -> list[str]:
        return [
            token
            for token in tokens
            if token not in ENTITY_STOPWORDS and len(token) >= 2
        ]

    @staticmethod
    def _has_author_evidence(book: Book, query_tokens: list[str]) -> bool:
        author_tokens = {
            token for token in tokenize(book.author_norm) if len(token) >= 3
        }
        return bool(author_tokens.intersection(query_tokens))

    def _transliterate_with_vocabulary(self, value: str) -> str:
        result: list[str] = []
        for token in tokenize(value):
            if token.isdigit() or re.search(r"[а-яё]", token):
                result.append(token)
                continue
            if token in TRANSLIT_FUNCTION_WORDS:
                result.append(TRANSLIT_FUNCTION_WORDS[token])
                continue
            matched = self._best_latin_alias(token)
            if matched:
                result.append(matched)
                continue
            fallbacks = (
                latin_to_cyrillic(token),
                latin_to_cyrillic(token, h_as_g=True, y_as_i=True),
            )
            result.append(max(fallbacks, key=self._variant_score))
        return " ".join(result)

    def _best_latin_alias(self, token: str) -> str | None:
        if token in self._latin_match_cache:
            return self._latin_match_cache[token]

        alias = token if token in self._latin_aliases else None
        if alias is None:
            threshold = (
                0.9
                if len(token) <= 4
                else 0.84
                if len(token) <= 7
                else 0.8
            )
            best_score = threshold
            for candidate in self._latin_alias_keys:
                if abs(len(candidate) - len(token)) > 2:
                    continue
                score = similarity(token, candidate)
                if score > best_score:
                    alias = candidate
                    best_score = score

        if alias is None:
            self._latin_match_cache[token] = None
            return None
        choices = self._latin_aliases[alias]
        matched = max(
            choices,
            key=lambda word: (choices[word], self.frequency[word], len(word)),
        )
        self._latin_match_cache[token] = matched
        return matched

    def _variant_score(self, value: str) -> float:
        tokens = tokenize(value)
        if not tokens:
            return 0.0
        score = 0.0
        for token in tokens:
            if token in self.frequency:
                score += 2.0 + min(1.0, self.frequency[token] / 25.0)
            elif resemblant := self._best_match(token, threshold=0.72):
                score += similarity(token, resemblant)
            if any("а" <= char <= "я" for char in token):
                score += 0.1
        return score / len(tokens)

    def _correct_token(self, token: str) -> str:
        if token in self.frequency or len(token) < 4 or token.isdigit():
            return token
        threshold = 0.76 if len(token) >= 8 else 0.81
        match = self._best_match(token, threshold=threshold)
        if match and self._looks_like_inflection(token, match):
            return token
        return match or token

    def _best_match(self, token: str, threshold: float) -> str | None:
        cache_key = (token, threshold)
        if cache_key in self._match_cache:
            return self._match_cache[cache_key]
        candidates: list[str] = []
        for length in range(max(1, len(token) - 2), len(token) + 3):
            candidates.extend(self.by_length.get(length, ()))
        best_word: str | None = None
        best_score = threshold
        for candidate in candidates:
            current = similarity(token, candidate)
            if current > best_score:
                best_word = candidate
                best_score = current
            elif current == best_score and best_word is not None:
                if self.frequency[candidate] > self.frequency[best_word]:
                    best_word = candidate
        self._match_cache[cache_key] = best_word
        return best_word

    @staticmethod
    def _looks_like_inflection(left: str, right: str) -> bool:
        def stems(word: str) -> set[str]:
            result = {word}
            for ending in GRAMMATICAL_ENDINGS:
                if word.endswith(ending) and len(word) - len(ending) >= 4:
                    result.add(word[: -len(ending)])
            return result

        return bool(stems(left).intersection(stems(right)))
