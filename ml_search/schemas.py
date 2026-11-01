from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchFilters(BaseModel):
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    authors: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    pages_min: int | None = Field(default=None, ge=1)
    pages_max: int | None = Field(default=None, ge=1)
    year_min: int | None = Field(default=None, ge=0)
    year_max: int | None = Field(default=None, ge=0)
    age_ratings: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    paces: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SearchFilters":
        pairs = (
            ("price", self.price_min, self.price_max),
            ("pages", self.pages_min, self.pages_max),
            ("year", self.year_min, self.year_max),
        )
        for name, minimum, maximum in pairs:
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"{name}_min cannot be greater than {name}_max")
        return self


class RatingSummary(BaseModel):
    value: float = Field(ge=0, le=5)
    count: int = Field(ge=0)


class SearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    sort: Literal[
        "relevance",
        "popularity_desc",
        "price_asc",
        "price_desc",
        "rating_external_desc",
        "rating_local_desc",
        "rating_desc",
    ] = "relevance"
    local_ratings: dict[int, RatingSummary] = Field(default_factory=dict)
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0)] = 0
    include_debug: bool = False


class ScoreBreakdown(BaseModel):
    total: float
    relevance: float
    semantic: float
    residual_semantic: float
    lexical: float
    residual_lexical: float
    metadata: float
    popularity: float
    entity_match: str | None = None


class SearchResult(BaseModel):
    product_id: int
    title: str
    author: str
    price: float
    image: str
    year: int
    pages: int
    genres: list[str]
    moods: list[str]
    pace: str
    age_rating: str
    external_rating: float
    external_rating_count: int
    local_rating: float
    local_rating_count: int
    ranking_rating: float
    score: float
    relevance_score: float = Field(ge=0, le=1)
    explanation: list[str]
    score_breakdown: ScoreBreakdown | None = None


class SearchResponse(BaseModel):
    query: str
    corrected_query: str
    correction_applied: bool
    total: int
    offset: int
    limit: int
    processing_ms: float
    intent: dict
    results: list[SearchResult]
    state: Literal[
        "results",
        "empty_query",
        "invalid_query",
        "no_matches",
        "partial",
    ] = "results"


class Suggestion(BaseModel):
    type: Literal["book", "author", "genre", "phrase"]
    value: str
    label: str
    product_id: int | None = None
    author: str | None = None
    image: str | None = None
    score: float


class SuggestResponse(BaseModel):
    query: str
    corrected_query: str
    suggestions: list[Suggestion]


class RecommendationSignal(BaseModel):
    product_id: int = Field(gt=0)
    kind: Literal["view", "wishlist", "cart", "purchase"]
    age_days: float = Field(default=0, ge=0, le=3650)
    strength: float = Field(default=1, gt=0, le=100)


class RecommendationRequest(BaseModel):
    signals: list[RecommendationSignal] = Field(
        default_factory=list,
        max_length=250,
    )
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    strategy: Literal["balanced", "explore", "similar"] = "balanced"
    anchor_product_id: int | None = Field(default=None, gt=0)
    random_seed: int | None = Field(default=None, ge=0, le=2147483647)
    include_debug: bool = False

    @model_validator(mode="after")
    def validate_similar_anchor(self) -> "RecommendationRequest":
        if self.strategy == "similar" and self.anchor_product_id is None:
            raise ValueError("anchor_product_id is required for similar strategy")
        return self


class RecommendationResult(BaseModel):
    product_id: int
    score: float
    reasons: list[str]
    already_viewed: bool = False
    score_breakdown: dict[str, float] | None = None


class RecommendationResponse(BaseModel):
    results: list[RecommendationResult]
    signals_used: int
    processing_ms: float


AlchemyText = Annotated[str, Field(min_length=1, max_length=120)]
AlchemyIngredientKind = Literal[
    "genre",
    "theme",
    "mood",
    "pace",
    "style",
    "content",
    "audience",
    "freeform",
]


class AlchemyContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AlchemyIngredient(AlchemyContractModel):
    kind: AlchemyIngredientKind
    value: AlchemyText
    weight: float = Field(default=1.0, gt=0, le=1)


class AlchemyNegativeIngredient(AlchemyIngredient):
    mode: Literal["avoid", "exclude"] = "avoid"


class AlchemyAnalyzedIngredient(AlchemyIngredient):
    source: Literal["parser", "user", "anchor"] = "parser"
    confidence: float = Field(default=1.0, ge=0, le=1)
    supported: bool = True


class AlchemyAnalyzedNegativeIngredient(AlchemyNegativeIngredient):
    source: Literal["parser", "user", "anchor"] = "parser"
    confidence: float = Field(default=1.0, ge=0, le=1)
    supported: bool = True


class AlchemyAnchor(AlchemyContractModel):
    product_id: int = Field(gt=0)
    weight: float = Field(default=1.0, gt=0, le=1)
    aspects: list[AlchemyText] = Field(default_factory=list, max_length=5)

    @field_validator("aspects")
    @classmethod
    def validate_unique_aspects(cls, values: list[str]) -> list[str]:
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("anchor aspects must be unique")
        return values


class AlchemyAnalyzedAnchor(AlchemyAnchor):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    author: Annotated[str, Field(max_length=160)] = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: Literal["parser"] = "parser"


class AlchemyFilters(SearchFilters):
    model_config = ConfigDict(extra="forbid")

    in_stock: bool = True


class AlchemyWarning(AlchemyContractModel):
    code: Annotated[str, Field(min_length=1, max_length=64)]
    message: Annotated[str, Field(min_length=1, max_length=300)]


class AlchemyAnalyzeRequest(AlchemyContractModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    locale: Literal["ru-RU", "en-GB"] = "ru-RU"

    @field_validator("query")
    @classmethod
    def validate_meaningful_query(cls, value: str) -> str:
        if not any(character.isalnum() for character in value):
            raise ValueError("query must contain a letter or a digit")
        return value


class AlchemyAnalyzeResponse(AlchemyContractModel):
    query: str
    normalized_query: str
    residual_query: str = ""
    anchors: list[AlchemyAnalyzedAnchor] = Field(default_factory=list, max_length=3)
    positive: list[AlchemyAnalyzedIngredient] = Field(default_factory=list)
    negative: list[AlchemyAnalyzedNegativeIngredient] = Field(default_factory=list)
    filters: AlchemyFilters = Field(default_factory=AlchemyFilters)
    unresolved_fragments: list[AlchemyText] = Field(default_factory=list)
    warnings: list[AlchemyWarning] = Field(default_factory=list)
    processing_ms: float = Field(ge=0)


class AlchemyRecommendRequest(AlchemyContractModel):
    query: str = Field(default="", max_length=500)
    residual_query: str | None = Field(default=None, max_length=500)
    anchors: list[AlchemyAnchor] = Field(default_factory=list, max_length=3)
    positive: list[AlchemyIngredient] = Field(default_factory=list, max_length=20)
    negative: list[AlchemyNegativeIngredient] = Field(
        default_factory=list,
        max_length=20,
    )
    filters: AlchemyFilters = Field(default_factory=AlchemyFilters)
    surprise: float = Field(default=0.35, ge=0, le=1)
    local_ratings: dict[int, RatingSummary] = Field(default_factory=dict)
    limit: int = Field(default=12, ge=6, le=12)
    random_seed: int | None = Field(default=None, ge=0, le=2147483647)
    include_debug: bool = False

    @model_validator(mode="after")
    def validate_recipe(self) -> "AlchemyRecommendRequest":
        if not self.query and not self.anchors and not self.positive:
            raise ValueError(
                "alchemy recipe requires a query, an anchor, or a positive ingredient"
            )
        if (
            self.query
            and not any(character.isalnum() for character in self.query)
            and not self.anchors
            and not self.positive
        ):
            raise ValueError("query must contain a letter or a digit")

        anchor_ids = [anchor.product_id for anchor in self.anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("anchor product IDs must be unique")

        positive_keys = [
            (ingredient.kind, ingredient.value.casefold())
            for ingredient in self.positive
        ]
        negative_keys = [
            (ingredient.kind, ingredient.value.casefold())
            for ingredient in self.negative
        ]
        if len(positive_keys) != len(set(positive_keys)):
            raise ValueError("positive ingredients must be unique")
        if len(negative_keys) != len(set(negative_keys)):
            raise ValueError("negative ingredients must be unique")

        contradictions = sorted(set(positive_keys) & set(negative_keys))
        if contradictions:
            kind, value = contradictions[0]
            raise ValueError(
                f"ingredient cannot be both positive and negative: {kind}:{value}"
            )

        unsupported_exclusions = [
            ingredient.value
            for ingredient in self.negative
            if ingredient.kind == "content" and ingredient.mode == "exclude"
        ]
        if unsupported_exclusions:
            raise ValueError(
                "content ingredients support only avoid mode until verified "
                "content warnings are available"
            )

        return self


class AlchemyRecommendationResult(AlchemyContractModel):
    product_id: int = Field(gt=0)
    score: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    band: Literal["close", "balanced", "bold"]
    matched: list[AlchemyText] = Field(default_factory=list)
    unmet: list[AlchemyText] = Field(default_factory=list)
    relaxations: list[AlchemyText] = Field(default_factory=list)
    reasons: list[AlchemyText] = Field(default_factory=list, min_length=1)
    score_breakdown: dict[str, float] | None = None


class AlchemyRecommendResponse(AlchemyContractModel):
    total: int = Field(ge=0)
    results: list[AlchemyRecommendationResult] = Field(default_factory=list)
    relaxations: list[AlchemyText] = Field(default_factory=list)
    warnings: list[AlchemyWarning] = Field(default_factory=list)
    processing_ms: float = Field(ge=0)
    state: Literal["results", "no_candidates", "partial", "unavailable"] = (
        "results"
    )
