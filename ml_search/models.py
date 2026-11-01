from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Book:
    product_id: int
    catalog_id: int
    title: str
    source_title: str
    author: str
    authors: tuple[str, ...]
    year: int
    pages: int
    genres: tuple[str, ...]
    themes: tuple[str, ...]
    moods: tuple[str, ...]
    pace: str
    age_rating: str
    language: str
    series: str
    price: float
    quantity: int
    popularity: int
    rating: float
    rating_count: int
    annotation: str
    search_text: str
    image: str
    title_norm: str = ""
    source_title_norm: str = ""
    author_norm: str = ""
    searchable_norm: str = ""


@dataclass(slots=True)
class SoftRange:
    minimum: float | None = None
    maximum: float | None = None
    target: float | None = None


@dataclass(slots=True)
class SearchIntent:
    original_query: str
    normalized_query: str
    corrected_query: str
    query_variants: list[str] = field(default_factory=list)
    taxonomy_query: str = ""
    residual_query: str = ""
    matched_titles: list[str] = field(default_factory=list)
    matched_authors: list[str] = field(default_factory=list)
    preferred_genres: set[str] = field(default_factory=set)
    excluded_genres: set[str] = field(default_factory=set)
    preferred_moods: set[str] = field(default_factory=set)
    excluded_moods: set[str] = field(default_factory=set)
    preferred_paces: set[str] = field(default_factory=set)
    excluded_terms: set[str] = field(default_factory=set)
    pages: SoftRange | None = None
    year: SoftRange | None = None
    age_max: int | None = None
    matched_phrases: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "normalized_query": self.normalized_query,
            "corrected_query": self.corrected_query,
            "query_variants": self.query_variants,
            "taxonomy_query": self.taxonomy_query,
            "residual_query": self.residual_query,
            "matched_titles": self.matched_titles,
            "matched_authors": self.matched_authors,
            "preferred_genres": sorted(self.preferred_genres),
            "excluded_genres": sorted(self.excluded_genres),
            "preferred_moods": sorted(self.preferred_moods),
            "excluded_moods": sorted(self.excluded_moods),
            "preferred_paces": sorted(self.preferred_paces),
            "excluded_terms": sorted(self.excluded_terms),
            "pages": (
                {
                    "minimum": self.pages.minimum,
                    "maximum": self.pages.maximum,
                    "target": self.pages.target,
                }
                if self.pages
                else None
            ),
            "year": (
                {
                    "minimum": self.year.minimum,
                    "maximum": self.year.maximum,
                    "target": self.year.target,
                }
                if self.year
                else None
            ),
            "age_max": self.age_max,
            "matched_phrases": self.matched_phrases,
        }
