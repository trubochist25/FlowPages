<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

$root = dirname(__DIR__, 2);
require $root . '/config.php';

$catalogFile = $root . '/data/book_catalog/catalog.json';
$backupFile = $root . '/backups/before-book-catalog-20260725.sql';
$reportFile = $root . '/data/book_catalog/import-report.json';
$imageDir = $root . '/image/catalog/books';

if (!is_file($backupFile) || filesize($backupFile) < 10000) {
    throw new RuntimeException('Pre-import database backup is missing.');
}

$books = json_decode((string) file_get_contents($catalogFile), true, 512, JSON_THROW_ON_ERROR);

if (count($books) !== 1000) {
    throw new RuntimeException('Expected exactly 1000 books, got ' . count($books));
}

$seenTitles = [];

foreach ($books as $book) {
    $titleKey = mb_strtolower(trim($book['title']), 'UTF-8');
    if (isset($seenTitles[$titleKey])) {
        throw new RuntimeException("Duplicate title: {$book['title']}");
    }
    $seenTitles[$titleKey] = true;

    $image = $imageDir . '/book-' . str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT) . '.jpg';
    if (!is_file($image) || filesize($image) < 1500) {
        throw new RuntimeException("Missing or invalid cover: {$image}");
    }
}

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;
$now = date('Y-m-d H:i:s');
$today = date('Y-m-d');
$languageIds = [1, 2];

function cut(string $value, int $length): string
{
    return mb_substr($value, 0, $length, 'UTF-8');
}

function html(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
}

function slug(string $value): string
{
    $map = [
        'а'=>'a','б'=>'b','в'=>'v','г'=>'g','д'=>'d','е'=>'e','ё'=>'e','ж'=>'zh','з'=>'z',
        'и'=>'i','й'=>'y','к'=>'k','л'=>'l','м'=>'m','н'=>'n','о'=>'o','п'=>'p','р'=>'r',
        'с'=>'s','т'=>'t','у'=>'u','ф'=>'f','х'=>'h','ц'=>'c','ч'=>'ch','ш'=>'sh','щ'=>'sch',
        'ъ'=>'','ы'=>'y','ь'=>'','э'=>'e','ю'=>'yu','я'=>'ya'
    ];
    $value = mb_strtolower($value, 'UTF-8');
    $value = strtr($value, $map);
    $value = preg_replace('/[^a-z0-9]+/u', '-', $value);
    return trim((string) $value, '-');
}

function insertSeo(mysqli $db, string $prefix, int $languageId, string $query, string $keyword): void
{
    $stmt = $db->prepare(
        "INSERT INTO {$prefix}seo_url (store_id, language_id, query, keyword) VALUES (0, ?, ?, ?)"
    );
    $stmt->bind_param('iss', $languageId, $query, $keyword);
    $stmt->execute();
    $stmt->close();
}

$productTables = [
    'article_related_product', 'coupon_product', 'googleshopping_product',
    'googleshopping_product_status', 'googleshopping_product_target',
    'product_attribute', 'product_description', 'product_discount',
    'product_filter', 'product_image', 'product_option',
    'product_option_value', 'product_recurring', 'product_related',
    'product_related_article', 'product_related_mn', 'product_related_wb',
    'product_reward', 'product_special', 'product_to_category',
    'product_to_download', 'product_to_layout', 'product_to_store'
];

foreach ($productTables as $table) {
    $db->query("DELETE FROM {$prefix}{$table}");
}
$db->query("DELETE FROM {$prefix}product");

$categoryTables = [
    'category_filter', 'category_path', 'category_to_layout', 'category_to_store',
    'category_description', 'coupon_category', 'googleshopping_category'
];
foreach ($categoryTables as $table) {
    $db->query("DELETE FROM {$prefix}{$table}");
}
$db->query("DELETE FROM {$prefix}category");

$db->query("DELETE FROM {$prefix}manufacturer_description");
$db->query("DELETE FROM {$prefix}manufacturer_to_layout");
$db->query("DELETE FROM {$prefix}manufacturer_to_store");
$db->query("DELETE FROM {$prefix}manufacturer");

$db->query("DELETE FROM {$prefix}product_attribute");
$db->query("DELETE FROM {$prefix}attribute_description");
$db->query("DELETE FROM {$prefix}attribute");
$db->query("DELETE FROM {$prefix}attribute_group_description");
$db->query("DELETE FROM {$prefix}attribute_group");

$db->query(
    "DELETE FROM {$prefix}seo_url
     WHERE query LIKE 'product_id=%'
        OR query LIKE 'category_id=%'
        OR query LIKE 'manufacturer_id=%'"
);

$db->query(
    "CREATE TABLE IF NOT EXISTS {$prefix}book_metadata (
        product_id INT NOT NULL,
        work_key VARCHAR(64) NOT NULL,
        author TEXT NOT NULL,
        publication_year SMALLINT NOT NULL,
        pages SMALLINT NOT NULL,
        genres TEXT NOT NULL,
        themes TEXT NOT NULL,
        mood TEXT NOT NULL,
        pace VARCHAR(32) NOT NULL,
        age_rating VARCHAR(8) NOT NULL,
        language VARCHAR(32) NOT NULL,
        series VARCHAR(255) NOT NULL,
        popularity INT NOT NULL DEFAULT 0,
        rating DECIMAL(4,2) NOT NULL DEFAULT 0,
        rating_count INT NOT NULL DEFAULT 0,
        search_text TEXT NOT NULL,
        embedding MEDIUMTEXT NULL,
        cover_source_url VARCHAR(255) NOT NULL,
        PRIMARY KEY (product_id),
        KEY publication_year (publication_year),
        KEY pages (pages),
        KEY popularity (popularity),
        KEY pace (pace),
        KEY age_rating (age_rating)
    ) ENGINE=MyISAM DEFAULT CHARSET=utf8"
);
$db->query("DELETE FROM {$prefix}book_metadata");

$groupSort = 1;
$db->query("INSERT INTO {$prefix}attribute_group (sort_order) VALUES ({$groupSort})");
$attributeGroupId = (int) $db->insert_id;

$groupNames = [1 => 'Характеристики книги', 2 => 'Book details'];
$stmt = $db->prepare(
    "INSERT INTO {$prefix}attribute_group_description (attribute_group_id, language_id, name)
     VALUES (?, ?, ?)"
);
foreach ($languageIds as $languageId) {
    $name = $groupNames[$languageId];
    $stmt->bind_param('iis', $attributeGroupId, $languageId, $name);
    $stmt->execute();
}
$stmt->close();

$attributeDefinitions = [
    'author' => [1 => 'Автор', 2 => 'Author'],
    'year' => [1 => 'Год публикации', 2 => 'Publication year'],
    'pages' => [1 => 'Количество страниц', 2 => 'Pages'],
    'genres' => [1 => 'Жанры', 2 => 'Genres'],
    'themes' => [1 => 'Темы', 2 => 'Themes'],
    'mood' => [1 => 'Настроение', 2 => 'Mood'],
    'pace' => [1 => 'Темп', 2 => 'Pace'],
    'age' => [1 => 'Возрастной рейтинг', 2 => 'Age rating'],
    'language' => [1 => 'Язык', 2 => 'Language'],
    'series' => [1 => 'Серия', 2 => 'Series']
];
$attributeIds = [];
$sortOrder = 1;

foreach ($attributeDefinitions as $key => $names) {
    $stmt = $db->prepare(
        "INSERT INTO {$prefix}attribute (attribute_group_id, sort_order) VALUES (?, ?)"
    );
    $stmt->bind_param('ii', $attributeGroupId, $sortOrder);
    $stmt->execute();
    $attributeId = (int) $db->insert_id;
    $stmt->close();
    $attributeIds[$key] = $attributeId;

    $stmt = $db->prepare(
        "INSERT INTO {$prefix}attribute_description (attribute_id, language_id, name)
         VALUES (?, ?, ?)"
    );
    foreach ($languageIds as $languageId) {
        $name = $names[$languageId];
        $stmt->bind_param('iis', $attributeId, $languageId, $name);
        $stmt->execute();
    }
    $stmt->close();
    $sortOrder++;
}

$genreNames = array_values(array_unique(array_merge(...array_column($books, 'genres'))));
sort($genreNames, SORT_STRING);
$genreEnglish = [
    'Бизнес и экономика'=>'Business & Economics', 'Биографии и мемуары'=>'Biographies & Memoirs',
    'Детективы'=>'Detective Fiction', 'Детская литература'=>"Children's Books",
    'Здоровье'=>'Health', 'Искусство и культура'=>'Arts & Culture',
    'Историческая проза'=>'Historical Fiction', 'История'=>'History',
    'Классическая литература'=>'Classics', 'Комиксы и манга'=>'Comics & Manga',
    'Компьютеры и технологии'=>'Computers & Technology',
    'Научно-популярная литература'=>'Popular Science',
    'Подростковая литература'=>'Young Adult', 'Поэзия'=>'Poetry',
    'Приключения'=>'Adventure', 'Психология'=>'Psychology', 'Религия'=>'Religion',
    'Родительство'=>'Parenting', 'Романтика'=>'Romance', 'Саморазвитие'=>'Self-Improvement',
    'Современная проза'=>'Contemporary Fiction', 'Триллеры'=>'Thrillers',
    'Ужасы'=>'Horror', 'Фантастика'=>'Science Fiction', 'Философия'=>'Philosophy',
    'Фэнтези'=>'Fantasy', 'Юмор'=>'Humor'
];

$stmt = $db->prepare(
    "INSERT INTO {$prefix}category
     (image, parent_id, top, `column`, sort_order, status, date_added, date_modified, noindex)
     VALUES (NULL, 0, 1, 4, 0, 1, ?, ?, 0)"
);
$stmt->bind_param('ss', $now, $now);
$stmt->execute();
$rootCategoryId = (int) $db->insert_id;
$stmt->close();

$stmt = $db->prepare(
    "INSERT INTO {$prefix}category_description
     (category_id, language_id, name, description, meta_title, meta_description, meta_keyword, meta_h1)
     VALUES (?, ?, ?, '', ?, ?, ?, ?)"
);
foreach ($languageIds as $languageId) {
    $name = $languageId === 1 ? 'Книги' : 'Books';
    $metaTitle = $languageId === 1 ? 'Каталог книг FlowPages' : 'FlowPages Book Catalogue';
    $metaDescription = $languageId === 1
        ? 'Популярные книги разных жанров с удобным смысловым поиском.'
        : 'Popular books across genres with semantic search.';
    $metaKeyword = $languageId === 1 ? 'книги, каталог книг' : 'books, book catalogue';
    $metaH1 = $name;
    $stmt->bind_param(
        'iisssss',
        $rootCategoryId,
        $languageId,
        $name,
        $metaTitle,
        $metaDescription,
        $metaKeyword,
        $metaH1
    );
    $stmt->execute();
}
$stmt->close();
$db->query(
    "INSERT INTO {$prefix}category_path (category_id, path_id, level)
     VALUES ({$rootCategoryId}, {$rootCategoryId}, 0)"
);
$db->query(
    "INSERT INTO {$prefix}category_to_store (category_id, store_id)
     VALUES ({$rootCategoryId}, 0)"
);
insertSeo($db, $prefix, 1, "category_id={$rootCategoryId}", 'books');

$categoryIds = [];
$sortOrder = 1;
foreach ($genreNames as $genre) {
    $stmt = $db->prepare(
        "INSERT INTO {$prefix}category
         (image, parent_id, top, `column`, sort_order, status, date_added, date_modified, noindex)
         VALUES (NULL, ?, 0, 1, ?, 1, ?, ?, 0)"
    );
    $stmt->bind_param('iiss', $rootCategoryId, $sortOrder, $now, $now);
    $stmt->execute();
    $categoryId = (int) $db->insert_id;
    $stmt->close();
    $categoryIds[$genre] = $categoryId;

    $stmt = $db->prepare(
        "INSERT INTO {$prefix}category_description
         (category_id, language_id, name, description, meta_title, meta_description, meta_keyword, meta_h1)
         VALUES (?, ?, ?, '', ?, ?, ?, ?)"
    );
    foreach ($languageIds as $languageId) {
        $name = $languageId === 1 ? $genre : ($genreEnglish[$genre] ?? $genre);
        $metaTitle = cut($name . ' — книги FlowPages', 255);
        $metaDescription = cut('Популярные книги категории «' . $genre . '».', 255);
        $metaKeyword = cut(mb_strtolower($genre, 'UTF-8') . ', книги', 255);
        $metaH1 = $name;
        $stmt->bind_param(
            'iisssss',
            $categoryId,
            $languageId,
            $name,
            $metaTitle,
            $metaDescription,
            $metaKeyword,
            $metaH1
        );
        $stmt->execute();
    }
    $stmt->close();

    $db->query(
        "INSERT INTO {$prefix}category_path (category_id, path_id, level) VALUES
         ({$categoryId}, {$rootCategoryId}, 0),
         ({$categoryId}, {$categoryId}, 1)"
    );
    $db->query(
        "INSERT INTO {$prefix}category_to_store (category_id, store_id)
         VALUES ({$categoryId}, 0)"
    );
    insertSeo($db, $prefix, 1, "category_id={$categoryId}", 'books-' . slug($genre));
    $sortOrder++;
}

$authorNames = [];
foreach ($books as $book) {
    $author = cut((string) ($book['authors'][0] ?? $book['author']), 64);
    $authorNames[$author] = true;
}
$authorNames = array_keys($authorNames);
sort($authorNames, SORT_STRING);
$manufacturerIds = [];

foreach ($authorNames as $authorName) {
    $stmt = $db->prepare(
        "INSERT INTO {$prefix}manufacturer (name, image, sort_order, noindex)
         VALUES (?, NULL, 0, 0)"
    );
    $stmt->bind_param('s', $authorName);
    $stmt->execute();
    $manufacturerId = (int) $db->insert_id;
    $stmt->close();
    $manufacturerIds[$authorName] = $manufacturerId;

    $stmt = $db->prepare(
        "INSERT INTO {$prefix}manufacturer_description
         (manufacturer_id, language_id, description, meta_description, meta_keyword, meta_title, meta_h1)
         VALUES (?, ?, '', ?, ?, ?, ?)"
    );
    foreach ($languageIds as $languageId) {
        $metaDescription = cut('Книги автора ' . $authorName . ' в каталоге FlowPages.', 255);
        $metaKeyword = cut($authorName . ', книги', 255);
        $metaTitle = cut($authorName . ' — книги автора', 255);
        $metaH1 = $authorName;
        $stmt->bind_param(
            'iissss',
            $manufacturerId,
            $languageId,
            $metaDescription,
            $metaKeyword,
            $metaTitle,
            $metaH1
        );
        $stmt->execute();
    }
    $stmt->close();

    $db->query(
        "INSERT INTO {$prefix}manufacturer_to_store (manufacturer_id, store_id)
         VALUES ({$manufacturerId}, 0)"
    );
}

$productInsert = $db->prepare(
    "INSERT INTO {$prefix}product
     (model, sku, upc, ean, jan, isbn, mpn, location, quantity, stock_status_id,
      image, manufacturer_id, shipping, price, points, tax_class_id, date_available,
      weight, weight_class_id, length, width, height, length_class_id, subtract,
      minimum, sort_order, status, viewed, date_added, date_modified, noindex)
     VALUES (?, ?, '', ?, '', ?, '', '', ?, 7, ?, ?, 1, ?, 0, 9, ?, ?, 1,
             21, 14, ?, 1, 1, 1, ?, 1, ?, ?, ?, 0)"
);
$descriptionInsert = $db->prepare(
    "INSERT INTO {$prefix}product_description
     (product_id, language_id, name, description, tag, meta_title,
      meta_description, meta_keyword, meta_h1)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
);
$productCategoryInsert = $db->prepare(
    "INSERT INTO {$prefix}product_to_category (product_id, category_id, main_category)
     VALUES (?, ?, ?)"
);
$productStoreInsert = $db->prepare(
    "INSERT INTO {$prefix}product_to_store (product_id, store_id) VALUES (?, 0)"
);
$attributeInsert = $db->prepare(
    "INSERT INTO {$prefix}product_attribute (product_id, attribute_id, language_id, text)
     VALUES (?, ?, ?, ?)"
);
$metadataInsert = $db->prepare(
    "INSERT INTO {$prefix}book_metadata
     (product_id, work_key, author, publication_year, pages, genres, themes, mood,
      pace, age_rating, language, series, popularity, rating, rating_count,
      search_text, embedding, cover_source_url)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)"
);

$importedIds = [];

foreach ($books as $index => $book) {
    $number = str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT);
    $model = "BOOK-{$number}";
    $sku = $model;
    $ean = preg_match('/^\d{13}$/', (string) $book['isbn']) ? $book['isbn'] : '';
    $isbn = cut((string) $book['isbn'], 17);
    $quantity = (int) $book['quantity'];
    $image = "catalog/books/book-{$number}.jpg";
    $primaryAuthor = cut((string) ($book['authors'][0] ?? $book['author']), 64);
    $manufacturerId = $manufacturerIds[$primaryAuthor];
    $price = (float) $book['price'];
    $weight = round(0.14 + ((int) $book['pages'] * 0.00075), 3);
    $height = round(max(0.6, min(8.0, (int) $book['pages'] * 0.005)), 2);
    $sort = $index + 1;
    $viewed = min(250000, max(0, (int) $book['popularity'] * 3));

    $productInsert->bind_param(
        'ssssisidsddiiss',
        $model,
        $sku,
        $ean,
        $isbn,
        $quantity,
        $image,
        $manufacturerId,
        $price,
        $today,
        $weight,
        $height,
        $sort,
        $viewed,
        $now,
        $now
    );
    $productInsert->execute();
    $productId = (int) $db->insert_id;
    $importedIds[] = $productId;

    $genreText = implode(', ', $book['genres']);
    $themeText = implode(', ', $book['themes']);
    $moodText = implode(', ', $book['mood']);
    $seriesText = $book['series'] ?: 'Не указана';
    $details = '<ul class="book-summary">'
        . '<li><strong>Автор:</strong> ' . html($book['author']) . '</li>'
        . '<li><strong>Жанры:</strong> ' . html($genreText) . '</li>'
        . '<li><strong>Темы:</strong> ' . html($themeText) . '</li>'
        . '<li><strong>Настроение:</strong> ' . html($moodText) . '</li>'
        . '<li><strong>Объём:</strong> ' . (int) $book['pages'] . ' стр.</li>'
        . '</ul>';
    $description = '<p>' . html($book['annotation']) . '</p>' . $details;
    $tag = cut(implode(', ', array_unique($book['tags'])), 1000);
    $metaTitle = cut($book['title'] . ' — ' . $book['author'] . ' | FlowPages', 255);
    $metaDescription = cut($book['annotation'], 255);
    $metaKeyword = cut(implode(', ', array_merge([$book['title'], $book['author']], $book['tags'])), 255);
    $metaH1 = cut($book['title'], 255);
    $name = cut($book['title'], 255);

    foreach ($languageIds as $languageId) {
        $descriptionInsert->bind_param(
            'iisssssss',
            $productId,
            $languageId,
            $name,
            $description,
            $tag,
            $metaTitle,
            $metaDescription,
            $metaKeyword,
            $metaH1
        );
        $descriptionInsert->execute();
    }

    $mainGenre = $book['genres'][0];
    $rootMain = 0;
    $productCategoryInsert->bind_param('iii', $productId, $rootCategoryId, $rootMain);
    $productCategoryInsert->execute();

    foreach ($book['genres'] as $genreIndex => $genre) {
        $categoryId = $categoryIds[$genre];
        $main = $genreIndex === 0 ? 1 : 0;
        $productCategoryInsert->bind_param('iii', $productId, $categoryId, $main);
        $productCategoryInsert->execute();
    }

    $productStoreInsert->bind_param('i', $productId);
    $productStoreInsert->execute();

    $attributeValues = [
        'author' => $book['author'],
        'year' => (string) $book['year'],
        'pages' => (string) $book['pages'],
        'genres' => $genreText,
        'themes' => $themeText,
        'mood' => $moodText,
        'pace' => $book['pace'],
        'age' => $book['ageRating'],
        'language' => $book['language'],
        'series' => $seriesText
    ];
    foreach ($attributeValues as $attributeKey => $text) {
        $attributeId = $attributeIds[$attributeKey];
        foreach ($languageIds as $languageId) {
            $attributeInsert->bind_param(
                'iiis',
                $productId,
                $attributeId,
                $languageId,
                $text
            );
            $attributeInsert->execute();
        }
    }

    $workKey = cut($book['workKey'], 64);
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
    $coverSource = cut($book['coverSource'], 255);
    $metadataInsert->bind_param(
        'issiisssssssidiss',
        $productId,
        $workKey,
        $author,
        $year,
        $pages,
        $genresJson,
        $themesJson,
        $moodJson,
        $pace,
        $ageRating,
        $language,
        $series,
        $popularity,
        $rating,
        $ratingCount,
        $searchText,
        $coverSource
    );
    $metadataInsert->execute();

    insertSeo(
        $db,
        $prefix,
        1,
        "product_id={$productId}",
        'book-' . slug($book['title']) . '-' . $book['id']
    );

    if (($index + 1) % 100 === 0) {
        echo 'Imported ' . ($index + 1) . "/1000\n";
    }
}

$productInsert->close();
$descriptionInsert->close();
$productCategoryInsert->close();
$productStoreInsert->close();
$attributeInsert->close();
$metadataInsert->close();

$report = [
    'importedAt' => date(DATE_ATOM),
    'products' => count($importedIds),
    'firstProductId' => min($importedIds),
    'lastProductId' => max($importedIds),
    'categories' => 1 + count($categoryIds),
    'authors' => count($manufacturerIds),
    'attributes' => count($attributeIds),
    'covers' => count($books),
    'backup' => str_replace('\\', '/', substr($backupFile, strlen($root) + 1))
];

file_put_contents(
    $reportFile,
    json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)
);

echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
