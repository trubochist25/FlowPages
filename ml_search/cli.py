from __future__ import annotations

import argparse
import json
import sys

from .catalog import load_catalog
from .config import MODEL_CHOICES, Settings
from .embeddings import E5Embedder, HashingEmbedder
from .index import build_index
from .schemas import SearchFilters, SearchRequest
from .search import SearchEngine


def make_embedder(settings: Settings, backend: str):
    if backend == "hashing":
        return HashingEmbedder()
    return E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
        settings.model_dimension,
    )


def settings_for(args: argparse.Namespace) -> Settings:
    return Settings.from_env(getattr(args, "model", None))


def command_build_index(args: argparse.Namespace) -> int:
    settings = settings_for(args)
    books = load_catalog(settings.catalog_path, settings.import_report_path)
    embedder = make_embedder(settings, args.backend)
    manifest = build_index(
        books,
        embedder,
        settings.index_path,
        settings.manifest_path,
        settings.catalog_path,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def command_search(args: argparse.Namespace) -> int:
    settings = settings_for(args)
    embedder = make_embedder(settings, args.backend)
    engine = SearchEngine.from_settings(settings, embedder)
    filters_data = json.loads(args.filters) if args.filters else {}
    response = engine.search(
        SearchRequest(
            query=args.query,
            filters=SearchFilters(**filters_data),
            limit=args.limit,
            include_debug=args.debug,
        )
    )
    print(response.model_dump_json(indent=2))
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    settings = settings_for(args)
    books = load_catalog(settings.catalog_path, settings.import_report_path)
    from .correction import QueryCorrector
    from .intent import IntentParser

    corrector = QueryCorrector(books)
    corrected, variants = corrector.correct(args.query)
    intent = IntentParser().parse(
        args.query,
        corrected,
        variants,
        taxonomy_query=corrector.intent_query(corrected),
    )
    print(json.dumps(intent.as_dict(), ensure_ascii=False, indent=2))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError(
            "uvicorn is not installed; install ml_search/requirements.txt"
        ) from error
    settings = settings_for(args)
    from .app import create_app

    uvicorn.run(
        create_app(settings),
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FlowPages local ML search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-index", help="Generate book embeddings")
    build.add_argument(
        "--backend", choices=("e5", "hashing"), default="e5"
    )
    build.add_argument(
        "--model", choices=MODEL_CHOICES, help="Embedding model (overrides ML_SEARCH_MODEL)"
    )
    build.set_defaults(handler=command_build_index)

    search = subparsers.add_parser("search", help="Run a search from the console")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--filters", help="JSON object with strict filters")
    search.add_argument("--debug", action="store_true")
    search.add_argument(
        "--backend", choices=("e5", "hashing"), default="e5"
    )
    search.add_argument(
        "--model", choices=MODEL_CHOICES, help="Embedding model (overrides ML_SEARCH_MODEL)"
    )
    search.set_defaults(handler=command_search)

    analyze = subparsers.add_parser(
        "analyze", help="Inspect correction and query intent"
    )
    analyze.add_argument("query")
    analyze.set_defaults(handler=command_analyze)

    serve = subparsers.add_parser("serve", help="Start the local HTTP API")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument(
        "--model", choices=MODEL_CHOICES, help="Embedding model (overrides ML_SEARCH_MODEL)"
    )
    serve.set_defaults(handler=command_serve)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
