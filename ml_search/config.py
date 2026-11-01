from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class ModelProfile:
    key: str
    name: str
    storage_name: str
    dimension: int
    local_model_relative_path: Path


MODEL_PROFILES = {
    "small": ModelProfile(
        key="small",
        name="intfloat/multilingual-e5-small",
        storage_name="multilingual-e5-small",
        dimension=384,
        local_model_relative_path=Path("local-model"),
    ),
}
MODEL_CHOICES = tuple(MODEL_PROFILES)
DEFAULT_MODEL = "small"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of: 1, 0, true, false, yes, no, on, off")


def resolve_model_profile(value: str | None) -> ModelProfile:
    requested = (value or DEFAULT_MODEL).strip().lower()
    aliases = {
        profile.key: profile
        for profile in MODEL_PROFILES.values()
    }
    aliases.update(
        {
            profile.name.lower(): profile
            for profile in MODEL_PROFILES.values()
        }
    )
    aliases.update(
        {
            profile.storage_name.lower(): profile
            for profile in MODEL_PROFILES.values()
        }
    )
    try:
        return aliases[requested]
    except KeyError as error:
        choices = ", ".join(MODEL_CHOICES)
        raise ValueError(
            f"Unsupported ML search model {value!r}; choose one of: {choices}"
        ) from error


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    catalog_path: Path = PROJECT_ROOT / "data" / "book_catalog" / "catalog.json"
    import_report_path: Path = (
        PROJECT_ROOT / "data" / "book_catalog" / "import-report.json"
    )
    data_dir: Path = PROJECT_ROOT / "data" / "ml_search"
    model_key: str = DEFAULT_MODEL
    model_name: str = "intfloat/multilingual-e5-small"
    model_dimension: int = 384
    model_cache_dir: Path = PROJECT_ROOT / "data" / "ml_search" / "model-cache"
    local_model_path: Path = PROJECT_ROOT / "data" / "ml_search" / "local-model"
    index_path: Path = (
        PROJECT_ROOT
        / "data"
        / "ml_search"
        / "indexes"
        / "multilingual-e5-small"
        / "book-index.npz"
    )
    manifest_path: Path = (
        PROJECT_ROOT
        / "data"
        / "ml_search"
        / "indexes"
        / "multilingual-e5-small"
        / "manifest.json"
    )
    host: str = "127.0.0.1"
    port: int = 8765
    batch_size: int = 32
    max_results: int = 50
    fuzzy_title_resolver: bool = False
    multi_vector_reranker: bool = False
    multi_vector_index_path: Path = (
        PROJECT_ROOT / "data" / "ml_search" / "indexes" / "multi-vector-fields.npz"
    )

    @classmethod
    def from_env(cls, model: str | None = None) -> "Settings":
        root = Path(os.getenv("ML_SEARCH_PROJECT_ROOT", PROJECT_ROOT)).resolve()
        data_dir = Path(
            os.getenv("ML_SEARCH_DATA_DIR", root / "data" / "ml_search")
        ).resolve()
        profile = resolve_model_profile(model or os.getenv("ML_SEARCH_MODEL"))
        index_dir = data_dir / "indexes" / profile.storage_name
        return cls(
            project_root=root,
            catalog_path=Path(
                os.getenv(
                    "ML_SEARCH_CATALOG",
                    root / "data" / "book_catalog" / "catalog.json",
                )
            ).resolve(),
            import_report_path=Path(
                os.getenv(
                    "ML_SEARCH_IMPORT_REPORT",
                    root / "data" / "book_catalog" / "import-report.json",
                )
            ).resolve(),
            data_dir=data_dir,
            model_key=profile.key,
            model_name=os.getenv("ML_SEARCH_MODEL_NAME", profile.name),
            model_dimension=profile.dimension,
            model_cache_dir=Path(
                os.getenv("ML_SEARCH_MODEL_CACHE", data_dir / "model-cache")
            ).resolve(),
            local_model_path=Path(
                os.getenv(
                    "ML_SEARCH_LOCAL_MODEL",
                    data_dir / profile.local_model_relative_path,
                )
            ).resolve(),
            index_path=Path(
                os.getenv("ML_SEARCH_INDEX", index_dir / "book-index.npz")
            ).resolve(),
            manifest_path=Path(
                os.getenv("ML_SEARCH_MANIFEST", index_dir / "manifest.json")
            ).resolve(),
            host=os.getenv("ML_SEARCH_HOST", "127.0.0.1"),
            port=int(os.getenv("ML_SEARCH_PORT", "8765")),
            batch_size=int(os.getenv("ML_SEARCH_BATCH_SIZE", "32")),
            max_results=int(os.getenv("ML_SEARCH_MAX_RESULTS", "50")),
            fuzzy_title_resolver=env_flag("ML_SEARCH_FUZZY_TITLE_RESOLVER"),
            multi_vector_reranker=env_flag("ML_SEARCH_MULTI_VECTOR_RERANKER"),
            multi_vector_index_path=Path(
                os.getenv(
                    "ML_SEARCH_MULTI_VECTOR_INDEX",
                    data_dir / "indexes" / "multi-vector-fields.npz",
                )
            ).resolve(),
        )
