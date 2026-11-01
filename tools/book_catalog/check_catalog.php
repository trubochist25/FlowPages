<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
require dirname(__DIR__, 2) . '/config.php';

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;

function scalar(mysqli $db, string $sql): int
{
    return (int) $db->query($sql)->fetch_row()[0];
}

$report = [
    'products' => scalar($db, "SELECT COUNT(*) FROM {$prefix}product"),
    'activeProducts' => scalar($db, "SELECT COUNT(*) FROM {$prefix}product WHERE status=1"),
    'russianDescriptions' => scalar(
        $db,
        "SELECT COUNT(*) FROM {$prefix}product_description WHERE language_id=1"
    ),
    'metadataRows' => scalar($db, "SELECT COUNT(*) FROM {$prefix}book_metadata"),
    'productAttributes' => scalar($db, "SELECT COUNT(*) FROM {$prefix}product_attribute"),
    'categories' => scalar($db, "SELECT COUNT(*) FROM {$prefix}category"),
    'authors' => scalar($db, "SELECT COUNT(*) FROM {$prefix}manufacturer"),
    'missingImages' => scalar(
        $db,
        "SELECT COUNT(*) FROM {$prefix}product
         WHERE image IS NULL OR image=''"
    ),
    'missingCategoryLinks' => scalar(
        $db,
        "SELECT COUNT(*) FROM {$prefix}product p
         LEFT JOIN {$prefix}product_to_category pc ON pc.product_id=p.product_id
         WHERE pc.product_id IS NULL"
    ),
    'missingStoreLinks' => scalar(
        $db,
        "SELECT COUNT(*) FROM {$prefix}product p
         LEFT JOIN {$prefix}product_to_store ps ON ps.product_id=p.product_id
         WHERE ps.product_id IS NULL"
    ),
    'duplicateRussianTitles' => scalar(
        $db,
        "SELECT COUNT(*) FROM (
            SELECT name FROM {$prefix}product_description
            WHERE language_id=1 GROUP BY name HAVING COUNT(*)>1
         ) duplicates"
    ),
    'priceMin' => (float) $db->query("SELECT MIN(price) FROM {$prefix}product")->fetch_row()[0],
    'priceMax' => (float) $db->query("SELECT MAX(price) FROM {$prefix}product")->fetch_row()[0],
    'pagesMin' => scalar($db, "SELECT MIN(pages) FROM {$prefix}book_metadata"),
    'pagesMax' => scalar($db, "SELECT MAX(pages) FROM {$prefix}book_metadata")
];

$currencies = [];
$result = $db->query(
    "SELECT currency_id,title,code,symbol_left,symbol_right,value,status
     FROM {$prefix}currency ORDER BY currency_id"
);
while ($row = $result->fetch_assoc()) {
    $currencies[] = $row;
}
$report['currencies'] = $currencies;

$settings = [];
$result = $db->query(
    "SELECT store_id,code,`key`,value
     FROM {$prefix}setting WHERE `key`='config_currency'"
);
while ($row = $result->fetch_assoc()) {
    $settings[] = $row;
}
$report['currencySettings'] = $settings;

echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
