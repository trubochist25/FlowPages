from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .config import Settings
from .embeddings import E5Embedder
from .alchemy import AlchemyContractError
from .schemas import (
    AlchemyAnalyzeRequest,
    AlchemyAnalyzeResponse,
    AlchemyRecommendRequest,
    AlchemyRecommendResponse,
    RecommendationRequest,
    RecommendationResponse,
    SearchRequest,
    SearchResponse,
    SuggestResponse,
)
from .search import SearchEngine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        embedder = E5Embedder(
            settings.model_name,
            settings.model_cache_dir,
            settings.batch_size,
            settings.local_model_path,
            settings.model_dimension,
        )
        app.state.engine = SearchEngine.from_settings(settings, embedder)
        yield

    app = FastAPI(
        title="FlowPages Local ML Search",
        version="0.1.0",
        description="Local hybrid semantic search service for the book catalogue.",
        lifespan=lifespan,
    )

    def engine() -> SearchEngine:
        current = getattr(app.state, "engine", None)
        if current is None:
            raise HTTPException(status_code=503, detail="Search engine is not ready")
        return current

    @app.get("/health")
    def health() -> dict:
        current = engine()
        return {
            "status": "ok",
            "model": current.embedder.model_name,
            "model_key": settings.model_key,
            "books": len(current.books),
            "dimension": current.vector_index.vectors.shape[1],
            "fuzzy_title_resolver": settings.fuzzy_title_resolver,
            "multi_vector_reranker": settings.multi_vector_reranker,
        }

    @app.post("/search", response_model=SearchResponse)
    def search(request: SearchRequest) -> SearchResponse:
        return engine().search(request)

    @app.post("/recommend", response_model=RecommendationResponse)
    def recommend(request: RecommendationRequest) -> RecommendationResponse:
        return engine().recommend(request)

    @app.post("/alchemy/analyze", response_model=AlchemyAnalyzeResponse)
    def analyze_alchemy(request: AlchemyAnalyzeRequest) -> AlchemyAnalyzeResponse:
        return engine().analyze_alchemy(request)

    @app.post("/alchemy/recommend", response_model=AlchemyRecommendResponse)
    def recommend_alchemy(
        request: AlchemyRecommendRequest,
    ) -> AlchemyRecommendResponse:
        try:
            return engine().recommend_alchemy(request)
        except AlchemyContractError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @app.get("/suggest", response_model=SuggestResponse)
    def suggest(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=8, ge=1, le=20),
    ) -> SuggestResponse:
        return engine().suggest(q, limit)

    @app.get("/analyze")
    def analyze(q: str = Query(min_length=1, max_length=500)) -> dict:
        return engine().analyze(q).as_dict()

    @app.get("/facets")
    def facets() -> dict:
        return engine().facets()

    return app


app = create_app()
