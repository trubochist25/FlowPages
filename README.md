# FlowPages

An OpenCart bookstore prototype with local machine-learning search and recommendations.

## Features
- Semantic search with multilingual E5 embeddings, title and author matching, typo and transliteration handling, and strict filters.
- Multi-vector reranking across plot, annotation, characteristics, and taxonomy.
- AJAX filters, personalized recommendations, and the free-form Book Alchemy flow.
- OpenCart fallback search, friendly URLs, sitemap, robots rules, and breadcrumb structured data.

## Architecture
Browser -> OpenCart (PHP, Twig, MySQL) -> local Python API at 127.0.0.1:8765.

The Python service uses intfloat/multilingual-e5-small (384-dimensional embeddings). OpenCart loads current product details, prices, and stock; the browser does not call Python directly. See ml_search/ARCHITECTURE.md and ml_search/README.md for details.

## Local setup
This repository excludes the local OpenCart configuration, production database, downloaded model weights, and generated indexes.

1. Set up OpenCart with PHP and MySQL and provide a local config.php.
2. In PowerShell, install the Python service and build the base-model index:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\ml_search\install.ps1 -Model small
   ```
3. Start the base-model API:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\ml_search\run.ps1 -Profile legacy -Model small
   ```

The API listens on http://127.0.0.1:8765. Model download requires network access. The selected profile needs fine-tuned model and reranking artifacts that are not included.

## API routes
- POST /search — catalog search and filters
- POST /recommend — personalized and similar-book recommendations
- GET /suggest — title and author suggestions
- GET /analyze — free-query analysis
- GET /facets — filter values
- GET /health — service status
- GET /docs — interactive API documentation

## Licensing and public release
OpenCart core is licensed under GPL-3.0. Bundled dependencies and fonts retain their own license notices. This repository has no top-level license; do not apply MIT without reviewing the upstream code and notices.

Book-cover images, catalog descriptions, and model files may have separate rights. The OpenCart license does not grant permission to redistribute them. Verify their rights or remove/replace affected materials before making this repository public.
