<?php

declare(strict_types=1);

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$root = dirname(__DIR__, 2);
require $root . '/config.php';

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$table = DB_PREFIX . 'customer_product_view';
$db->query(
    "CREATE TABLE IF NOT EXISTS `{$table}` (
        `customer_id` int(11) NOT NULL,
        `product_id` int(11) NOT NULL,
        `view_count` smallint(5) unsigned NOT NULL DEFAULT '1',
        `first_viewed` datetime NOT NULL,
        `last_viewed` datetime NOT NULL,
        PRIMARY KEY (`customer_id`, `product_id`),
        KEY `last_viewed` (`last_viewed`),
        KEY `product_id` (`product_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8"
);
$db->close();

echo "Recommendation history table is ready: {$table}\n";
