<?php

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$root = dirname(__DIR__, 2);
require $root . '/config.php';

$days = isset($argv[1]) ? (int)$argv[1] : 30;
$days = max(1, min(365, $days));
$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);
$db->set_charset('utf8');
$table = DB_PREFIX . 'alchemy_event';
$since = "DATE_SUB(NOW(), INTERVAL {$days} DAY)";

$counts = array();
$result = $db->query(
    "SELECT event_type, COUNT(*) AS total FROM `{$table}` "
    . "WHERE date_added >= {$since} GROUP BY event_type ORDER BY event_type"
);
foreach ($result->fetch_all(MYSQLI_ASSOC) as $row) {
    $counts[$row['event_type']] = (int)$row['total'];
}

$shown = isset($counts['recommendation_shown']) ? $counts['recommendation_shown'] : 0;

echo "Book Alchemy quality — last {$days} days\n";
echo "Selections shown: {$shown}\n";
foreach (array('product_open', 'wishlist', 'cart') as $type) {
    $value = isset($counts[$type]) ? $counts[$type] : 0;
    echo ucfirst(str_replace('_', ' ', $type)) . ": {$value}\n";
}

echo "\nSignals by result position:\n";
$positions = $db->query(
    "SELECT position, "
    . "SUM(event_type = 'product_open') AS open_count, "
    . "SUM(event_type = 'wishlist') AS wishlist_count, "
    . "SUM(event_type = 'cart') AS cart_count "
    . "FROM `{$table}` WHERE date_added >= {$since} AND position > 0 "
    . "GROUP BY position ORDER BY position"
);
foreach ($positions->fetch_all(MYSQLI_ASSOC) as $row) {
    echo sprintf(
        "#%d open:%d wishlist:%d cart:%d\n",
        $row['position'],
        $row['open_count'],
        $row['wishlist_count'],
        $row['cart_count']
    );
}

$db->close();
