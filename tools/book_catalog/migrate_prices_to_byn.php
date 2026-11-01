<?php
declare(strict_types=1);

// Fixed NBRB rate, 2026-09-15: 100 RUB = 3.6095 BYN.
require dirname(__DIR__, 2) . '/config.php';
mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$root = dirname(__DIR__, 2);
$roundOnly = in_array('--round-tenths', $argv, true);
$rate = $roundOnly ? 1.0 : 0.036095;
$current = $db->query("SELECT value FROM " . DB_PREFIX . "setting WHERE store_id=0 AND `key`='config_currency'")->fetch_assoc()['value'];
if ($current === 'BYN' && !$roundOnly) {
    echo "Already migrated to BYN; no changes.\n";
    exit;
}
if ($current !== ($roundOnly ? 'BYN' : 'RUB')) throw new RuntimeException('Unexpected base currency');
$backup = $root . '/data/currency-backup-' . date('Ymd-His');
if (!mkdir($backup, 0700)) throw new RuntimeException('Cannot create backup directory');
file_put_contents($backup . '/.htaccess', "Require all denied\n");
$argv = [__FILE__, $backup . '/database.sql'];
require __DIR__ . '/backup_database.php';
$catalogPath = $root . '/data/book_catalog/catalog.json';
$manifestPath = $root . '/data/ml_search/indexes/multilingual-e5-small/manifest.json';
$oldCatalog = file_get_contents($catalogPath);
$oldManifest = file_get_contents($manifestPath);
copy($catalogPath, $backup . '/catalog.json');
copy($manifestPath, $backup . '/manifest.json');
$oldBooks = json_decode($oldCatalog, true, 512, JSON_THROW_ON_ERROR);
$newCatalog = preg_replace_callback('/("price"\s*:\s*)(\d+(?:\.\d+)?)/', static function ($match) use ($rate) {
    return $match[1] . number_format(round((float) $match[2] * $rate, 1), 1, '.', '');
}, $oldCatalog, -1, $replaced);
if ($replaced !== count($oldBooks)) throw new RuntimeException('Unexpected catalog price count');
$newBooks = json_decode($newCatalog, true, 512, JSON_THROW_ON_ERROR);
foreach ($oldBooks as $i => $book) {
    unset($book['price']);
    $newBook = $newBooks[$i]; unset($newBook['price']);
    if ($book !== $newBook) throw new RuntimeException('Non-price catalog data changed');
}
$manifest = json_decode($oldManifest, true, 512, JSON_THROW_ON_ERROR);
if ($manifest['catalog_sha256'] !== hash('sha256', $oldCatalog)) throw new RuntimeException('Index manifest was already stale');
// Embedding passages contain searchText only; price changes do not alter vectors.
$manifest['catalog_sha256'] = hash('sha256', $newCatalog);
$newManifest = json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
// OpenCart tables can be MyISAM: retain explicit undo statements as well.
$undo = [];
$restoreColumns = ['product'=>['price'], 'product_discount'=>['price'], 'product_special'=>['price'],
    'product_option_value'=>['price'], 'recurring'=>['price','trial_price'], 'voucher'=>['amount'],
    'voucher_history'=>['amount'], 'customer_transaction'=>['amount'], 'coupon'=>['discount','total'],
    'tax_rate'=>['rate'], 'setting'=>['value'], 'currency'=>['value','status','title','symbol_left','symbol_right','decimal_place','date_modified']];
foreach ($restoreColumns as $table=>$columns) {
    $tableName = DB_PREFIX . $table;
    $keys = array_column($db->query("SHOW KEYS FROM `$tableName` WHERE Key_name='PRIMARY'")->fetch_all(MYSQLI_ASSOC), 'Column_name');
    if (!$keys) throw new RuntimeException('Missing primary key: ' . $tableName);
    foreach ($db->query("SELECT * FROM `$tableName`")->fetch_all(MYSQLI_ASSOC) as $row) {
        $quote = static fn($value) => $value === null ? 'NULL' : "'" . $db->real_escape_string((string)$value) . "'";
        $set = []; $where = [];
        foreach ($columns as $column) $set[] = "`$column`=" . $quote($row[$column]);
        foreach ($keys as $key) $where[] = "`$key`=" . $quote($row[$key]);
        $undo[] = "UPDATE `$tableName` SET " . implode(',', $set) . ' WHERE ' . implode(' AND ', $where);
    }
}
$db->begin_transaction();
try {
    foreach (['product' => ['price'], 'product_discount' => ['price'], 'product_special' => ['price'],
        'product_option_value' => ['price'], 'recurring' => ['price', 'trial_price'],
        'voucher' => ['amount'], 'voucher_history' => ['amount'], 'customer_transaction' => ['amount']] as $table => $columns) {
        foreach ($columns as $column) $db->query('UPDATE ' . DB_PREFIX . $table . " SET `$column`=ROUND(`$column`*$rate,1)");
    }
    $db->query('UPDATE ' . DB_PREFIX . "coupon SET discount=ROUND(discount*$rate,1) WHERE type='F'");
    $db->query('UPDATE ' . DB_PREFIX . "coupon SET total=ROUND(total*$rate,1)");
    $db->query('UPDATE ' . DB_PREFIX . "tax_rate SET rate=ROUND(rate*$rate,1) WHERE type='F'");
    $db->query('UPDATE ' . DB_PREFIX . "setting SET value=ROUND(CAST(value AS DECIMAL(15,4))*$rate,1) WHERE `key` IN ('shipping_flat_cost','config_voucher_min','config_voucher_max')");
    $db->query('UPDATE ' . DB_PREFIX . "setting SET value=GREATEST(CAST(value AS DECIMAL(15,4)),0.1) WHERE `key`='config_voucher_min'");
    $db->query('UPDATE ' . DB_PREFIX . "currency SET value=value/$rate, status=0");
    $db->query('UPDATE ' . DB_PREFIX . "currency SET title='Белорусский рубль',symbol_left='',symbol_right=' р.',decimal_place=1,value=1,status=1,date_modified=NOW() WHERE code='BYN'");
    $db->query('UPDATE ' . DB_PREFIX . "setting SET value='BYN' WHERE `key`='config_currency' AND store_id=0");
    $db->query('UPDATE ' . DB_PREFIX . "setting SET value='0' WHERE `key`='config_currency_auto'");
    if (file_put_contents($catalogPath, $newCatalog) === false || file_put_contents($manifestPath, $newManifest) === false) throw new RuntimeException('Cannot update catalog files');
    $db->commit();
} catch (Throwable $error) {
    $db->rollback();
    foreach ($undo as $sql) $db->query($sql);
    file_put_contents($catalogPath, $oldCatalog);
    file_put_contents($manifestPath, $oldManifest);
    throw $error;
}
echo "Migrated $replaced catalog prices to BYN at $rate; backup: $backup\n";
