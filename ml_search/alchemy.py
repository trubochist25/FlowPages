from __future__ import annotations

import re
import time
from collections.abc import Iterable, Sequence

from .alchemy_ranking import AlchemyRanker
from .embeddings import Embedder
from .index import VectorIndex
from .intent import GENRE_PATTERNS, MOOD_PATTERNS, PACE_PATTERNS, IntentParser
from .models import Book, SearchIntent
from .schemas import (
    AlchemyAnalyzedAnchor,
    AlchemyAnalyzedIngredient,
    AlchemyAnalyzedNegativeIngredient,
    AlchemyAnalyzeRequest,
    AlchemyAnalyzeResponse,
    AlchemyFilters,
    AlchemyRecommendRequest,
    AlchemyRecommendResponse,
    AlchemyWarning,
)
from .text import normalize_text, tokenize


LETTER_CLASS = "а-яa-z"
NEGATION_QUALIFIER = (
    r"(?:слишком|излишне|чрезмерно|совсем|явно|"
    r"всяк[а-я]*|лишн[а-я]*|выраженн[а-я]*)"
)
HARD_NEGATION = re.compile(
    rf"(?:без|кроме|исключая|не)\s+(?:{NEGATION_QUALIFIER}\s+)?$"
)
SCOPED_HARD_NEGATION = re.compile(
    r"(?:без|кроме|исключая)\s+[^,;.]{1,40}\s+(?:и|или)\s+$"
)
CLAUSE_BOUNDARY = re.compile(r"[,;.!?]+|[\r\n]+")
TOKEN_PATTERN = re.compile(r"[0-9a-zа-я]+", re.IGNORECASE)
REDUCTION = re.compile(
    r"(?:меньше|поменьше|меньшим\s+количеством)\s+"
    r"(?:[а-яa-z-]+\s+)?$"
)
INTENSIFIER = re.compile(
    r"(?:больше|побольше|особенно|очень)\s+(?:[а-яa-z-]+\s+)?$"
)

THEME_PATTERNS: dict[str, tuple[str, ...]] = {
    "расследование и тайны": ("загадк", "тайн", "расследован"),
    "семья и поколения": ("семейн", "семья", "поколен"),
    "власть и общество": ("власт", "общество", "тоталитар", "политик"),
    "космос и открытия": ("космос", "космическ", "открыти"),
    "будущее и технологии": ("будущ", "технолог", "киберпанк"),
    "дружба и верность": ("дружб", "верност"),
    "любовь и отношения": ("отношени", "про любовь"),
    "взросление и поиск себя": ("взрослен", "поиск себя"),
    "магия и сверхъестественное": ("магия", "мистик", "сверхъестеств"),
    "выживание и испытания": ("выживан", "испытан"),
    "смысл жизни и выбор": ("смысл жизни", "жизненный выбор"),
}

EXTRA_MOOD_PATTERNS: dict[str, tuple[str, ...]] = {
    "загадочная": ("загадк",),
    "мистическая": ("мистик", "сверхъестеств"),
}

STYLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "камерная": ("камерн",),
    "короткая": ("коротк", "небольшая книга", "быстро прочитать"),
    "короче": ("короче",),
    "эпическая": ("эпическ", "масштабн", "эпопея"),
    "с литературным языком": ("красивый язык", "литературный язык"),
    "с простым языком": ("простой язык", "легко написан"),
}

CONTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "жестокость": ("жесток",),
    "насилие": ("насили",),
    "смерть": ("смерт",),
    "тяжёлые темы": ("тяжелые темы", "тяжелая тема"),
}

AUDIENCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "для детей": ("для детей", "ребенк", "детск"),
    "для подростков": ("для подростк", "подростк", "young adult"),
    "для взрослых": ("для взрослых", "взрослой аудитории"),
}

ANCHOR_MARKER = re.compile(
    r"(?:как|похоже на|похожую на|похожий на|в духе|по мотивам|смешай)\s+$"
)

PAGE_RANGE = re.compile(
    r"(?:от\s*)?(\d{1,4})\s*(?:-|до)\s*(\d{1,4})\s*(?:стр(?:аниц[а-я]*)?)"
)
PAGE_MAX = re.compile(
    r"(?:до|не более|максимум)\s*(\d{1,4})\s*(?:стр(?:аниц[а-я]*)?)"
)
PAGE_MIN = re.compile(
    r"(?:от|не менее|минимум)\s*(\d{1,4})\s*(?:стр(?:аниц[а-я]*)?)"
)
PRICE_AMOUNT = r"(\d{1,7}(?:decimalpoint\d{1,2})?)"
PRICE_UNIT = r"(?:byn\b|br\b|белорусских рублей|руб(?:лей|ля)?|р\b)"
PRICE_RANGE = re.compile(r"(?:от\s*)?" + PRICE_AMOUNT + r"\s*(?:-|до)\s*" + PRICE_AMOUNT + r"\s*" + PRICE_UNIT)
PRICE_MAX = re.compile(r"(?:до|не дороже|не более|максимум)\s*" + PRICE_AMOUNT + r"\s*" + PRICE_UNIT)
PRICE_MIN = re.compile(r"(?:от|не дешевле|не менее|минимум)\s*" + PRICE_AMOUNT + r"\s*" + PRICE_UNIT)
YEAR_MIN = re.compile(r"(?:после|новее)\s*(\d{4})(?:\s*г(?:ода)?)?")
YEAR_MAX = re.compile(r"(?:до|старше)\s*(\d{4})(?:\s*г(?:ода)?)?")
AGE_RATING = re.compile(r"\b(0|6|12|16|18)\s*\+")


class AlchemyContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AlchemyService:
    """Interprets an alchemy prompt without outsourcing decisions to an LLM."""

    def __init__(
        self,
        known_product_ids: Iterable[int],
        books: Iterable[Book] = (),
        embedder: Embedder | None = None,
        vector_index: VectorIndex | None = None,
    ) -> None:
        self.known_product_ids = frozenset(int(value) for value in known_product_ids)
        self.books = tuple(books)
        self._anchor_aliases = self._build_anchor_aliases(self.books)
        self._catalog_themes = self._build_catalog_themes(self.books)
        self.ranker = (
            AlchemyRanker(self.books, embedder, vector_index)
            if self.books and embedder is not None and vector_index is not None
            else None
        )

    def analyze(
        self,
        request: AlchemyAnalyzeRequest,
        intent: SearchIntent | None = None,
        taxonomy_query: str | None = None,
    ) -> AlchemyAnalyzeResponse:
        started = time.perf_counter()
        warnings: list[AlchemyWarning] = []

        if request.locale == "en-GB":
            normalized = normalize_text(request.query)
            warnings.append(
                AlchemyWarning(
                    code="limited_locale",
                    message=(
                        "Structured extraction currently supports Russian; "
                        "the complete English text remains available for semantic search."
                    ),
                )
            )
            return AlchemyAnalyzeResponse(
                query=request.query,
                normalized_query=normalized,
                residual_query=normalized,
                unresolved_fragments=self._bounded_fragments(normalized),
                warnings=warnings,
                processing_ms=round((time.perf_counter() - started) * 1000, 3),
            )

        if intent is None:
            intent = IntentParser().parse(
                request.query,
                request.query,
                [normalize_text(request.query)],
            )

        query = normalize_text(intent.corrected_query)
        taxonomy = normalize_text(taxonomy_query or query)
        clause_boundaries = self._clause_boundaries(request.query)
        recognized_spans: list[tuple[int, int]] = []

        anchors, anchor_spans, anchors_truncated = self._extract_anchors(query)
        recognized_spans.extend(anchor_spans)
        if anchors_truncated:
            warnings.append(
                AlchemyWarning(
                    code="anchors_truncated",
                    message="Only the first three recognized book anchors were kept.",
                )
            )

        positive: dict[tuple[str, str], tuple[AlchemyAnalyzedIngredient, int]] = {}
        negative: dict[
            tuple[str, str], tuple[AlchemyAnalyzedNegativeIngredient, int]
        ] = {}

        self._add_intent_taxonomy(
            query,
            intent,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        self._add_pattern_group(
            taxonomy,
            "mood",
            EXTRA_MOOD_PATTERNS,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        self._add_pattern_group(
            taxonomy,
            "theme",
            THEME_PATTERNS,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        self._add_catalog_theme_phrases(
            taxonomy,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        self._add_pattern_group(
            taxonomy,
            "style",
            STYLE_PATTERNS,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        content_avoidance = self._add_pattern_group(
            taxonomy,
            "content",
            CONTENT_PATTERNS,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
            hard_exclusion_supported=False,
        )
        self._add_pattern_group(
            taxonomy,
            "audience",
            AUDIENCE_PATTERNS,
            positive,
            negative,
            recognized_spans,
            clause_boundaries,
        )
        if content_avoidance:
            warnings.append(
                AlchemyWarning(
                    code="unverified_content_avoidance",
                    message=(
                        "Content warnings are not verified in the catalogue, so hard "
                        "content exclusions were converted to avoid preferences."
                    ),
                )
            )

        constraint_query = normalize_text(re.sub(
            r"(?<=\d)[.,](?=\d)", "decimalpoint", request.query.replace("₽", " руб")
        ))
        filters, filter_spans = self._extract_strict_filters(constraint_query)
        # Decimal protection must not shift removal spans into the following text.
        filter_spans = [
            (len(constraint_query[:start].replace("decimalpoint", " ")),
             len(constraint_query[:end].replace("decimalpoint", " ")))
            for start, end in filter_spans
        ]
        recognized_spans.extend(filter_spans)

        for key in tuple(positive):
            if key in negative:
                del positive[key]

        positive_values = [
            item
            for item, _ in sorted(positive.values(), key=lambda value: value[1])
        ]
        negative_values = [
            item
            for item, _ in sorted(negative.values(), key=lambda value: value[1])
        ]
        unresolved = self._extract_unresolved(
            query,
            recognized_spans,
            bool(positive_values or negative_values or anchors or filter_spans),
        )
        residual_query = " ".join(unresolved)

        return AlchemyAnalyzeResponse(
            query=request.query,
            normalized_query=query,
            residual_query=residual_query,
            anchors=anchors,
            positive=positive_values,
            negative=negative_values,
            filters=filters,
            unresolved_fragments=unresolved,
            warnings=warnings,
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def recommend(self, request: AlchemyRecommendRequest) -> AlchemyRecommendResponse:
        started = time.perf_counter()
        unknown_anchor_ids = sorted(
            anchor.product_id
            for anchor in request.anchors
            if anchor.product_id not in self.known_product_ids
        )
        if unknown_anchor_ids:
            values = ", ".join(str(value) for value in unknown_anchor_ids)
            raise AlchemyContractError(
                "unknown_anchor",
                f"Unknown anchor product IDs: {values}",
            )

        if self.ranker is not None:
            return self.ranker.recommend(request)

        return AlchemyRecommendResponse(
            total=0,
            warnings=[
                AlchemyWarning(
                    code="ranking_unavailable",
                    message=(
                        "Alchemy ranking requires catalogue vectors and an embedder; "
                        "the recipe contract is valid."
                    ),
                )
            ],
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
            state="unavailable",
        )

    @staticmethod
    def _build_anchor_aliases(
        books: Sequence[Book],
    ) -> tuple[tuple[str, Book], ...]:
        aliases: dict[str, Book] = {}
        for book in sorted(books, key=lambda item: item.popularity, reverse=True):
            for raw_alias in (book.title, book.source_title):
                alias = normalize_text(raw_alias)
                if len(alias) >= 2:
                    aliases.setdefault(alias, book)
        return tuple(sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True))

    @staticmethod
    def _build_catalog_themes(books: Sequence[Book]) -> tuple[str, ...]:
        themes = {
            normalize_text(theme)
            for book in books
            for theme in book.themes
            if " " in normalize_text(theme)
        }
        return tuple(sorted(themes, key=len, reverse=True))

    def _extract_anchors(
        self, query: str
    ) -> tuple[list[AlchemyAnalyzedAnchor], list[tuple[int, int]], bool]:
        between_mode = bool(re.search(r"\bмежду\b", query))
        found: list[tuple[int, int, Book]] = []
        occupied: list[tuple[int, int]] = []
        seen_ids: set[int] = set()

        for alias, book in self._anchor_aliases:
            pattern = self._anchor_pattern(alias)
            for match in pattern.finditer(query):
                prefix = query[max(0, match.start() - 32) : match.start()]
                if not between_mode and not ANCHOR_MARKER.search(prefix):
                    continue
                span = (match.start(), match.end())
                if book.product_id in seen_ids or any(
                    span[0] < other[1] and span[1] > other[0] for other in occupied
                ):
                    continue
                found.append((span[0], span[1], book))
                occupied.append(span)
                seen_ids.add(book.product_id)

        found.sort(key=lambda item: item[0])
        truncated = len(found) > 3
        kept = found[:3]
        anchors = [
            AlchemyAnalyzedAnchor(
                product_id=book.product_id,
                title=book.title,
                author=book.author,
                confidence=0.98,
            )
            for _, _, book in kept
        ]
        spans = [(start, end) for start, end, _ in kept]
        return anchors, spans, truncated

    @staticmethod
    def _anchor_pattern(alias: str) -> re.Pattern[str]:
        escaped = re.escape(alias)
        if " " not in alias and re.fullmatch(r"[а-я]+", alias):
            endings = {
                "а": r"(?:а|ы|е|у|ой|ою)",
                "я": r"(?:я|и|е|ю|ей|ею)",
            }
            ending = endings.get(alias[-1])
            if ending:
                escaped = re.escape(alias[:-1]) + ending
        return re.compile(
            rf"(?<![{LETTER_CLASS}]){escaped}(?![{LETTER_CLASS}])"
        )

    def _add_intent_taxonomy(
        self,
        query: str,
        intent: SearchIntent,
        positive: dict,
        negative: dict,
        spans: list[tuple[int, int]],
        clause_boundaries: Sequence[int],
    ) -> None:
        groups = (
            (
                "genre",
                GENRE_PATTERNS,
                intent.preferred_genres,
                intent.excluded_genres,
            ),
            (
                "mood",
                MOOD_PATTERNS,
                intent.preferred_moods,
                intent.excluded_moods,
            ),
            ("pace", PACE_PATTERNS, intent.preferred_paces, set()),
        )
        for kind, patterns_by_value, preferred, excluded in groups:
            for value in preferred | excluded:
                match = self._first_pattern(query, patterns_by_value[value])
                if match is None:
                    continue
                position, end = match
                forced_mode = "exclude" if value in excluded else None
                self._store_ingredient(
                    query,
                    kind,
                    value,
                    position,
                    positive,
                    negative,
                    forced_mode=forced_mode,
                    clause_boundaries=clause_boundaries,
                )
                spans.append((position, end))

    def _add_pattern_group(
        self,
        query: str,
        kind: str,
        patterns_by_value: dict[str, tuple[str, ...]],
        positive: dict,
        negative: dict,
        spans: list[tuple[int, int]],
        clause_boundaries: Sequence[int],
        hard_exclusion_supported: bool = True,
    ) -> bool:
        downgraded = False
        for value, patterns in patterns_by_value.items():
            match = self._first_pattern(query, patterns)
            if match is None:
                continue
            position, end = match
            mode, _ = self._modifier(query, position, clause_boundaries)
            if mode == "exclude" and not hard_exclusion_supported:
                mode = "avoid"
                downgraded = True
            self._store_ingredient(
                query,
                kind,
                value,
                position,
                positive,
                negative,
                forced_mode=mode,
                clause_boundaries=clause_boundaries,
            )
            spans.append((position, end))
        return downgraded

    def _add_catalog_theme_phrases(
        self,
        query: str,
        positive: dict,
        negative: dict,
        spans: list[tuple[int, int]],
        clause_boundaries: Sequence[int],
    ) -> None:
        for theme in self._catalog_themes:
            match = self._first_pattern(query, (theme,))
            if match is None:
                continue
            position, end = match
            self._store_ingredient(
                query,
                "theme",
                theme,
                position,
                positive,
                negative,
                clause_boundaries=clause_boundaries,
            )
            spans.append((position, end))

    @staticmethod
    def _store_ingredient(
        query: str,
        kind: str,
        value: str,
        position: int,
        positive: dict,
        negative: dict,
        forced_mode: str | None = None,
        clause_boundaries: Sequence[int] = (),
    ) -> None:
        detected_mode, weight = AlchemyService._modifier(
            query, position, clause_boundaries
        )
        mode = forced_mode if forced_mode is not None else detected_mode
        key = (kind, value.casefold())
        if mode in {"avoid", "exclude"}:
            ingredient = AlchemyAnalyzedNegativeIngredient(
                kind=kind,
                value=value,
                weight=weight,
                mode=mode,
                confidence=0.92,
            )
            current = negative.get(key)
            if current is None or ingredient.weight > current[0].weight:
                negative[key] = (ingredient, position)
            return

        ingredient = AlchemyAnalyzedIngredient(
            kind=kind,
            value=value,
            weight=weight,
            confidence=0.9,
        )
        current = positive.get(key)
        if current is None or ingredient.weight > current[0].weight:
            positive[key] = (ingredient, position)

    @staticmethod
    def _modifier(
        query: str,
        position: int,
        clause_boundaries: Sequence[int] = (),
    ) -> tuple[str | None, float]:
        prefix_start = max(0, position - 36)
        target_token = len(TOKEN_PATTERN.findall(query[:position]))
        clause_token = max(
            (boundary for boundary in clause_boundaries if boundary <= target_token),
            default=0,
        )
        if clause_token:
            tokens = list(TOKEN_PATTERN.finditer(query))
            if clause_token < len(tokens):
                prefix_start = max(prefix_start, tokens[clause_token].start())
        prefix = query[prefix_start:position]
        if REDUCTION.search(prefix):
            return "avoid", 0.55
        if HARD_NEGATION.search(prefix) or SCOPED_HARD_NEGATION.search(prefix):
            return "exclude", 1.0
        if INTENSIFIER.search(prefix):
            return None, 1.0
        return None, 0.8

    @staticmethod
    def _clause_boundaries(original_query: str) -> tuple[int, ...]:
        """Return token offsets after punctuation that ends a preference clause."""
        return tuple(
            len(tokenize(original_query[: match.end()]))
            for match in CLAUSE_BOUNDARY.finditer(original_query)
        )

    @staticmethod
    def _first_pattern(
        query: str, patterns: Sequence[str]
    ) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        for pattern in patterns:
            normalized = normalize_text(pattern)
            if not normalized:
                continue
            suffix = "" if " " in normalized else f"[{LETTER_CLASS}-]*"
            match = re.search(
                rf"(?<![{LETTER_CLASS}]){re.escape(normalized)}{suffix}(?![{LETTER_CLASS}])",
                query,
            )
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), match.end())
        return best

    @staticmethod
    def _extract_strict_filters(
        query: str,
    ) -> tuple[AlchemyFilters, list[tuple[int, int]]]:
        values: dict[str, object] = {}
        spans: list[tuple[int, int]] = []

        def range_value(pattern: re.Pattern[str], minimum: str, maximum: str) -> bool:
            match = pattern.search(query)
            if not match:
                return False
            convert = lambda value: float(value.replace("decimalpoint", ".")) if minimum.startswith("price") else int(value)
            values[minimum] = convert(match.group(1))
            values[maximum] = convert(match.group(2))
            spans.append(match.span())
            return True

        def bound_value(pattern: re.Pattern[str], field: str) -> None:
            match = pattern.search(query)
            if match:
                values[field] = float(match.group(1).replace("decimalpoint", ".")) if field.startswith("price") else int(match.group(1))
                spans.append(match.span())

        if not range_value(PAGE_RANGE, "pages_min", "pages_max"):
            bound_value(PAGE_MAX, "pages_max")
            bound_value(PAGE_MIN, "pages_min")
        if not range_value(PRICE_RANGE, "price_min", "price_max"):
            bound_value(PRICE_MAX, "price_max")
            bound_value(PRICE_MIN, "price_min")
        bound_value(YEAR_MIN, "year_min")
        bound_value(YEAR_MAX, "year_max")

        age = AGE_RATING.search(query)
        if age:
            values["age_ratings"] = [f"{age.group(1)}+"]
            spans.append(age.span())

        return AlchemyFilters(**values), spans

    @staticmethod
    def _extract_unresolved(
        query: str,
        spans: Sequence[tuple[int, int]],
        has_structured_result: bool,
    ) -> list[str]:
        if not has_structured_result:
            return AlchemyService._bounded_fragments(query)

        characters = list(query)
        for start, end in spans:
            for index in range(max(0, start), min(len(characters), end)):
                characters[index] = " "
        remainder = "".join(characters)
        remainder = re.sub(
            r"\b(?:хочу|ищу|найди|подбери|посоветуй|книга|книгу|книги|"
            r"что-нибудь|что-то|что|то|как|между|но|без|кроме|исключая|"
            r"больше|побольше|меньше|поменьше|меньшим|количеством|"
            r"очень|особенно|с|со|и|или)\b",
            " ",
            remainder,
        )
        remainder = re.sub(r"\s+", " ", remainder).strip(" ,;.-")
        if len(remainder) < 2:
            return []
        return AlchemyService._bounded_fragments(remainder)

    @staticmethod
    def _bounded_fragments(value: str) -> list[str]:
        value = value.strip()
        if not value:
            return []
        return [value[index : index + 120] for index in range(0, len(value), 120)]


__all__ = ["AlchemyContractError", "AlchemyService"]
