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
$stmt = $db->prepare(
    "SELECT p.product_id, p.price, p.quantity, p.image, pd.name,
            bm.author, bm.publication_year, bm.pages, bm.genres, bm.themes,
            bm.mood, bm.pace, bm.age_rating, bm.search_text, bm.embedding
     FROM {$prefix}product p
     JOIN {$prefix}product_description pd ON pd.product_id=p.product_id AND pd.language_id=1
     JOIN {$prefix}book_metadata bm ON bm.product_id=p.product_id
     WHERE p.model=? LIMIT 1"
);
$errors = [];
$nullEmbeddings = 0;
foreach ($books as $book) {
    $model = 'BOOK-' . str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT);
    $stmt->bind_param('s', $model);
    $stmt->execute();
    $row = $stmt->get_result()->fetch_assoc();
    if (!$row) {
        $errors[] = "{$model}: row missing";
        continue;
    }
    $expected = [
        'name' => $book['title'], 'author' => $book['author'],
        'publication_year' => (string) $book['year'], 'pages' => (string) $book['pages'],
        'genres' => json_encode($book['genres'], JSON_UNESCAPED_UNICODE),
        'themes' => json_encode($book['themes'], JSON_UNESCAPED_UNICODE),
        'mood' => json_encode($book['mood'], JSON_UNESCAPED_UNICODE),
        'pace' => $book['pace'], 'age_rating' => $book['ageRating'],
        'search_text' => $book['searchText'],
        'quantity' => (string) $book['quantity'],
        'image' => 'catalog/books/book-' . str_pad((string) $book['id'], 4, '0', STR_PAD_LEFT) . '.jpg',
    ];
    foreach ($expected as $field => $value) {
        if ((string) $row[$field] !== (string) $value) {
            $errors[] = "{$model}: {$field} differs";
        }
    }
    if (abs((float) $row['price'] - (float) $book['price']) > 0.001) {
        $errors[] = "{$model}: price differs";
    }
    if ($row['embedding'] === null) {
        $nullEmbeddings++;
    }
}
$stmt->close();
$db->close();
echo json_encode([
    'status' => $errors ? 'failed' : 'passed',
    'books' => count($books),
    'errors' => count($errors),
    'examples' => array_slice($errors, 0, 20),
    'nullEmbeddings' => $nullEmbeddings,
], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
exit($errors ? 1 : 0);
