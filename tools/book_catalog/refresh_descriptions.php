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
$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;

function cutDescription(string $value, int $length): string
{
    return mb_substr($value, 0, $length, 'UTF-8');
}

function htmlDescription(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
}

$find = $db->prepare("SELECT product_id FROM {$prefix}product WHERE model=?");
$update = $db->prepare(
    "UPDATE {$prefix}product_description
     SET description=?, tag=?, meta_title=?, meta_description=?, meta_keyword=?, meta_h1=?
     WHERE product_id=?"
);
$updated = 0;

foreach ($books as $book) {
    $model = 'BOOK-' . str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT);
    $find->bind_param('s', $model);
    $find->execute();
    $productId = (int) $find->get_result()->fetch_row()[0];

    if (!$productId) {
        throw new RuntimeException("Product not found: {$model}");
    }

    $genreText = implode(', ', $book['genres']);
    $themeText = implode(', ', $book['themes']);
    $moodText = implode(', ', $book['mood']);
    $description = '<p>' . htmlDescription($book['annotation']) . '</p>'
        . '<ul class="book-summary">'
        . '<li><strong>Автор:</strong> ' . htmlDescription($book['author']) . '</li>'
        . '<li><strong>Жанры:</strong> ' . htmlDescription($genreText) . '</li>'
        . '<li><strong>Темы:</strong> ' . htmlDescription($themeText) . '</li>'
        . '<li><strong>Настроение:</strong> ' . htmlDescription($moodText) . '</li>'
        . '<li><strong>Объём:</strong> ' . (int) $book['pages'] . ' стр.</li>'
        . '</ul>';
    $tag = cutDescription(implode(', ', array_unique($book['tags'])), 1000);
    $metaTitle = cutDescription($book['title'] . ' — ' . $book['author'] . ' | FlowPages', 255);
    $metaDescription = cutDescription($book['annotation'], 255);
    $metaKeyword = cutDescription(
        implode(', ', array_merge([$book['title'], $book['author']], $book['tags'])),
        255
    );
    $metaH1 = cutDescription($book['title'], 255);

    $update->bind_param(
        'ssssssi',
        $description,
        $tag,
        $metaTitle,
        $metaDescription,
        $metaKeyword,
        $metaH1,
        $productId
    );
    $update->execute();
    $updated++;
}

$find->close();
$update->close();

echo "Descriptions refreshed: {$updated}\n";
