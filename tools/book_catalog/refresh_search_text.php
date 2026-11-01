<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

$root = dirname(__DIR__, 2);
require $root . '/config.php';

$catalogFile = $root . '/data/book_catalog/catalog.json';
$books = json_decode(
    (string) file_get_contents($catalogFile),
    true,
    512,
    JSON_THROW_ON_ERROR
);

if (count($books) !== 1000) {
    throw new RuntimeException('Expected exactly 1000 books, got ' . count($books));
}

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;

$findProduct = $db->prepare(
    "SELECT product_id FROM {$prefix}product WHERE model = ? LIMIT 1"
);
$updateMetadata = $db->prepare(
    "UPDATE {$prefix}book_metadata SET search_text = ? WHERE product_id = ?"
);

$updated = 0;

foreach ($books as $book) {
    $model = 'BOOK-' . str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT);
    $findProduct->bind_param('s', $model);
    $findProduct->execute();
    $row = $findProduct->get_result()->fetch_assoc();

    if (!$row) {
        throw new RuntimeException("Product not found: {$model}");
    }

    $productId = (int) $row['product_id'];
    $searchText = (string) $book['searchText'];
    $updateMetadata->bind_param('si', $searchText, $productId);
    $updateMetadata->execute();

    if ($updateMetadata->affected_rows === 0) {
        $check = $db->query(
            "SELECT 1 FROM {$prefix}book_metadata WHERE product_id = {$productId} LIMIT 1"
        );
        if (!$check->fetch_row()) {
            throw new RuntimeException("Book metadata not found: {$model}");
        }
    }

    $updated++;
}

$findProduct->close();
$updateMetadata->close();
$db->close();

echo "Search profiles refreshed: {$updated}\n";
