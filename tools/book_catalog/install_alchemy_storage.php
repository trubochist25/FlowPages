<?php

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$root = dirname(__DIR__, 2);
require $root . '/config.php';

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');

$event_table = DB_PREFIX . 'alchemy_event';

$db->query(
    "CREATE TABLE IF NOT EXISTS `{$event_table}` (
        `event_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
        `anonymous_id` char(64) NOT NULL,
        `customer_id` int(10) unsigned NOT NULL DEFAULT '0',
        `selection_id` char(32) NOT NULL DEFAULT '',
        `event_type` varchar(32) NOT NULL,
        `product_id` int(10) unsigned NOT NULL DEFAULT '0',
        `position` tinyint(3) unsigned NOT NULL DEFAULT '0',
        `recipe_fingerprint` char(64) NOT NULL,
        `recipe_json` mediumtext NOT NULL,
        `metadata_json` text NOT NULL,
        `date_added` datetime NOT NULL,
        `expires_at` datetime NOT NULL,
        PRIMARY KEY (`event_id`),
        KEY `event_date` (`event_type`,`date_added`),
        KEY `anonymous_date` (`anonymous_id`,`date_added`),
        KEY `selection_event` (`selection_id`,`event_type`),
        KEY `product_event` (`product_id`,`event_type`),
        KEY `expires_at` (`expires_at`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8"
);

$db->close();
echo "Book Alchemy storage is ready: {$event_table}\n";
