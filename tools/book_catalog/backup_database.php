<?php

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/config.php';

$output = $argv[1] ?? null;

if (!$output) {
    fwrite(STDERR, "Usage: php backup_database.php <output.sql>\n");
    exit(1);
}

$db = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int) DB_PORT);

if ($db->connect_errno) {
    fwrite(STDERR, "Database connection failed: {$db->connect_error}\n");
    exit(2);
}

$db->set_charset('utf8');
$tables = [];
$result = $db->query('SHOW TABLES');

while ($row = $result->fetch_row()) {
    $tables[] = $row[0];
}

$handle = fopen($output, 'wb');

if (!$handle) {
    fwrite(STDERR, "Cannot open backup file: {$output}\n");
    exit(3);
}

fwrite($handle, "-- OpenCart database backup\n");
fwrite($handle, '-- Created: ' . date(DATE_ATOM) . "\n\n");
fwrite($handle, "SET NAMES utf8;\nSET FOREIGN_KEY_CHECKS=0;\n\n");

foreach ($tables as $table) {
    $quotedTable = '`' . str_replace('`', '``', $table) . '`';
    $createResult = $db->query("SHOW CREATE TABLE {$quotedTable}");
    $create = $createResult->fetch_row()[1];

    fwrite($handle, "DROP TABLE IF EXISTS {$quotedTable};\n{$create};\n\n");

    $dataResult = $db->query("SELECT * FROM {$quotedTable}", MYSQLI_USE_RESULT);

    while ($row = $dataResult->fetch_assoc()) {
        $columns = [];
        $values = [];

        foreach ($row as $column => $value) {
            $columns[] = '`' . str_replace('`', '``', $column) . '`';
            $values[] = $value === null
                ? 'NULL'
                : "'" . $db->real_escape_string((string) $value) . "'";
        }

        fwrite(
            $handle,
            "INSERT INTO {$quotedTable} (" . implode(',', $columns) . ') VALUES (' .
            implode(',', $values) . ");\n"
        );
    }

    $dataResult->free();
    fwrite($handle, "\n");
}

fwrite($handle, "SET FOREIGN_KEY_CHECKS=1;\n");
fclose($handle);

echo "Backup written to {$output}\n";
