<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
require dirname(__DIR__, 2) . '/config.php';

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$prefix = DB_PREFIX;

$db->query(
    "UPDATE {$prefix}currency
     SET status=CASE WHEN code='BYN' THEN 1 ELSE 0 END,
         value=CASE WHEN code='BYN' THEN 1.00000000 ELSE value END"
);
$db->query(
    "UPDATE {$prefix}setting
     SET value='BYN'
     WHERE store_id=0 AND `key`='config_currency'"
);

echo "Store currency configured: BYN\n";
