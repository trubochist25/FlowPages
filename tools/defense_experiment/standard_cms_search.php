<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$root = dirname(__DIR__, 2);
require $root . '/config.php';

if ($argc !== 2) {
    fwrite(STDERR, "Usage: php standard_cms_search.php <queries.json>\n");
    exit(2);
}

$queries = json_decode((string) file_get_contents($argv[1]), true, 512, JSON_THROW_ON_ERROR);
$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8mb4');
$prefix = DB_PREFIX;
$results = array();

foreach ($queries as $case) {
    $query = trim((string) $case['query']);
    $words = explode(' ', trim((string) preg_replace('/\s+/u', ' ', $query)));
    $nameParts = array();
    $tagParts = array();
    foreach ($words as $word) {
        $escaped = $db->real_escape_string($word);
        $nameParts[] = "pd.name LIKE '%{$escaped}%'";
        $tagParts[] = "pd.tag LIKE '%{$escaped}%'";
    }
    $exact = $db->real_escape_string(mb_strtolower($query, 'UTF-8'));
    $sql = "SELECT p.product_id, p.model, pd.name
            FROM {$prefix}product p
            LEFT JOIN {$prefix}product_description pd ON p.product_id = pd.product_id
            LEFT JOIN {$prefix}product_to_store p2s ON p.product_id = p2s.product_id
            WHERE pd.language_id = 1
              AND p.status = 1
              AND p.date_available <= NOW()
              AND p2s.store_id = 0
              AND ((" . implode(' AND ', $nameParts) . ")
                   OR (" . implode(' AND ', $tagParts) . ")
                   OR LCASE(p.model) = '{$exact}'
                   OR LCASE(p.sku) = '{$exact}'
                   OR LCASE(p.upc) = '{$exact}'
                   OR LCASE(p.ean) = '{$exact}'
                   OR LCASE(p.jan) = '{$exact}'
                   OR LCASE(p.isbn) = '{$exact}'
                   OR LCASE(p.mpn) = '{$exact}')
            GROUP BY p.product_id
            ORDER BY p.sort_order ASC, LCASE(pd.name) ASC
            LIMIT 5";

    $rows = $db->query($sql)->fetch_all(MYSQLI_ASSOC);
    foreach ($rows as &$row) {
        $row['product_id'] = (int) $row['product_id'];
        $row['catalog_id'] = preg_match('/^BOOK-(\d+)$/', (string) $row['model'], $match)
            ? (int) $match[1]
            : null;
    }
    unset($row);
    $results[(string) $case['query_id']] = $rows;
}

$db->close();
echo json_encode($results, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . "\n";

