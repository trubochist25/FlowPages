# FlowPages Book Alchemy — technical specification

Status: steps 1–8 complete; private recipe storage and quality signals implemented  
Specification version: 0.8  
Baseline captured: 2026-09-11

## 1. Product decisions

- The primary entry point is a free-form Russian-language request.
- The request is converted into explicit, editable ingredients.
- A recipe may include up to three anchor books.
- Ingredients may be positive, soft-negative (`avoid`), or hard-negative (`exclude`).
- Price, stock, page count, publication year, and age rating remain strict filters.
- A `surprise` control changes semantic distance and diversity, not merely randomness.
- The result reveal uses an expressive but short ritual.
- The first release does not use an external LLM, WebGL, or a conversational chat UI.
- Compatibility percentages are not shown until the score is calibrated.

## 2. First-release user flow

1. The user enters a free-form request.
2. The service extracts editable ingredients and strict constraints.
3. The user confirms, removes, or changes ingredient weights.
4. The user may add up to three anchor books and select aspects to borrow; an
   anchor with no aspects uses the whole book as the similarity reference.
5. The user chooses the degree of surprise.
6. The user starts mixing.
7. Six to twelve books are returned with evidence-based reasons and disclosed compromises.
8. The user may open a result, bookmark it, or add it to the cart.

The initial example is:

> Камерная тайна для дождливого вечера, без мистики и жестокости.

Expected interpretation:

- positive: `загадочная`, `уютная`, `камерная`;
- soft pace preference: `медленный` or `средний`;
- hard exclusion only when backed by structured metadata: `мистика`;
- soft avoidance when the catalogue cannot guarantee absence: `жестокость`.

## 3. Interaction states

```text
idle -> analyzing -> editing -> mixing -> revealing -> ready
                                      \-> degraded
                                      \-> error
```

- `analyzing` extracts ingredients but does not select books yet.
- `editing` is always usable without animation.
- `mixing` lasts at least 2.2 seconds when motion is enabled, so the ritual remains
  legible; reduced-motion mode never adds this decorative delay.
- `revealing` shows the first three results, followed by the remainder.
- `degraded` provides an honest fallback when the ML service is unavailable.
- repeated slider or weight adjustments use a lightweight result reorder instead of the full ritual.
- `prefers-reduced-motion` removes all non-essential motion.

## 4. Draft API contract

### `POST /alchemy/analyze`

Request:

```json
{
  "query": "Камерная тайна для дождливого вечера, без мистики",
  "locale": "ru-RU"
}
```

Response responsibilities:

- preserve the original query;
- return a normalized semantic query;
- return up to three catalogue-backed book anchors found after phrases such as
  `как` and `между`;
- return recognized positive and negative ingredients;
- return strict numeric and catalogue filters;
- return unresolved fragments;
- attach confidence only to parsing, not to book compatibility;
- never turn an unsupported content absence into a guaranteed exclusion.

### `POST /alchemy/recommend`

Draft request:

```json
{
  "query": "камерная тайна для дождливого вечера",
  "anchors": [
    {
      "product_id": 209,
      "weight": 0.7,
      "aspects": ["загадка", "структура"]
    }
  ],
  "positive": [
    {"kind": "mood", "value": "уютная", "weight": 0.8},
    {"kind": "mood", "value": "загадочная", "weight": 1.0}
  ],
  "negative": [
    {"kind": "genre", "value": "мистика", "mode": "exclude"},
    {"kind": "content", "value": "жестокость", "mode": "avoid"}
  ],
  "filters": {
    "pages_max": 450
  },
  "surprise": 0.35,
  "limit": 12
}
```

Each result must contain:

- `product_id`;
- an internal score;
- a calibrated band: `close`, `balanced`, or `bold`;
- matched ingredients;
- unmet soft preferences;
- applied relaxations;
- evidence-based reasons;
- optional debug breakdown that is never enabled on the public page.

## 5. Ranking constraints

The initial tuning hypothesis is:

- 45% free-query semantic similarity;
- 25% anchor-book similarity;
- 20% explicit ingredient match;
- 5% rating and popularity quality signals;
- 5% diversity.

These values are not a public contract. They must be tuned against an alchemy-specific regression set before release.

Rules:

- hard filters are applied before ranking;
- `exclude` removes a candidate only when the property is backed by reliable structured data;
- `avoid` applies a strong penalty but cannot guarantee absence;
- surprise interpolates semantic distance, genre rarity, and MMR diversity;
- surprise must remain deterministic for an unchanged recipe and session seed;
- results must be diversified by author, series, and near-duplicate content;
- impossible recipes return explicit relaxation proposals instead of a silent empty result;
- strict filters are never relaxed automatically.

## 6. Animation scope

The expressive motion layer will use CSS transforms, the Web Animations API, SVG, and a small optional Canvas particle layer.

Included:

- ingredients moving into a vessel;
- ingredient size responding to weight;
- a short composition morph;
- a sequential reveal of the first three results;
- FLIP-based result reordering;
- reduced motion and low-power fallbacks.

Excluded from the first release:

- WebGL;
- fluid-physics simulation;
- looping background motion;
- animation that blocks input or delays a completed response beyond the explicit
  2.2-second minimum duration of the mixing ritual.

## 7. Privacy and analytics boundaries

- Raw query text is not persisted.
- The Python service receives recipe content but no customer or session identifier.
- Analytics stores a structured recipe fingerprint and anonymous event context.
- Public sharing is a separate, explicit user action.
- Debug score breakdowns are never exposed to analytics as a compatibility promise.

## 8. Baseline system state

### Runtime and catalogue

- OpenCart: `3.0.4.2`.
- Active products: `1000 / 1000`.
- Russian descriptions: `1000`.
- Book metadata rows: `1000`.
- Product attributes: `20000`.
- Categories: `28`.
- Authors/manufacturers in MySQL: `530`.
- Missing images: `0`.
- Missing category links: `0`.
- Missing store links: `0`.
- Duplicate Russian titles: `0`.
- Price range: `389–1899 RUB`.
- Page range: `48–1600`.

### ML service and index

- Health: `ok`.
- Model: `intfloat/multilingual-e5-small`.
- Indexed books: `1000`.
- Vector dimension: `384`.
- The current catalogue SHA-256 matches the index manifest:
  `a0a56393fed047e96c00d94b9588338c74a0a07f56d1cd906d1126aaaa835c1a`.
- Existing automated tests: `28 passed` in `6.280s`.

### Resolved pre-existing database drift

At the original step-1 baseline, `tools/book_catalog/verify_catalog_db.php` failed before any alchemy code was added.

- `search_text` differs for all `1000` books. MySQL contains an older profile while `catalog.json` contains the accepted `search-profile-v2.0` text.
- MySQL `embedding` is `NULL` for all `1000` books. The live service uses the external NPZ index, so health and live search remain operational.
- Three stored titles differ from the current catalogue:
  - `BOOK-0051`: `Библия` vs `Священное Писание — Перевод нового мира (увеличенный формат)`;
  - `BOOK-0178`: `Любовь и время холода` vs `Любовь во время чумы`;
  - `BOOK-0419`: `Эйнштейн` vs `Эйнштейн. Его жизнь и его Вселенная`.
- Four publication years differ:
  - `BOOK-0051`: `1200` vs `2022`;
  - `BOOK-0460`: `1956` vs `1961`;
  - `BOOK-0683`: `1968` vs `1998`;
  - `BOOK-0811`: `2001` vs `2015`.

The user subsequently authorized catalogue synchronization. On 2026-09-11,
`tools/book_catalog/apply_catalog_to_opencart.php` synchronized all 1000 books from
`catalog.json`. No manufacturers were created. The post-sync verification result is:

- status: `passed`;
- books checked: `1000`;
- synchronization errors: `0`;
- `embedding` remains `NULL` for all 1000 rows by design; the live service uses the
  validated NPZ index instead;
- all 28 existing ML tests still pass;
- the captured `что-нибудь уютное на вечер` control query keeps the same top-five
  product IDs: `209`, `487`, `881`, `418`, `160`.

The drift listed above is retained as historical baseline evidence and is no longer
an active blocker for alchemy work.

## 9. Captured behavioral baseline

All requests were executed against the live local service on 2026-09-11 with a result limit of five.

### Query: `что-нибудь уютное на вечер`

- Total candidates: `100`.
- Processing time: `419.73 ms`.
- Top results:
  1. `209` — «Убийство Роджера Экройда»;
  2. `487` — «Большая маленькая ложь»;
  3. `881` — «Переключатель»;
  4. `418` — «Пятеро, что ждут тебя на небесах»;
  5. `160` — «Угадай, как сильно я тебя люблю».

This is the primary quality baseline for alchemy: explicit editable ingredients should move books with verified `уютная` mood above merely broad semantic matches.

### Query: `короткий страшный детектив без мистики`

- Total candidates: `80`.
- Processing time: `566.085 ms`.
- The top five include detective and horror results.
- Explanations identify genre, scary mood, suitable page count, and absence of the parsed mystical theme.

This baseline demonstrates that negation already affects explanations but requires a clearer `avoid` versus `exclude` contract.

### Query: `dostoevskiy`

- Corrected query: `достоевский`.
- Total candidates: `9`.
- Processing time: `623.87 ms`.
- The top five are Dostoevsky books and are explained as author matches.

Alchemy must preserve existing correction and entity matching behavior.

### Strict filter-only request

Filters: genre `Детективы`, maximum `300` pages, mood `напряжённая`, pace `быстрый`.

- Total candidates: `42`.
- Processing time: `5.019 ms`.
- The first results satisfy the strict genre and page-count constraints.

Alchemy must reuse the existing strict-filter semantics.

### Similar-to-Dune recommendation

- Anchor: product `598`, «Дюна».
- Seed: `123`.
- First five product IDs: `61`, `81`, `549`, `62`, `209`.
- Titles: «Алхимик», «451° по Фаренгейту», «Еретики Дюны», «1984», «Убийство Роджера Экройда».

This output is deterministic baseline data, not a quality endorsement.

### Cold-start recommendation

- Strategy: `balanced`.
- Seed: `123`.
- First five product IDs: `598`, `57`, `54`, `53`, `55`.
- Titles: «Дюна», «Гарри Поттер и философский камень», «Все закончится на нас», «48 законов власти», «Богатый папа, бедный папа».

Alchemy must not change these existing recommendation endpoints unless explicitly covered by a later migration.

## 10. Step-1 acceptance status

- [x] No Git repository was created.
- [x] No backup was created by Codex at the user's request.
- [x] Existing ML tests were executed and passed.
- [x] Catalogue integrity and database drift were measured.
- [x] ML service health and index/catalogue hash agreement were verified.
- [x] Search, strict-filter, correction, similar, and cold-start baselines were captured.
- [x] Product decisions, first-release boundaries, API direction, animation scope, and privacy boundaries were documented.

Step 2 was completed after the catalogue drift was resolved.

## 11. Step-2 implementation status

Implemented on 2026-09-11:

- strict Pydantic models for analysis requests and responses;
- strict Pydantic models for recipes, anchors, ingredients, filters, warnings,
  recommendation results, and recommendation responses;
- a maximum of three unique anchor books and five unique aspects per anchor;
- recipe validation for duplicate and contradictory ingredients;
- `content:exclude` rejection until verified content-warning metadata exists;
- strict rejection of unknown contract fields;
- catalogue-aware rejection of unknown anchor product IDs;
- `POST /alchemy/analyze` and `POST /alchemy/recommend` routes;
- truthful placeholder responses that explicitly state which later implementation
  step is pending;
- contract and OpenAPI tests in `ml_search/tests/test_alchemy_contract.py`.

Verification:

- `41` automated tests pass;
- Python compilation succeeds for all changed modules;
- both routes are present in the generated OpenAPI 3.1 schema;
- a valid analysis request returns HTTP `200` with
  `analysis_not_implemented`;
- a valid recipe returns HTTP `200` with `ranking_not_implemented`;
- an empty recipe, unknown field, unsupported hard content exclusion, or unknown
  anchor returns HTTP `422`;
- the live service was restarted and reports `status=ok` with 1000 books;
- the existing `dostoevskiy` search regression still corrects to `достоевский`
  and returns «Преступление и наказание» first.

At the end of step 2 both endpoints intentionally returned placeholders. Step 3
replaced the analysis placeholder; recommendation ranking remains reserved for
step 4. Existing search and recommendation behavior remains unchanged.

## 12. Step-3 free-text analysis status

Implemented on 2026-09-11:

- reuse of the existing keyboard-layout correction, transliteration correction,
  title/author protection, and Russian intent parser;
- extraction of genre, theme, mood, pace, style, content, and audience ingredients;
- weights for emphasis (`больше`, `очень`) and soft negative preferences for
  reduction (`меньше`, `поменьше`);
- hard negative ingredients for reliably catalogued fields after `без`, `кроме`,
  and `исключая`;
- automatic downgrade of unverified content exclusions to `avoid`, accompanied by
  an explicit warning;
- exact page, price, publication-year, and age-rating filters only when the user
  states a numeric constraint;
- catalogue-backed recognition of up to three book anchors in phrases such as
  `как Дюна` and `между Дюной и 1984`, including common Russian inflections;
- preservation of the complete corrected text in `normalized_query`, so unknown
  wording is not lost before semantic embedding;
- bounded `unresolved_fragments` for text that was not converted into structured
  controls;
- an honest `limited_locale` response for English until English structured parsing
  is implemented.

The analysis is deterministic and local; it does not call an external LLM. The
future embedding stage receives the whole normalized request, while extracted
ingredients and filters provide editable, explainable controls around it.

Verification:

- `51` automated tests pass, including real-catalogue analysis cases;
- ordinary title searches are not silently converted into book anchors;
- layout correction is applied before ingredient extraction;
- the rouble symbol and written currency forms both produce strict price filters;
- step-2 validation and all existing search/recommendation regressions remain green.

Step 3 is complete. Step 4 may now implement recipe ranking behind
`POST /alchemy/recommend`.

## 13. Step-4 alchemical ranking status

Implemented on 2026-09-11:

- a hybrid ranker combining the complete free-text embedding, weighted anchor-book
  similarity, explicit ingredient support, and catalogue quality signals;
- anchor similarity enriched with verified genre, theme, mood, and pace overlap;
- optional anchor aspects blended into the corresponding anchor signal;
- strict filtering by stock, price, page count, publication year, author, genre,
  mood, pace, and age rating before scoring;
- removal of anchor books from their own recommendation results;
- hard `exclude` behavior for catalogue-backed genre, theme, mood, and pace fields;
- strong but non-removing penalties for `avoid` ingredients;
- safe downgrade and an explicit warning when a hard exclusion is requested for a
  property that is not backed by reliable structured metadata;
- relative handling of `короче` against the weighted page count of the selected
  anchors;
- a deterministic surprise signal combining genre rarity and seeded exploration;
- MMR-style diversification with extra author and series repetition penalties;
- calibrated `close`, `balanced`, and `bold` result bands rather than public
  compatibility percentages;
- evidence-based matched and unmet ingredient lists, concise reasons, and an
  optional internal score breakdown;
- explicit relaxation proposals for impossible recipes without automatically
  weakening any strict constraint;
- support for blended local and external ratings while keeping quality influence
  intentionally small.

The ranking weights remain an internal tuning detail. Missing creative signals are
reweighted among the signals actually present, while quality alone can never turn
an unrelated book into a strong match. The surprise control contributes at most
18% to pre-diversification scoring, so it broadens a recipe rather than replacing
its meaning.

Verification:

- `58` automated tests pass;
- strict filters and supported hard exclusions are never violated;
- `avoid` retains the full candidate pool while lowering matching books;
- anchor books never recommend themselves;
- exact mood ingredients dominate an anchorless recipe;
- the same recipe and seed produce the same order;
- conservative and maximum-surprise runs produce distinct selections;
- impossible price constraints return no books plus relaxation proposals;
- existing search and ordinary recommendation regressions remain green.

Step 4 is complete. The next implementation step can connect the analyzer and
ranker to the storefront ritual and editable ingredient interface.

## 14. Step-5 OpenCart integration status

Implemented on 2026-09-11:

- `alchemyAnalyze()` and `alchemyRecommend()` methods in the existing fail-safe
  local ML client;
- structured client error state for connection failures, invalid responses,
  rejected requests, and FastAPI validation errors without logging recipe text;
- same-origin OpenCart JSON routes:
  - `POST index.php?route=product/alchemy/analyze`;
  - `POST index.php?route=product/alchemy/recommend`;
- a 64 KiB request limit, mandatory JSON content type, POST-only access, no-store
  responses, and `nosniff` response protection;
- server-side normalization and size limits for anchors, aspects, ingredients,
  filters, query length, surprise, and result count;
- a server-owned stable session seed and server-owned local rating summaries;
- forced public `include_debug=false`, regardless of client input;
- no customer ID, session ID, or raw guest recipe persistence;
- anchor enrichment from OpenCart with the current title, author, resized cover,
  and SEO product URL;
- result hydration from OpenCart with current availability, price, special price,
  cover, author, ratings, cart minimum, and product URL;
- preservation of ML bands, matched and unmet ingredients, reasons, warnings, and
  relaxation proposals without exposing the internal score breakdown;
- localized Russian and English user-safe error messages;
- HTTP `400`, `405`, `413`, `415`, `422`, `502`, and `503` error semantics for
  future interface handling.

Verification:

- all changed PHP files pass syntax checks on PHP 5.6, PHP 7.4, and PHP 8.1;
- the live OpenCart analysis route recognizes «Дюна», returns its resized cover
  and SEO URL, extracts three ingredients, and preserves the 400-page limit;
- the live OpenCart recommendation route returns six hydrated product cards with
  prices, covers, bands, and reasons in about 216 ms on the control recipe;
- a client-supplied debug request does not expose `score_breakdown`;
- GET on the analysis route returns `405 method_not_allowed`;
- malformed JSON returns `400 invalid_json`;
- an unknown anchor is propagated as `422 validation_error` with
  `unknown_anchor` detail;
- all `59` Python search, analysis, ranking, and recommendation tests remain green.

Step 5 is complete. No storefront markup or ritual animation is introduced here;
the next step can consume these same-origin endpoints from the FlowPages interface.

## 15. Step-6 functional interface status

Implemented on 2026-09-12 without animation:

- a dedicated `product/alchemy` storefront page in the FlowPages visual language;
- a three-stage flow: describe the desired reading experience, edit the recipe,
  then inspect the selected books;
- three example prompts that launch analysis immediately;
- editable positive and negative ingredients with kind, value, weight, and
  `avoid`/supported `exclude` controls;
- book-anchor search, up to three editable anchors, anchor weights, and up to five
  comma-separated aspects to borrow;
- strict price, page-count, publication-year, age-rating, and stock controls;
- a surprise control whose label explains the current selection mode;
- accessible busy, success, warning, dirty-query, empty, and unavailable-service
  states without artificial response delays;
- keyboard-operable anchor suggestions and visible focus states;
- result cards with calibrated bands, reasons, matched and unmet preferences,
  relaxations, current OpenCart prices, bookmarks, cart actions, and product links;
- same-origin requests only, text-node rendering for service data, and no storage
  of the raw recipe in browser persistence;
- responsive desktop, tablet, and mobile layouts;
- navigation and footer entry points to the laboratory.

The animation layer remains intentionally absent. The markup and state model are
ready for a later expressive ritual without changing the analysis or ranking API.

### Post-step quality correction: anchored comparative recipes

After storefront testing, the control recipe «Как Дюна, но короче и с меньшим
количеством политики» exposed an overconfidence defect: the uncalibrated E5
cosine range made unrelated short books appear close to the anchor, while
`короче` dominated their score.

The ranking now:

- calibrates query, ingredient, negative, and anchor similarities against the
  current catalogue distribution;
- removes comparative scaffolding such as `как <книга>, но...` from the free
  semantic signal when an explicit anchor already represents it;
- gates anchored candidates by both calibrated anchor similarity and genre-family
  affinity, with a controlled relaxation as surprise increases;
- gives the anchor the dominant weight in anchored recipes;
- interprets `меньше политики` and `с меньшим количеством политики` as a soft
  `власть и общество` avoidance ingredient;
- uses semantic evidence for negative ingredients instead of relying only on
  exact metadata text;
- reserves the `close` band for genuinely strong calibrated anchor matches.

At 50% surprise, the live control result now starts with «Еретики Дюны»,
«Пространство Откровения», «Гиперион», «Дело Джен», «День триффидов» and
Star Wars titles; the unrelated how-to, business, art-album, and romance results
from the reported failure no longer enter the twelve-book selection.

## 16. Step-7 expressive ritual status

Implemented on 2026-09-12:

- mixing starts the recommendation request and the visual ritual at the same
  moment; a ready successful response waits only for the 2.2-second ritual
  minimum, while service errors remain immediate;
- current anchors, positive ingredients, and avoidances visibly converge into
  the vessel, with stronger ingredients rendered more prominently;
- the ritual progresses through intention, balance, and catalogue-search phases
  while the request is in flight, then resolves into a completed formula;
- the first three result cards are revealed in a short sequence and all
  remaining cards follow together, keeping the total cascade under 650 ms;
- the ritual is an absolutely positioned overlay inside a viewport-sized
  reserved output area; completion animates only opacity and transforms, so
  removing the ritual does not move the result cards or contribute to CLS;
- repeated mixes replace the previous ritual safely, and errors stop the active
  state immediately while preserving the normal retry path;
- the existing live status region remains the accessible source of truth; the
  decorative chamber is hidden from assistive technology;
- `prefers-reduced-motion` removes token travel, orbiting, liquid motion, smooth
  scrolling, and result reveals while retaining the same functional states;
- the ritual uses CSS and the Web Animations API only—no WebGL, canvas, external
  assets, artificial response delay, or change to the analysis/ranking contract.

Step 7 is complete. The remaining work is product polish and optional quality
signal collection rather than a dependency of the functional alchemy flow.

## 17. Step-8 quality signals status

Implemented on 2026-09-12:

- a separate idempotent installer creates `oc_alchemy_event` without changing
  the OpenCart installer;
- a first-party random anonymous cookie identifies a browser locally; only its
  SHA-256 hash is stored, and neither it nor the OpenCart session identifier is
  sent to the Python service;
- the former session-derived ranking seed is replaced with a deterministic hash
  of the normalized recipe, closing the last session-to-Python correlation path;
- analytics snapshots contain anchors, positive and negative ingredients,
  strict filters, and surprise, but omit both raw and normalized query text;
- recorded events include analysis completion, ingredient additions/removals,
  weight changes, anchor additions/removals, recommendation impressions,
  product opens, wishlists, and carts;
- result events carry selection, product, and position context, allowing quality
  and position-bias analysis without score breakdowns or session identifiers;
- event metadata is allow-listed, event writes are rate-limited, and event rows
  expire after 180 days with opportunistic cleanup;
- `report_alchemy_quality.php` summarizes impressions and downstream actions for a
  configurable 1–365 day window.

The storage, privacy boundary, user flow, and basic quality report have all been
verified against the live OpenCart database. The saved-recipe UI, routes, model
methods, and fresh-install schema were removed on 2026-09-13. An existing
`oc_alchemy_recipe` table is intentionally left untouched to preserve historical
data, but the application no longer reads from or writes to it. Step 8 is complete.

## 18. Step-9 full verification status

Completed on 2026-09-12 against the live 1,000-book catalogue and the real
`intfloat/multilingual-e5-small` model:

- all 77 established search evaluation queries were executed: Hit@1 is 85.71%,
  Hit@3 is 93.51%, Hit@10 is 97.40%, MRR@10 is 0.9026, and nDCG@10 is 0.9201;
- 118 of 120 independently generated Alchemy recipes had at least two of their
  first three results supported by catalogue metadata, a 98.33% acceptance rate;
- all 33 hard-exclusion cases and all 10 strict-filter cases completed with zero
  violations;
- all 12 deliberately contradictory recipes were rejected by the contract;
- five empty/impossible scenarios produced either explained relaxations or an
  explicit empty-state message, with no unexplained blank result;
- every returned product ID, reason, and debug score checked by the evaluator was
  grounded in the loaded catalogue; there were zero grounding failures;
- direct model ranking over the acceptance suite measured 38.31 ms mean,
  53.75 ms p95, and 59.69 ms maximum after model loading;
- 20 live HTTP recommendation requests measured 53.6 ms wall-clock mean,
  60.0 ms p95, and 120.4 ms maximum; service-side p95 was 54.1 ms;
- stopping the exact ML process produced an intentional HTTP 503 from OpenCart
  with the localized `service_unavailable` explanation; the service was then
  restored and its health, model, catalogue size, page, and recommendation route
  were rechecked;
- the Python suite contains 73 passing tests, including reduced-motion, stable
  ritual-layout, strict-exclusion control, and clause-scoped negation contracts;
  relevant PHP files pass syntax checks on PHP 5.6,
  7.4, and 8.1, while the production JavaScript passes syntax validation;
- interactive checks at 360, 390, and 768 CSS-pixel viewports found no horizontal
  overflow; textarea-to-button keyboard flow, Enter activation, result cards,
  the explained strict-empty state, cart updates, and wishlist updates all work;
- no browser JavaScript errors were recorded during the full interaction run.

The browser used for the interactive run could not emulate the operating-system
reduced-motion preference. That branch is therefore covered by source-level
contract tests which verify immediate ritual completion, disabled result-card
animation, and the matching CSS media query.

The verification uncovered and fixed one storefront integration defect: the
custom wishlist link did not expose OpenCart's expected `wishlist-total` target,
so adding a recommendation worked on the server but left the header counter
stale. The header now exposes the standard target and the counter updates live.

The two conservative Alchemy misses were recipes anchored to «Все закончится на
нас» and «Тонкое искусство пофигизма»: only one of the first three results shared
explicit genre, author, or series metadata. This remains above the 90% target,
but is retained in the JSON report as a future ranking-improvement opportunity.

Step 9 acceptance targets are met. The detailed reproducible reports are stored
in `data/ml_search/step9-search-evaluation.json` and
`data/ml_search/step9-alchemy-evaluation.json`.

## 19. Catalogue-style result cards

Updated on 2026-09-13 after visual review of the Alchemy results:

- desktop results now use a three-column vertical catalogue grid with the cover
  as the primary element, followed by author, rating, title, price, cart, and
  wishlist controls;
- match bands remain visible as cover badges and coloured top rules, preserving
  the distinction between precise, balanced, and bold recommendations;
- the duplicated reasons, matched tags, and unmet tags were consolidated into
  exactly one `Matched` field; it combines catalogue-supported matches and useful
  ranking explanations, removes repeated wording, and shows at most four concise
  characteristics;
- the `Fits` and `Does not fit` controls were subsequently removed by product
  decision, along with their text resources, JavaScript, allow-listed event types,
  vote-replacement model method, and feedback metrics in the quality report;
- cart and wishlist actions use the same 10 px corner radius, dimensions, and
  hover transitions as catalogue cards on the home page;
- the grid becomes two columns on tablet and one column on mobile. A live 390 px
  viewport check found no horizontal overflow and exactly one evidence field in
  each of all 12 rendered cards;
- the complete contract suite, JavaScript syntax check, PHP 5.6/7.4/8.1 syntax
  checks, and an error-free browser console all pass.
