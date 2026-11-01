from __future__ import annotations

import re

from .models import SearchIntent, SoftRange
from .text import normalize_text


GENRE_PATTERNS: dict[str, tuple[str, ...]] = {
    "Бизнес и экономика": ("бизнес", "экономик", "финанс", "предприним"),
    "Биографии и мемуары": ("биограф", "мемуар", "реальная история"),
    "Детективы": ("детектив", "расследован", "сыщик"),
    "Детская литература": ("детск", "для ребенка", "для детей"),
    "Здоровье": ("здоров", "медицин", "питание", "фитнес"),
    "Искусство и культура": ("искусств", "культур", "живопис", "музык"),
    "Историческая проза": ("исторический роман", "историческая проза"),
    "История": ("история", "историческ"),
    "Классическая литература": ("классик", "классическ"),
    "Комиксы и манга": ("комикс", "манга", "графический роман"),
    "Компьютеры и технологии": (
        "компьютер",
        "программирован",
        "технолог",
        "айти",
    ),
    "Научно-популярная литература": (
        "научпоп",
        "научно популяр",
        "познавательн",
    ),
    "Подростковая литература": ("подростк", "young adult"),
    "Поэзия": ("поэз", "стих", "поэтическ"),
    "Приключения": ("приключен", "путешеств"),
    "Психология": ("психолог", "поведен"),
    "Религия": ("религи", "духовн", "богослов"),
    "Родительство": ("родитель", "воспитание детей", "материнств"),
    "Романтика": ("романтик", "романтич", "любовн", "про любовь"),
    "Саморазвитие": ("саморазвит", "личный рост", "привычк"),
    "Современная проза": ("современная проза", "современный роман"),
    "Триллеры": ("триллер", "саспенс", "напряженн"),
    "Ужасы": ("ужас", "хоррор", "страшн", "жутк"),
    "Фантастика": ("фантастик", "космос", "киберпанк", "антиутоп"),
    "Философия": ("философ", "смысл жизни", "мировоззрен"),
    "Фэнтези": ("фэнтези", "магия", "магическ", "дракон"),
    "Юмор": ("юмор", "смешн", "комеди"),
}

MOOD_PATTERNS: dict[str, tuple[str, ...]] = {
    "страшная": ("страшн", "жутк", "пугающ"),
    "мрачная": ("мрачн", "темн", "безысход", "страшн"),
    "напряжённая": ("тревожн", "напряженн", "страшн", "саспенс"),
    "драматичная": ("драматич", "драма", "трагич"),
    "атмосферная": ("атмосфер", "погружен"),
    "лёгкая": ("легк", "ненапряж", "отдых"),
    "романтичная": ("романтич", "нежн"),
    "эмоциональная": ("эмоциональн", "трогательн", "до слез"),
    "вдумчивая": ("вдумчив", "философск", "глубок"),
    "интеллектуальная": ("интеллектуальн", "умн", "сложн"),
    "познавательная": ("познавательн", "узнать", "научн"),
    "динамичная": ("динамичн", "экшен", "захватывающ"),
    "приключенческая": ("приключен", "путешеств"),
    "загадочная": ("загадоч", "тайн", "головолом"),
    "волшебная": ("волшебн", "магическ", "сказочн"),
    "меланхоличная": ("меланхол", "грустн", "печальн"),
    "уютная": ("уютн", "добрая", "теплая"),
    "ироничная": ("весел", "смешн", "юмор", "иронич"),
}

PACE_PATTERNS: dict[str, tuple[str, ...]] = {
    "быстрый": ("быстр", "динамичн", "экшен"),
    "средний": ("средний темп",),
    "медленный": ("медленн", "неспешн"),
}

NEGATION_PATTERNS = ("без ", "не ", "кроме ", "исключая ")


class IntentParser:
    def parse(
        self,
        original_query: str,
        corrected_query: str,
        variants: list[str],
        taxonomy_query: str | None = None,
        matched_titles: list[str] | None = None,
        matched_authors: list[str] | None = None,
    ) -> SearchIntent:
        query = normalize_text(corrected_query)
        intent = SearchIntent(
            original_query=original_query,
            normalized_query=normalize_text(original_query),
            corrected_query=query,
            query_variants=variants,
            matched_titles=list(matched_titles or []),
            matched_authors=list(matched_authors or []),
        )
        preference_query = normalize_text(
            query if taxonomy_query is None else taxonomy_query
        )
        intent.taxonomy_query = preference_query
        self._parse_taxonomy(preference_query, intent)
        self._parse_pages(preference_query, intent)
        self._parse_year(preference_query, intent)
        self._parse_age(preference_query, intent)
        intent.residual_query = self._residual_query(preference_query, intent)
        return intent

    def _parse_taxonomy(self, query: str, intent: SearchIntent) -> None:
        for genre, patterns in GENRE_PATTERNS.items():
            for pattern in patterns:
                position = self._pattern_position(query, pattern)
                if position is not None:
                    if self._is_negated(query, position):
                        intent.excluded_genres.add(genre)
                    else:
                        intent.preferred_genres.add(genre)
                    if pattern not in intent.matched_phrases:
                        intent.matched_phrases.append(pattern)
                    break

        for mood, patterns in MOOD_PATTERNS.items():
            for pattern in patterns:
                position = self._pattern_position(query, pattern)
                if position is not None:
                    if self._is_negated(query, position):
                        intent.excluded_moods.add(mood)
                    else:
                        intent.preferred_moods.add(mood)
                    if pattern not in intent.matched_phrases:
                        intent.matched_phrases.append(pattern)
                    break

        for pace, patterns in PACE_PATTERNS.items():
            for pattern in patterns:
                if self._pattern_position(query, pattern) is not None:
                    intent.preferred_paces.add(pace)
                    if pattern not in intent.matched_phrases:
                        intent.matched_phrases.append(pattern)
                    break

        excluded = re.findall(
            r"(?:без|кроме|исключая)\s+([а-яёa-z-]+)",
            query,
        )
        intent.excluded_terms.update(excluded)

    @staticmethod
    def _residual_query(query: str, intent: SearchIntent) -> str:
        """Return free text after removing confidently structured preferences."""
        has_structured = bool(
            intent.matched_phrases
            or intent.excluded_terms
            or intent.pages
            or intent.year
            or intent.age_max is not None
            or intent.matched_titles
            or intent.matched_authors
        )
        if not has_structured:
            return query

        residual = query
        for pattern in sorted(intent.matched_phrases, key=len, reverse=True):
            normalized = normalize_text(pattern)
            if not normalized:
                continue
            suffix = "" if " " in normalized else r"[а-яёa-z-]*"
            residual = re.sub(
                rf"(?<![а-яёa-z]){re.escape(normalized)}{suffix}(?![а-яёa-z])",
                " ",
                residual,
            )

        for term in intent.excluded_terms:
            residual = re.sub(
                rf"(?<![а-яёa-z]){re.escape(normalize_text(term))}[а-яёa-z-]*(?![а-яёa-z])",
                " ",
                residual,
            )

        structured_patterns = (
            r"(?:от\s*)?\d{2,4}\s*(?:-|до)\s*\d{2,4}\s*(?:стр(?:аниц[а-я]*)?)?",
            r"(?:до|не более|максимум|от|не менее|минимум)\s*\d{2,4}\s*(?:стр(?:аниц[а-я]*)?)",
            r"(?:после|новее|до|старше)\s*\d{4}(?:\s*г(?:ода)?)?",
            r"\b(?:0|6|12|16|18)\s*\+",
        )
        for pattern in structured_patterns:
            residual = re.sub(pattern, " ", residual)

        residual = re.sub(
            r"\b(?:хочу|ищу|найди|подбери|посоветуй|книга|книгу|книги|"
            r"что-нибудь|что-то|без|кроме|исключая|не|очень|особенно)\b",
            " ",
            residual,
        )
        return normalize_text(residual).strip(" ,-+")

    @staticmethod
    def _is_negated(query: str, position: int) -> bool:
        prefix = query[max(0, position - 12) : position]
        return any(prefix.endswith(marker) for marker in NEGATION_PATTERNS)

    @staticmethod
    def _pattern_position(query: str, pattern: str) -> int | None:
        normalized = normalize_text(pattern)
        if not normalized:
            return None
        if " " in normalized:
            match = re.search(
                rf"(?<![а-яёa-z]){re.escape(normalized)}(?![а-яёa-z])",
                query,
            )
            return match.start() if match else None

        for match in re.finditer(
            rf"(?<![а-яёa-z]){re.escape(normalized)}[а-яёa-z-]*",
            query,
        ):
            token = match.group(0)
            # "темн" describes darkness, not skin colour.
            if normalized == "темн" and token.startswith("темнокож"):
                continue
            return match.start()
        return None

    @staticmethod
    def _parse_pages(query: str, intent: SearchIntent) -> None:
        between = re.search(
            r"(?:от\s*)?(\d{2,4})\s*(?:-|до)\s*(\d{2,4})\s*(?:стр|страниц)?",
            query,
        )
        if between:
            intent.pages = SoftRange(
                minimum=float(between.group(1)), maximum=float(between.group(2))
            )
            return

        maximum = re.search(
            r"(?:до|не более|максимум)\s*(\d{2,4})\s*(?:стр|страниц)", query
        )
        if maximum:
            intent.pages = SoftRange(maximum=float(maximum.group(1)))
            return

        minimum = re.search(
            r"(?:от|не менее|минимум)\s*(\d{2,4})\s*(?:стр|страниц)", query
        )
        if minimum:
            intent.pages = SoftRange(minimum=float(minimum.group(1)))
            return

        if any(
            phrase in query
            for phrase in ("не слишком длинн", "не длинн", "небольш", "тонк")
        ):
            intent.pages = SoftRange(maximum=300, target=220)
        elif "не коротк" in query:
            intent.pages = SoftRange(minimum=250, target=400)
        elif any(word in query for word in ("коротк", "быстро прочитать")):
            intent.pages = SoftRange(maximum=250, target=180)
        elif any(word in query for word in ("длинн", "большой роман", "эпопея")):
            intent.pages = SoftRange(minimum=450, target=650)

    @staticmethod
    def _parse_year(query: str, intent: SearchIntent) -> None:
        after = re.search(r"(?:после|новее)\s*(\d{4})", query)
        before = re.search(r"(?:до|старше)\s*(\d{4})", query)
        if after:
            intent.year = SoftRange(minimum=float(after.group(1)))
        elif before:
            intent.year = SoftRange(maximum=float(before.group(1)))
        elif any(word in query for word in ("современн", "новинк", "недавн")):
            intent.year = SoftRange(minimum=2000, target=2020)

    @staticmethod
    def _parse_age(query: str, intent: SearchIntent) -> None:
        explicit = re.search(r"\b(0|6|12|16|18)\s*\+", query)
        if explicit:
            intent.age_max = int(explicit.group(1))
        elif any(value in query for value in ("для детей", "ребенк", "детск")):
            intent.age_max = 12
        elif "подростк" in query:
            intent.age_max = 16
