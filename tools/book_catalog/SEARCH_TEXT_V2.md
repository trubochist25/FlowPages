# SearchText v2

Этот конвейер строит новую версию поисковых профилей рядом с действующим
каталогом. `data/book_catalog/catalog.json` не меняется ни на одном этапе.

## Что считается источником

- исходное описание Open Library;
- машинный перевод, явно связанный с исходным описанием;
- рубрики Open Library;
- ручные fallback-описания;
- 20 вручную проверенных пилотных профилей.

Старые `genres`, `themes`, `mood`, `pace` сохраняются в source pack только для
локального аудита и вообще не передаются ни генератору, ни верификатору. Старая
`annotation` в конвейер не входит. Это исключает закрепление текущих ошибок через
контекст модели.

Каждое содержательное поле профиля содержит `evidence`: `sourceId` и дословный
фрагмент соответствующего источника. Импорт отклоняет неизвестные источники и
цитаты, которых нет в source pack.

## Этапы

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" prepare
```

Текущий бесплатный процесс: профили создаются партиями внутри задачи Codex,
сохраняются как обычный JSON или JSONL и проходят тот же строгий импорт. Внешний
API для этого не нужен. Импорт принимает как JSON-массив объектов, так и JSONL:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\data\book_catalog\search-text-v2\codex-priority-profiles.json" --merge
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" preview-generation
```

`preview-generation` рендерит все уже созданные профили, проверяет структуру,
дословность цитат, длину текста и фактическое число токенов локального E5. Результат
записывается в `generation-preview.json`. Это контроль генерации, но ещё не второй
независимый проход проверки.

### Локальная редакционная сборка 1000 профилей

Основная бесплатная сборка хранится в компактных редакционных JSONL-файлах
`editorial-*.jsonl`. В них находятся читательское описание книги, характерные
детали, темы, тон, темп, выбранные источники и отдельные причины для ручной
проверки. Служебные замечания об источниках допускаются только в
`reviewReasons`; в читательский `description` они не попадают.

Финальный редакционный проход воспроизводим и идемпотентен:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\finalize_search_text_v2_editorial.py"
```

Независимые смысловые проверки хранятся отдельно в
`semantic-review-*.jsonl`, чтобы редакторы могли работать параллельно без
конфликтов. Перед применением их можно проверить без записи:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\apply_search_text_v2_semantic_reviews.py" --check
```

`finalize_search_text_v2_editorial.py` сам накладывает эти решения последним
слоем. Для `accept` и `rewrite` он заменяет всю карточку и снимает
`needsReview`; для `unresolved` применяет консервативную проверенную карточку,
но сохраняет книгу в очереди проверки. Короткие проверенные выдержки
добавляются в `manual-sources.json`. Поэтому после
финализатора нужно обновить source pack:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" prepare
```

Затем компактные записи проверяются и компилируются в полную схему с
дословными evidence-цитатами:

```powershell
$editorial = @(
  ".\data\book_catalog\search-text-v2\editorial-001-250.jsonl",
  ".\data\book_catalog\search-text-v2\editorial-154-203.jsonl",
  ".\data\book_catalog\search-text-v2\editorial-251-500.jsonl",
  ".\data\book_catalog\search-text-v2\editorial-501-750.jsonl",
  ".\data\book_catalog\search-text-v2\editorial-751-1000.jsonl"
)

& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\audit_search_text_v2_editorial.py" @editorial
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\compile_search_text_v2_editorial.py" @editorial --output ".\data\book_catalog\search-text-v2\editorial-profiles.jsonl"
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\data\book_catalog\search-text-v2\editorial-profiles.jsonl" --merge
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" preview-generation
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\qa_search_text_v2_generation.py"
```

`hardValid` означает, что схема, ссылки на источники, дословность цитат,
ограничения длины, запрещённые рекламные или спойлерные формулировки и лимит
токенизатора прошли проверку. Это не означает автоматического доказательства
каждого перефразированного сюжетного утверждения. Известные пробелы источников
сохраняются через `needsReview` и перечисляются в
`generation-quality-report.json`. Лексический аудит в `editorial-audit.json`
используется как консервативный список кандидатов: он намеренно переоценивает
риск для нормального русского пересказа и не заменяет смысловую проверку.

Для воспроизводимого преобразования двух уже проверенных наборов используются
отдельные команды:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" export-pilot-profiles --exclude-id 10
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\data\book_catalog\search-text-v2\curated-pilot-profiles.jsonl" --merge
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" export-manual-profiles --exclude-id 546
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\data\book_catalog\search-text-v2\curated-manual-profiles.jsonl" --merge
```

`source-audit.json` отдельно перечисляет книги с коротким или единственным
содержательным источником. Дополнительные выдержки можно собрать сначала для
самых слабых карточек, а затем пересобрать source pack:

```powershell
node ".\tools\book_catalog\collect_search_text_v2_sources.mjs" --scope thin
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" prepare
```

Точечный сбор для редакционной партии задаётся списком идентификаторов:

```powershell
node ".\tools\book_catalog\collect_search_text_v2_sources.mjs" --catalog-ids "17,34,35" --providers "wikipedia-ru,wikipedia-en"
```

Режимы `--scope thin|single|all` означают соответственно короткие исходные
описания, все карточки без второго независимого источника или весь каталог.
Коллектор поддерживает Wikipedia на русском и английском и Google Books; любой
результат остаётся `external_unverified` до проверки генератором и верификатором.
Для каждого сервиса работает отдельная последовательная очередь, чтобы не
создавать всплесков запросов и не получать массовые ответы `429`.
Сводка текущей версии matcher-а сохраняется в `source-collection-report.json`;
старые записи кэша считаются `stale` и в source pack не попадают.

Если генератор или верификатор отклонил профиль из-за недостатка данных,
проверенную вручную выдержку можно добавить в
`data/book_catalog/search-text-v2/manual-sources.json`:

```json
[
  {
    "catalogId": 66,
    "sources": [
      {
        "sourceId": "manual-publisher",
        "language": "ru",
        "url": "https://example.org/book",
        "text": "Дословная проверенная выдержка источника."
      }
    ]
  }
]
```

После этого выполняются `prepare`, `export-generation --missing-only` и импорт
с `--merge`. Поле `trust` из ручного файла игнорируется: такие записи всегда
получают фиксированный тип `human_curated`.

Платный OpenAI Batch API остаётся необязательным альтернативным способом массовой
генерации. Для подготовки файла используется команда ниже; она сама ничего не
отправляет. Batch использует `/v1/responses`, Structured Outputs и `store: false`.

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" export-generation --model gpt-5.5
```

Для отправки ключ задаётся только через окружение. Скрипт не сохраняет ключ в
проекте:

```powershell
$env:OPENAI_API_KEY = "..."
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\openai_search_text_batch.py" submit generation
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\openai_search_text_batch.py" status generation --download
```

Команда `status` делает один запрос и завершается; автоматического частого
опроса нет. После скачивания стандартный файл результата называется
`openai-generation-output.jsonl`.

После получения результатов extraction:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\generation-output.jsonl"
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" export-verification --model gpt-5.5
```

Проверяющий batch получает исходные источники и профиль. Для каждого поля он
возвращает один из вердиктов: `supported`, `partial`, `unsupported`,
`contradicted`, `spoiler`, `too_generic`. Решение `accept` допустимо только при
`supported` для каждого поля.

После получения результатов проверки:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-verification ".\verification-output.jsonl"
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" assemble
```

`assemble` детерминированно строит `searchText`, проверяет длину, реальный лимит
токенизатора E5, рекламные фразы, явные спойлеры, дубликаты и повторяющийся между
книгами boilerplate. Параллельный `catalog-v2-draft.json` появляется только если
приняты все 1000 профилей. Перенос в основной каталог и перестроение индексов —
отдельный следующий этап после ручной проверки и сравнения качества поиска.

При использовании встроенных имён файлов команды импорта выглядят так:

```powershell
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-generation ".\data\book_catalog\search-text-v2\openai-generation-output.jsonl" --merge
& ".\ml_search\.venv\Scripts\python.exe" ".\tools\book_catalog\search_text_v2.py" import-verification ".\data\book_catalog\search-text-v2\openai-verification-output.jsonl" --merge
```

Флаги `--missing-only` при экспорте и `--merge` при импорте позволяют повторять
только неуспешные или отсутствующие карточки.

## Артефакты

Все файлы хранятся в `data/book_catalog/search-text-v2/`:

- `source-packs.jsonl` и `source-report.json`;
- `openai-generation-batch.jsonl`;
- `generation-results.jsonl`;
- `generation-preview.json`;
- `editorial-*.jsonl`, `editorial-profiles.jsonl` и
  `editorial-profiles.report.json`;
- `editorial-audit.json` и `generation-quality-report.json`;
- `curated-pilot-profiles.jsonl`, `curated-manual-profiles.jsonl`;
- `codex-priority-profiles.json`;
- `openai-verification-batch.jsonl`;
- `verification-results.jsonl`;
- `profiles-draft.json`, `draft-report.json`, `review.md`;
- `catalog-v2-draft.json`, только после полного прохождения проверок.
