<?php

require dirname(__DIR__, 2) . '/system/engine/registry.php';
require dirname(__DIR__, 2) . '/system/library/ml_search.php';

class AlchemyUnavailableTestLog {
    public $messages = array();

    public function write($message) {
        $this->messages[] = (string)$message;
    }
}

$registry = new Registry();
$log = new AlchemyUnavailableTestLog();
$registry->set('log', $log);
$client = new ml_search($registry);
$endpoint = new ReflectionProperty('ml_search', 'endpoint');
$endpoint->setAccessible(true);
$endpoint->setValue($client, 'http://127.0.0.1:1');

$started = microtime(true);
$response = $client->alchemyRecommend(array(
    'positive' => array(array('kind' => 'mood', 'value' => 'уютная')),
    'limit' => 12
));
$elapsed = (microtime(true) - $started) * 1000;
$error = $client->getLastError();

if ($response !== false
    || !isset($error['code'])
    || $error['code'] !== 'service_unavailable'
    || !isset($error['status'])
    || (int)$error['status'] !== 503
    || $elapsed > 1000) {
    fwrite(STDERR, "ML unavailability contract failed\n");
    exit(1);
}

echo "ML unavailability contract passed in " . round($elapsed, 1) . " ms\n";
