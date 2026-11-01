from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache


LATIN_TO_CYRILLIC = (
    ("shch", "щ"),
    ("sch", "щ"),
    ("yo", "ё"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ph", "ф"),
    ("th", "т"),
    ("ck", "к"),
    ("ts", "ц"),
    ("ch", "ч"),
    ("sh", "ш"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
)
LATIN_SINGLE = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "й",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "й",
    "z": "з",
}
CYRILLIC_TO_LATIN_OPTIONS = {
    "а": ("a",),
    "б": ("b",),
    "в": ("v", "w"),
    "г": ("g", "h"),
    "д": ("d",),
    "е": ("e", "ye"),
    "ж": ("zh", "j"),
    "з": ("z",),
    "и": ("i",),
    "й": ("y", "i", "j"),
    "к": ("k", "c"),
    "л": ("l",),
    "м": ("m",),
    "н": ("n",),
    "о": ("o",),
    "п": ("p",),
    "р": ("r",),
    "с": ("s", "c"),
    "т": ("t",),
    "у": ("u",),
    "ф": ("f", "ph"),
    "х": ("kh", "h"),
    "ц": ("ts", "c"),
    "ч": ("ch",),
    "ш": ("sh",),
    "щ": ("shch", "sch"),
    "ъ": ("",),
    "ы": ("y", "i"),
    "ь": ("",),
    "э": ("e", "eh"),
    "ю": ("yu", "iu", "u"),
    "я": ("ya", "ia"),
}
EN_TO_RU_KEYBOARD = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
    "йцукенгшщзхъфывапролджэячсмитьбю",
)
WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    value = re.sub(r"[‐‑‒–—―]+", "-", value)
    value = re.sub(r"[^0-9a-zа-яё+\-]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def tokenize(value: str) -> list[str]:
    return WORD_RE.findall(normalize_text(value))


def latin_to_cyrillic(
    value: str, *, h_as_g: bool = False, y_as_i: bool = False
) -> str:
    result = normalize_text(value)
    for latin, cyrillic in LATIN_TO_CYRILLIC:
        result = result.replace(latin, cyrillic)
    mapping = dict(LATIN_SINGLE)
    if h_as_g:
        mapping["h"] = "г"
    if y_as_i:
        mapping["y"] = "и"
    return "".join(mapping.get(char, char) for char in result)


@lru_cache(maxsize=8192)
def cyrillic_to_latin_variants(value: str, limit: int = 48) -> tuple[str, ...]:
    """Return common user-entered Latin spellings for Russian text.

    Reverse transliteration is ambiguous: ``ц`` is commonly entered as both
    ``ts`` and ``c``, while ``ы`` may be ``y`` or ``i``.  Generate a bounded
    set of aliases so queries can be matched in Latin space instead of
    committing to one destructive reverse mapping.
    """

    normalized = normalize_text(value)
    variants = [""]
    for char in normalized:
        if char in {" ", "-"}:
            options = (char,)
        else:
            options = CYRILLIC_TO_LATIN_OPTIONS.get(char, (char,))
        expanded: list[str] = []
        seen: set[str] = set()
        for prefix in variants:
            for option in options:
                candidate = prefix + option
                if candidate not in seen:
                    seen.add(candidate)
                    expanded.append(candidate)
                if len(expanded) >= limit:
                    break
            if len(expanded) >= limit:
                break
        variants = expanded
    return tuple(value for value in variants if value)


def keyboard_layout_to_russian(value: str) -> str:
    return normalize_text(value).translate(EN_TO_RU_KEYBOARD)


def contains_latin(value: str) -> bool:
    return bool(re.search(r"[a-z]", value, flags=re.IGNORECASE))


def similarity(left: str, right: str) -> float:
    left = normalize_text(left)
    right = normalize_text(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    try:
        from rapidfuzz.fuzz import ratio

        return ratio(left, right) / 100.0
    except ImportError:
        return SequenceMatcher(None, left, right).ratio()


def token_overlap(query: str, candidate: str) -> float:
    query_tokens = set(tokenize(query))
    candidate_tokens = set(tokenize(candidate))
    if not query_tokens or not candidate_tokens:
        return 0.0
    weighted_matches = sum(
        1.0 if token in candidate_tokens else 0.0 for token in query_tokens
    )
    return weighted_matches / len(query_tokens)


@lru_cache(maxsize=4096)
def char_ngrams(value: str, minimum: int = 3, maximum: int = 5) -> tuple[str, ...]:
    padded = f"  {normalize_text(value)}  "
    grams: list[str] = []
    for size in range(minimum, maximum + 1):
        grams.extend(padded[index : index + size] for index in range(len(padded) - size + 1))
    return tuple(grams)
