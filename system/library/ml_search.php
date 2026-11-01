<?php
/**
 * Small, fail-safe client for the local FlowPages ML search service.
 */
class ml_search {
	private $endpoint = 'http://127.0.0.1:8765';
	private $log;
	private $last_error = array();

	public function __construct($registry) {
		$this->log = $registry->get('log');
	}

	public function search($payload) {
		return $this->request('POST', '/search', $payload, 8);
	}

	public function recommend($payload) {
		return $this->request('POST', '/recommend', $payload, 4);
	}

	public function alchemyAnalyze($payload) {
		return $this->request('POST', '/alchemy/analyze', $payload, 4);
	}

	public function alchemyRecommend($payload) {
		return $this->request('POST', '/alchemy/recommend', $payload, 8);
	}

	public function getLastError() {
		return $this->last_error;
	}

	public function suggest($query, $limit = 8) {
		$parameters = http_build_query(array(
			'q' => (string)$query,
			'limit' => max(1, min(20, (int)$limit))
		), '', '&', PHP_QUERY_RFC3986);

		return $this->request('GET', '/suggest?' . $parameters, null, 2);
	}

	public function facets() {
		return $this->request('GET', '/facets', null, 2);
	}

	private function request($method, $path, $payload = null, $timeout = 5) {
		$this->last_error = array();

		if (!function_exists('curl_init')) {
			$this->writeLog('PHP cURL extension is not available');
			$this->setError('service_unavailable', 'ML service is unavailable', 503);
			return false;
		}

		$handle = curl_init($this->endpoint . $path);
		$options = array(
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_CONNECTTIMEOUT_MS => 300,
			CURLOPT_TIMEOUT => $timeout,
			CURLOPT_HTTPHEADER => array('Accept: application/json'),
		);

		if ($method === 'POST') {
			$body = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

			if ($body === false) {
				$this->writeLog('Unable to encode ML search request');
				$this->setError('encoding_error', 'Unable to prepare ML request', 500);
				curl_close($handle);
				return false;
			}

			$options[CURLOPT_POST] = true;
			$options[CURLOPT_POSTFIELDS] = $body;
			$options[CURLOPT_HTTPHEADER][] = 'Content-Type: application/json';
		}

		curl_setopt_array($handle, $options);
		$response = curl_exec($handle);
		$error = curl_error($handle);
		$status = (int)curl_getinfo($handle, CURLINFO_HTTP_CODE);
		curl_close($handle);

		if ($response === false || $error || $status < 200 || $status >= 300) {
			$decoded = is_string($response) ? json_decode($response, true) : null;
			$details = is_array($decoded) && isset($decoded['detail']) ? $decoded['detail'] : null;

			if ($status === 422) {
				$this->setError('validation_error', 'ML request validation failed', 422, $details);
			} elseif ($status >= 400 && $status < 500) {
				$this->setError('request_rejected', 'ML service rejected the request', $status, $details);
			} else {
				$this->writeLog('Request ' . $path . ' failed: HTTP ' . $status . ($error ? ', ' . $error : ''));
				$this->setError('service_unavailable', 'ML service is unavailable', 503);
			}
			return false;
		}

		$data = json_decode($response, true);

		if (!is_array($data)) {
			$this->writeLog('Request ' . $path . ' returned invalid JSON');
			$this->setError('invalid_response', 'ML service returned invalid data', 502);
			return false;
		}

		return $data;
	}

	private function setError($code, $message, $status, $details = null) {
		$this->last_error = array(
			'code' => (string)$code,
			'message' => (string)$message,
			'status' => (int)$status
		);

		if ($details !== null) {
			$this->last_error['details'] = $details;
		}
	}

	private function writeLog($message) {
		if ($this->log) {
			$this->log->write('ML Search: ' . $message);
		}
	}
}
