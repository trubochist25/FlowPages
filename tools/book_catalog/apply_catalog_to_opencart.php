<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

$root = dirname(__DIR__, 2);
require $root . '/config.php';

$books = json_decode(
    (string) file_get_contents($root . '/data/book_catalog/catalog.json'),
    true,
    512,
    JSON_THROW_ON_ERROR
);
if (count($books) !== 1000) {
    throw new RuntimeException('Expected exactly 1000 books');
}

$selectedIds = null;
foreach (array_slice($argv, 1) as $argument) {
    if (strpos($argument, '--ids=') !== 0) {
        continue;
    }
    $selectedIds = [];
    foreach (explode(',', substr($argument, 6)) as $rawId) {
        $id = filter_var(trim($rawId), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        if ($id === false) {
            throw new InvalidArgumentException("Invalid catalog id: {$rawId}");
        }
        $selectedIds[(int) $id] = true;
    }
    if (!$selectedIds) {
        throw new InvalidArgumentException('The --ids option must contain at least one catalog id');
    }
}

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;
$now = date('Y-m-d H:i:s');
$languageIds = [1, 2];

function cutValue(string $value, int $length): string
{
    return mb_substr($value, 0, $length, 'UTF-8');
}

function htmlValue(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
}

function slugValue(string $value): string
{
    $map = [
        'а'=>'a','б'=>'b','в'=>'v','г'=>'g','д'=>'d','е'=>'e','ё'=>'e','ж'=>'zh','з'=>'z',
        'и'=>'i','й'=>'y','к'=>'k','л'=>'l','м'=>'m','н'=>'n','о'=>'o','п'=>'p','р'=>'r',
        'с'=>'s','т'=>'t','у'=>'u','ф'=>'f','х'=>'h','ц'=>'c','ч'=>'ch','ш'=>'sh','щ'=>'sch',
        'ъ'=>'','ы'=>'y','ь'=>'','э'=>'e','ю'=>'yu','я'=>'ya'
    ];
    $value = strtr(mb_strtolower($value, 'UTF-8'), $map);
    return trim((string) preg_replace('/[^a-z0-9]+/u', '-', $value), '-');
}

function fetchNameMap(mysqli $db, string $sql): array
{
    $result = $db->query($sql);
    $map = [];
    while ($row = $result->fetch_assoc()) {
        $map[(string) $row['name']] = (int) $row['id'];
    }
    return $map;
}

$categoryIds = fetchNameMap(
    $db,
    "SELECT category_id AS id, name FROM {$prefix}category_description WHERE language_id=1"
);
if (!isset($categoryIds['Книги'])) {
    throw new RuntimeException('Root category "Книги" is missing');
}
$rootCategoryId = $categoryIds['Книги'];

$attributeNameToKey = [
    'Автор' => 'author',
    'Год публикации' => 'year',
    'Количество страниц' => 'pages',
    'Жанры' => 'genres',
    'Темы' => 'themes',
    'Настроение' => 'mood',
    'Темп' => 'pace',
    'Возрастной рейтинг' => 'age',
    'Язык' => 'language',
    'Серия' => 'series',
];
$attributeIds = [];
$attributeResult = $db->query(
    "SELECT attribute_id, name FROM {$prefix}attribute_description WHERE language_id=1"
);
while ($row = $attributeResult->fetch_assoc()) {
    if (isset($attributeNameToKey[$row['name']])) {
        $attributeIds[$attributeNameToKey[$row['name']]] = (int) $row['attribute_id'];
    }
}
if (count($attributeIds) !== count($attributeNameToKey)) {
    throw new RuntimeException('The expected book attributes are not configured');
}

$requiredGenres = [];
foreach ($books as $book) {
    foreach ($book['genres'] as $genre) {
        $requiredGenres[$genre] = true;
    }
}
foreach (array_keys($requiredGenres) as $genre) {
    if (!isset($categoryIds[$genre])) {
        throw new RuntimeException("Category is missing: {$genre}");
    }
}
$productCount = (int) $db->query(
    "SELECT COUNT(*) FROM {$prefix}product WHERE model REGEXP '^BOOK-[0-9]{4}$'"
)->fetch_row()[0];
$metadataCount = (int) $db->query(
    "SELECT COUNT(*) FROM {$prefix}book_metadata"
)->fetch_row()[0];
if ($productCount !== 1000 || $metadataCount !== 1000) {
    throw new RuntimeException("Expected 1000 products and metadata rows, got {$productCount}/{$metadataCount}");
}
if (($argv[1] ?? '') === '--check') {
    echo json_encode([
        'status' => 'ready',
        'products' => $productCount,
        'metadata' => $metadataCount,
        'genres' => count($requiredGenres),
        'attributes' => count($attributeIds),
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
    $db->close();
    exit(0);
}

$manufacturerIds = fetchNameMap(
    $db,
    "SELECT manufacturer_id AS id, name FROM {$prefix}manufacturer"
);
$findProduct = $db->prepare(
    "SELECT product_id FROM {$prefix}product WHERE model=? LIMIT 1"
);
$updateProduct = $db->prepare(
    "UPDATE {$prefix}product
     SET ean=?, isbn=?, quantity=?, image=?, manufacturer_id=?, price=?, weight=?, height=?,
         sort_order=?, viewed=?, date_modified=?
     WHERE product_id=?"
);
$updateDescription = $db->prepare(
    "UPDATE {$prefix}product_description
     SET name=?, description=?, tag=?, meta_title=?, meta_description=?, meta_keyword=?, meta_h1=?
     WHERE product_id=? AND language_id=?"
);
$deleteCategories = $db->prepare(
    "DELETE FROM {$prefix}product_to_category WHERE product_id=?"
);
$insertCategory = $db->prepare(
    "INSERT INTO {$prefix}product_to_category (product_id, category_id, main_category)
     VALUES (?, ?, ?)"
);
$deleteAttributes = $db->prepare(
    "DELETE FROM {$prefix}product_attribute WHERE product_id=?"
);
$insertAttribute = $db->prepare(
    "INSERT INTO {$prefix}product_attribute (product_id, attribute_id, language_id, text)
     VALUES (?, ?, ?, ?)"
);
$updateMetadata = $db->prepare(
    "UPDATE {$prefix}book_metadata
     SET work_key=?, author=?, publication_year=?, pages=?, genres=?, themes=?, mood=?, pace=?,
         age_rating=?, language=?, series=?, popularity=?, rating=?, rating_count=?, search_text=?,
         embedding=NULL, cover_source_url=?
     WHERE product_id=?"
);
$updateSeo = $db->prepare(
    "UPDATE {$prefix}seo_url SET keyword=?
     WHERE query=? AND language_id=1"
);

$updated = 0;
$createdManufacturers = 0;

foreach ($books as $index => $book) {
    if ($selectedIds !== null && !isset($selectedIds[(int) $book['id']])) {
        continue;
    }
    $number = str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT);
    $model = "BOOK-{$number}";
    $findProduct->bind_param('s', $model);
    $findProduct->execute();
    $row = $findProduct->get_result()->fetch_assoc();
    if (!$row) {
        throw new RuntimeException("Product not found: {$model}");
    }
    $productId = (int) $row['product_id'];

    $primaryAuthor = cutValue((string) ($book['authors'][0] ?? $book['author']), 64);
    if (!isset($manufacturerIds[$primaryAuthor])) {
        $stmt = $db->prepare(
            "INSERT INTO {$prefix}manufacturer (name, image, sort_order, noindex) VALUES (?, NULL, 0, 0)"
        );
        $stmt->bind_param('s', $primaryAuthor);
        $stmt->execute();
        $manufacturerId = (int) $db->insert_id;
        $stmt->close();
        $manufacturerIds[$primaryAuthor] = $manufacturerId;
        $db->query(
            "INSERT INTO {$prefix}manufacturer_to_store (manufacturer_id, store_id) VALUES ({$manufacturerId}, 0)"
        );
        $stmt = $db->prepare(
            "INSERT INTO {$prefix}manufacturer_description
             (manufacturer_id, language_id, description, meta_description, meta_keyword, meta_title, meta_h1)
             VALUES (?, ?, '', ?, ?, ?, ?)"
        );
        foreach ($languageIds as $languageId) {
            $metaDescription = cutValue('Книги автора ' . $primaryAuthor . ' в каталоге FlowPages.', 255);
            $metaKeyword = cutValue($primaryAuthor . ', книги', 255);
            $metaTitle = cutValue($primaryAuthor . ' — книги автора', 255);
            $metaH1 = $primaryAuthor;
            $stmt->bind_param('iissss', $manufacturerId, $languageId, $metaDescription, $metaKeyword, $metaTitle, $metaH1);
            $stmt->execute();
        }
        $stmt->close();
        $createdManufacturers++;
    }
    $manufacturerId = $manufacturerIds[$primaryAuthor];

    $ean = preg_match('/^\d{13}$/', (string) $book['isbn']) ? (string) $book['isbn'] : '';
    $isbn = cutValue((string) $book['isbn'], 17);
    $quantity = (int) $book['quantity'];
    $image = "catalog/books/book-{$number}.jpg";
    $price = (float) $book['price'];
    $weight = round(0.14 + ((int) $book['pages'] * 0.00075), 3);
    $height = round(max(0.6, min(8.0, (int) $book['pages'] * 0.005)), 2);
    $sortOrder = $index + 1;
    $viewed = min(250000, max(0, (int) $book['popularity'] * 3));
    $updateProduct->bind_param(
        'ssisidddiisi',
        $ean, $isbn, $quantity, $image, $manufacturerId, $price, $weight, $height,
        $sortOrder, $viewed, $now, $productId
    );
    $updateProduct->execute();

    $genreText = implode(', ', $book['genres']);
    $themeText = implode(', ', $book['themes']);
    $moodText = implode(', ', $book['mood']);
    $description = '<p>' . htmlValue($book['annotation']) . '</p>'
        . '<ul class="book-summary">'
        . '<li><strong>Автор:</strong> ' . htmlValue($book['author']) . '</li>'
        . '<li><strong>Жанры:</strong> ' . htmlValue($genreText) . '</li>'
        . '<li><strong>Темы:</strong> ' . htmlValue($themeText) . '</li>'
        . '<li><strong>Настроение:</strong> ' . htmlValue($moodText) . '</li>'
        . '<li><strong>Объём:</strong> ' . (int) $book['pages'] . ' стр.</li></ul>';
    $tag = cutValue(implode(', ', array_unique($book['tags'])), 1000);
    $metaTitle = cutValue($book['title'] . ' — ' . $book['author'] . ' | FlowPages', 255);
    $metaDescription = cutValue($book['annotation'], 255);
    $metaKeyword = cutValue(implode(', ', array_merge([$book['title'], $book['author']], $book['tags'])), 255);
    $metaH1 = cutValue($book['title'], 255);
    $name = cutValue($book['title'], 255);
    foreach ($languageIds as $languageId) {
        $updateDescription->bind_param(
            'sssssssii',
            $name, $description, $tag, $metaTitle, $metaDescription, $metaKeyword, $metaH1,
            $productId, $languageId
        );
        $updateDescription->execute();
    }

    $deleteCategories->bind_param('i', $productId);
    $deleteCategories->execute();
    $main = 0;
    $insertCategory->bind_param('iii', $productId, $rootCategoryId, $main);
    $insertCategory->execute();
    foreach ($book['genres'] as $genreIndex => $genre) {
        if (!isset($categoryIds[$genre])) {
            throw new RuntimeException("Category is missing: {$genre}");
        }
        $categoryId = $categoryIds[$genre];
        $main = $genreIndex === 0 ? 1 : 0;
        $insertCategory->bind_param('iii', $productId, $categoryId, $main);
        $insertCategory->execute();
    }

    $deleteAttributes->bind_param('i', $productId);
    $deleteAttributes->execute();
    $attributeValues = [
        'author' => $book['author'], 'year' => (string) $book['year'],
        'pages' => (string) $book['pages'], 'genres' => $genreText,
        'themes' => $themeText, 'mood' => $moodText, 'pace' => $book['pace'],
        'age' => $book['ageRating'], 'language' => $book['language'],
        'series' => $book['series'] ?: 'Не указана',
    ];
    foreach ($attributeValues as $key => $text) {
        $attributeId = $attributeIds[$key];
        foreach ($languageIds as $languageId) {
            $insertAttribute->bind_param('iiis', $productId, $attributeId, $languageId, $text);
            $insertAttribute->execute();
        }
    }

    $workKey = cutValue($book['workKey'], 64);
    $author = $book['author'];
    $year = (int) $book['year'];
    $pages = (int) $book['pages'];
    $genresJson = json_encode($book['genres'], JSON_UNESCAPED_UNICODE);
    $themesJson = json_encode($book['themes'], JSON_UNESCAPED_UNICODE);
    $moodJson = json_encode($book['mood'], JSON_UNESCAPED_UNICODE);
    $pace = $book['pace'];
    $ageRating = $book['ageRating'];
    $language = $book['language'];
    $series = $book['series'];
    $popularity = (int) $book['popularity'];
    $rating = (float) $book['rating'];
    $ratingCount = (int) $book['ratingCount'];
    $searchText = $book['searchText'];
    $coverSource = cutValue($book['coverSource'], 255);
    $updateMetadata->bind_param(
        'ssiisssssssidissi',
        $workKey, $author, $year, $pages, $genresJson, $themesJson, $moodJson,
        $pace, $ageRating, $language, $series, $popularity, $rating, $ratingCount,
        $searchText, $coverSource, $productId
    );
    $updateMetadata->execute();
    if ($updateMetadata->affected_rows === 0) {
        $check = $db->query("SELECT 1 FROM {$prefix}book_metadata WHERE product_id={$productId}");
        if (!$check->fetch_row()) {
            throw new RuntimeException("Metadata missing for {$model}");
        }
    }

    $keyword = 'book-' . slugValue($book['title']) . '-' . $book['id'];
    $query = "product_id={$productId}";
    $updateSeo->bind_param('ss', $keyword, $query);
    $updateSeo->execute();

    $updated++;
    if ($updated % 100 === 0) {
        echo "Updated {$updated}/1000\n";
    }
}

$db->close();
echo json_encode([
    'updated' => $updated,
    'selectedIds' => $selectedIds === null ? null : array_map('intval', array_keys($selectedIds)),
    'createdManufacturers' => $createdManufacturers,
    'catalog' => 'data/book_catalog/catalog.json',
], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
