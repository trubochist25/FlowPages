<?php
/**
 * Same-origin JSON bridge between the FlowPages storefront and Book Alchemy.
 * The browser never talks to the local Python service directly.
 */
class ControllerProductAlchemy extends Controller {
	const MAX_BODY_BYTES = 65536;

	public function index() {
		$this->load->language('product/alchemy');
		$this->getAnonymousIdHash();

		$this->document->setTitle($this->language->get('meta_title'));
		$this->document->setDescription($this->language->get('meta_description'));
		$this->document->setRobots('index,follow');
		$this->document->addLink($this->url->link('product/alchemy'), 'canonical');

		$data = array();
		$data['breadcrumbs'] = array(
			array(
				'text' => $this->language->get('text_home'),
				'href' => $this->url->link('common/home')
			),
			array(
				'text' => $this->language->get('heading_title'),
				'href' => $this->url->link('product/alchemy')
			)
		);

		$data['analyze_url'] = html_entity_decode($this->url->link('product/alchemy/analyze'), ENT_QUOTES, 'UTF-8');
		$data['recommend_url'] = html_entity_decode($this->url->link('product/alchemy/recommend'), ENT_QUOTES, 'UTF-8');
		$data['suggest_url'] = html_entity_decode($this->url->link('product/alchemy/suggest'), ENT_QUOTES, 'UTF-8');
		$data['event_url'] = html_entity_decode($this->url->link('product/alchemy/event'), ENT_QUOTES, 'UTF-8');
		$data['alchemy_token'] = $this->getCsrfToken();
		$data['rating_decimal_point'] = $this->language->get('decimal_point');
		$this->assignPageLanguage($data);

		$data['content_top'] = $this->load->controller('common/content_top');
		$data['content_bottom'] = $this->load->controller('common/content_bottom');
		$data['footer'] = $this->load->controller('common/footer');
		$data['header'] = $this->load->controller('common/header');

		$this->response->setOutput($this->load->view('product/alchemy', $data));
	}

	public function suggest() {
		$this->load->language('product/alchemy');

		$query = isset($this->request->get['q'])
			? trim(strip_tags((string)$this->request->get['q']))
			: '';
		$query = utf8_substr($query, 0, 200);
		$output = array('success' => true, 'suggestions' => array());

		if (utf8_strlen($query) >= 2) {
			$this->load->library('ml_search');
			$response = $this->ml_search->suggest($query, 20);
			if (!is_array($response) || !isset($response['suggestions']) || !is_array($response['suggestions'])) {
				$this->jsonMlFailure($this->language->get('error_suggest_unavailable'));
				return;
			}

			$this->load->model('catalog/product');
			$this->load->model('tool/image');
			$used = array();
			foreach ($response['suggestions'] as $suggestion) {
				if (!is_array($suggestion) || !isset($suggestion['type']) || $suggestion['type'] !== 'book') {
					continue;
				}
				$product_id = isset($suggestion['product_id']) ? (int)$suggestion['product_id'] : 0;
				if (!$product_id || isset($used[$product_id])) {
					continue;
				}
				$product = $this->model_catalog_product->getProduct($product_id);
				if (!$product) {
					continue;
				}
				$used[$product_id] = true;
				$output['suggestions'][] = array(
					'product_id' => $product_id,
					'title' => $product['name'],
					'author' => $product['manufacturer'],
					'thumb' => $this->model_tool_image->resize(
						$product['image'] ? $product['image'] : 'placeholder.png',
						72,
						104
					),
					'href' => html_entity_decode(
						$this->url->link('product/product', 'product_id=' . $product_id),
						ENT_QUOTES,
						'UTF-8'
					)
				);
				if (count($output['suggestions']) >= 8) {
					break;
				}
			}
		}

		$this->jsonResponse($output);
	}

	public function analyze() {
		$this->load->language('product/alchemy');

		if (!$this->requirePost()) {
			return;
		}

		$input = $this->readJsonBody();
		if ($input === null) {
			return;
		}

		$query = isset($input['query']) ? trim(strip_tags((string)$input['query'])) : '';
		$query = utf8_substr($query, 0, 500);
		if (!$this->hasMeaningfulText($query)) {
			$this->jsonError('query_required', $this->language->get('error_query_required'), 422);
			return;
		}

		$locale = isset($input['locale']) && $input['locale'] === 'en-GB' ? 'en-GB' : 'ru-RU';
		$this->load->library('ml_search');
		$analysis = $this->ml_search->alchemyAnalyze(array(
			'query' => $query,
			'locale' => $locale
		));

		if (!$this->isAnalysisResponse($analysis)) {
			$this->jsonMlFailure($this->language->get('error_analysis_unavailable'));
			return;
		}

		$this->load->model('catalog/product');
		$this->load->model('tool/image');
		$analysis['anchors'] = $this->enrichAnchors($analysis['anchors']);

		$this->jsonResponse(array(
			'success' => true,
			'analysis' => $analysis
		));
	}

	public function recommend() {
		$this->load->language('product/alchemy');

		if (!$this->requirePost()) {
			return;
		}

		$input = $this->readJsonBody();
		if ($input === null) {
			return;
		}

		$payload = $this->normaliseRecipe($input);
		if (!$payload['anchors'] && !$payload['positive'] && !$this->hasMeaningfulText($payload['query'])) {
			$this->jsonError('query_required', $this->language->get('error_query_required'), 422);
			return;
		}
		$payload['random_seed'] = $this->getRecipeSeed($payload);
		$this->load->model('catalog/review');
		$local_ratings = $this->config->get('config_review_status')
			? $this->model_catalog_review->getApprovedRatingSummary()
			: array();
		$payload['local_ratings'] = (object)$local_ratings;
		$payload['include_debug'] = false;

		$this->load->library('ml_search');
		$ranking = $this->ml_search->alchemyRecommend($payload);
		if (!$this->isRankingResponse($ranking)) {
			$this->jsonMlFailure($this->language->get('error_ranking_unavailable'));
			return;
		}

		$this->load->model('catalog/product');
		$this->load->model('tool/image');
		$products = array();
		foreach (array_slice($ranking['results'], 0, 12) as $result) {
			$product_id = isset($result['product_id']) ? (int)$result['product_id'] : 0;
			if (!$product_id) {
				continue;
			}
			$product = $this->model_catalog_product->getProduct($product_id);
			if ($product) {
				$products[] = $this->formatProduct($product, $result);
			}
		}

		$allowed_states = array('results', 'no_candidates', 'partial', 'unavailable');
		$state = isset($ranking['state']) && in_array($ranking['state'], $allowed_states, true)
			? $ranking['state']
			: (count($products) < $payload['limit'] ? 'partial' : 'results');
		$this->jsonResponse(array(
			'success' => true,
			'total' => isset($ranking['total']) ? max(0, (int)$ranking['total']) : 0,
			'count' => count($products),
			'results' => $products,
			'relaxations' => $this->cleanStringList(isset($ranking['relaxations']) ? $ranking['relaxations'] : array(), 4),
			'warnings' => $this->cleanWarnings(isset($ranking['warnings']) ? $ranking['warnings'] : array()),
			'processing_ms' => isset($ranking['processing_ms']) ? max(0, (float)$ranking['processing_ms']) : 0,
			'state' => $state,
			'requested_count' => $payload['limit']
		));
	}

	private function hasMeaningfulText($value) {
		return is_string($value) && preg_match('/[\p{L}\p{N}]/u', $value) === 1;
	}

	public function event() {
		$this->load->language('product/alchemy');
		if (!$this->requirePost()) {
			return;
		}
		$input = $this->readJsonBody();
		if ($input === null || !$this->requireAlchemyToken($input)) {
			return;
		}
		if (!$this->allowEvent()) {
			$this->jsonError('rate_limited', $this->language->get('error_event_rate'), 429);
			return;
		}

		$allowed = array(
			'analysis_complete', 'ingredient_add', 'ingredient_remove', 'weight_change',
			'anchor_add', 'anchor_remove', 'recommendation_shown', 'product_open',
			'wishlist', 'cart'
		);
		$event_type = isset($input['event_type']) ? trim((string)$input['event_type']) : '';
		if (!in_array($event_type, $allowed, true)) {
			$this->jsonError('invalid_event', $this->language->get('error_invalid_event'), 422);
			return;
		}

		$recipe = $this->normaliseAnalyticsRecipe(isset($input['recipe']) ? $input['recipe'] : array());
		$recipe_json = $this->encodeJson($recipe);
		$selection_id = isset($input['selection_id']) ? strtolower(trim((string)$input['selection_id'])) : '';
		if (!preg_match('/^[a-f0-9]{32}$/', $selection_id)) {
			$selection_id = '';
		}
		$product_id = isset($input['product_id']) ? max(0, (int)$input['product_id']) : 0;
		$position = isset($input['position']) ? max(0, min(255, (int)$input['position'])) : 0;
		$this->load->model('product/alchemy');
		$event_data = array(
			'anonymous_id' => $this->getAnonymousIdHash(),
			'customer_id' => $this->getCustomerId(),
			'selection_id' => $selection_id,
			'event_type' => $event_type,
			'product_id' => $product_id,
			'position' => $position,
			'recipe_fingerprint' => hash('sha256', $recipe_json),
			'recipe_json' => $recipe_json,
			'metadata_json' => $this->encodeJson($this->normaliseEventMetadata(isset($input['metadata']) ? $input['metadata'] : array()))
		);
		$this->model_product_alchemy->addEvent($event_data);
		if (mt_rand(1, 100) === 1) {
			$this->model_product_alchemy->deleteExpiredEvents();
		}
		$this->jsonResponse(array('success' => true));
	}

	private function requirePost() {
		if (!isset($this->request->server['REQUEST_METHOD']) || $this->request->server['REQUEST_METHOD'] !== 'POST') {
			$this->response->addHeader('Allow: POST');
			$this->jsonError('method_not_allowed', $this->language->get('error_method_not_allowed'), 405);
			return false;
		}
		$content_type = isset($this->request->server['CONTENT_TYPE'])
			? strtolower(trim((string)$this->request->server['CONTENT_TYPE']))
			: '';
		if (strpos($content_type, 'application/json') !== 0) {
			$this->jsonError('unsupported_media_type', $this->language->get('error_json_required'), 415);
			return false;
		}
		return true;
	}

	private function readJsonBody() {
		$length = isset($this->request->server['CONTENT_LENGTH'])
			? (int)$this->request->server['CONTENT_LENGTH']
			: 0;
		if ($length > self::MAX_BODY_BYTES) {
			$this->jsonError('payload_too_large', $this->language->get('error_payload_too_large'), 413);
			return null;
		}

		$raw = file_get_contents('php://input');
		if ($raw === false || strlen($raw) > self::MAX_BODY_BYTES) {
			$this->jsonError('payload_too_large', $this->language->get('error_payload_too_large'), 413);
			return null;
		}

		$input = json_decode($raw, true);
		if (!is_array($input) || json_last_error() !== JSON_ERROR_NONE) {
			$this->jsonError('invalid_json', $this->language->get('error_invalid_json'), 400);
			return null;
		}
		return $input;
	}

	private function normaliseRecipe($input) {
		$query = isset($input['query']) ? trim(strip_tags((string)$input['query'])) : '';
		$residual_query = array_key_exists('residual_query', $input)
			? trim(strip_tags((string)$input['residual_query']))
			: null;
		$surprise = isset($input['surprise']) && is_numeric($input['surprise'])
			? (float)$input['surprise']
			: 0.35;
		$limit = isset($input['limit']) && is_numeric($input['limit'])
			? (int)$input['limit']
			: 12;

		return array(
			'query' => utf8_substr($query, 0, 500),
			'residual_query' => $residual_query === null ? null : utf8_substr($residual_query, 0, 500),
			'anchors' => $this->normaliseAnchors(isset($input['anchors']) ? $input['anchors'] : array()),
			'positive' => $this->normaliseIngredients(isset($input['positive']) ? $input['positive'] : array(), false),
			'negative' => $this->normaliseIngredients(isset($input['negative']) ? $input['negative'] : array(), true),
			'filters' => $this->normaliseFilters(isset($input['filters']) ? $input['filters'] : array()),
			'surprise' => max(0, min(1, $surprise)),
			'limit' => max(6, min(12, $limit))
		);
	}

	private function normaliseAnchors($anchors) {
		if (!is_array($anchors)) {
			return array();
		}
		$output = array();
		foreach (array_slice($anchors, 0, 3) as $anchor) {
			if (!is_array($anchor)) {
				continue;
			}
			$aspects = isset($anchor['aspects']) && is_array($anchor['aspects'])
				? $this->cleanStringList($anchor['aspects'], 5)
				: array();
			$output[] = array(
				'product_id' => isset($anchor['product_id']) ? (int)$anchor['product_id'] : 0,
				'weight' => isset($anchor['weight']) && is_numeric($anchor['weight']) ? (float)$anchor['weight'] : 1.0,
				'aspects' => $aspects
			);
		}
		return $output;
	}

	private function normaliseIngredients($ingredients, $negative) {
		if (!is_array($ingredients)) {
			return array();
		}
		$output = array();
		foreach (array_slice($ingredients, 0, 20) as $ingredient) {
			if (!is_array($ingredient)) {
				continue;
			}
			$item = array(
				'kind' => isset($ingredient['kind']) ? trim((string)$ingredient['kind']) : '',
				'value' => isset($ingredient['value']) ? utf8_substr(trim(strip_tags((string)$ingredient['value'])), 0, 120) : '',
				'weight' => isset($ingredient['weight']) && is_numeric($ingredient['weight']) ? (float)$ingredient['weight'] : 1.0
			);
			if ($negative) {
				$item['mode'] = isset($ingredient['mode']) && $ingredient['mode'] === 'exclude' ? 'exclude' : 'avoid';
			}
			$output[] = $item;
		}
		return $output;
	}

	private function normaliseFilters($filters) {
		if (!is_array($filters)) {
			$filters = array();
		}
		$output = array('in_stock' => !isset($filters['in_stock']) || (bool)$filters['in_stock']);
		foreach (array('price_min', 'price_max', 'pages_min', 'pages_max', 'year_min', 'year_max') as $name) {
			if (isset($filters[$name]) && $filters[$name] !== '' && is_numeric($filters[$name])) {
				$output[$name] = strpos($name, 'price_') === 0 ? (float)$filters[$name] : (int)$filters[$name];
			}
		}
		foreach (array('authors', 'genres', 'age_ratings', 'moods', 'paces') as $name) {
			$output[$name] = isset($filters[$name]) && is_array($filters[$name])
				? $this->cleanStringList($filters[$name], 50)
				: array();
		}
		return $output;
	}

	private function getRecipeSeed($recipe) {
		$encoded = $this->encodeJson($recipe);
		return (int)hexdec(substr(hash_hmac('sha256', $encoded, DB_PASSWORD . '|alchemy-seed'), 0, 7));
	}

	private function getCustomerId() {
		return $this->customer->isLogged() ? (int)$this->customer->getId() : 0;
	}

	private function getCsrfToken() {
		if (!isset($this->session->data['alchemy_csrf']) || !preg_match('/^[a-f0-9]{32}$/', $this->session->data['alchemy_csrf'])) {
			$this->session->data['alchemy_csrf'] = $this->randomToken(16);
		}
		return $this->session->data['alchemy_csrf'];
	}

	private function requireAlchemyToken($input) {
		$provided = isset($input['_token']) ? strtolower(trim((string)$input['_token'])) : '';
		$expected = $this->getCsrfToken();
		if ($provided === '' || !hash_equals($expected, $provided)) {
			$this->jsonError('invalid_token', $this->language->get('error_invalid_token'), 403);
			return false;
		}
		return true;
	}

	private function getAnonymousIdHash() {
		$cookie_name = 'alchemy_aid';
		$token = isset($this->request->cookie[$cookie_name])
			? strtolower(trim((string)$this->request->cookie[$cookie_name]))
			: '';
		if (!preg_match('/^[a-f0-9]{64}$/', $token)) {
			$token = $this->randomToken(32);
			$https = isset($this->request->server['HTTPS'])
				? strtolower(trim((string)$this->request->server['HTTPS']))
				: '';
			$secure = in_array($https, array('on', '1'), true)
				|| (isset($this->request->server['SERVER_PORT']) && (int)$this->request->server['SERVER_PORT'] === 443);
			setcookie($cookie_name, $token, time() + 31536000, '/', '', $secure, true);
			$this->request->cookie[$cookie_name] = $token;
		}
		return hash('sha256', $token);
	}

	private function randomToken($bytes) {
		if (function_exists('random_bytes')) {
			try {
				return bin2hex(random_bytes($bytes));
			} catch (Exception $error) {
				// Fall through to the OpenSSL-compatible path used by PHP 5.6.
			}
		}
		if (function_exists('openssl_random_pseudo_bytes')) {
			$value = openssl_random_pseudo_bytes($bytes);
			if ($value !== false) {
				return bin2hex($value);
			}
		}
		return substr(hash('sha256', uniqid((string)mt_rand(), true) . microtime(true)), 0, $bytes * 2);
	}

	private function allowEvent() {
		$minute = (int)floor(time() / 60);
		if (!isset($this->session->data['alchemy_event_rate'])
			|| !is_array($this->session->data['alchemy_event_rate'])
			|| $this->session->data['alchemy_event_rate']['minute'] !== $minute) {
			$this->session->data['alchemy_event_rate'] = array('minute' => $minute, 'count' => 0);
		}
		$this->session->data['alchemy_event_rate']['count']++;
		return $this->session->data['alchemy_event_rate']['count'] <= 120;
	}

	private function normaliseAnalyticsRecipe($input) {
		$recipe = $this->normaliseRecipe(is_array($input) ? $input : array());
		unset($recipe['query']);
		unset($recipe['limit']);
		return $recipe;
	}

	private function normaliseEventMetadata($metadata) {
		if (!is_array($metadata)) {
			return array();
		}
		$output = array();
		foreach (array('ingredient_kind', 'ingredient_side', 'source', 'band') as $name) {
			if (isset($metadata[$name])) {
				$output[$name] = utf8_substr(trim(strip_tags((string)$metadata[$name])), 0, 32);
			}
		}
		foreach (array('weight', 'previous_weight', 'result_count') as $name) {
			if (isset($metadata[$name]) && is_numeric($metadata[$name])) {
				$output[$name] = (float)$metadata[$name];
			}
		}
		if (isset($metadata['result_product_ids']) && is_array($metadata['result_product_ids'])) {
			$output['result_product_ids'] = array();
			foreach (array_slice($metadata['result_product_ids'], 0, 12) as $product_id) {
				$product_id = (int)$product_id;
				if ($product_id > 0) {
					$output['result_product_ids'][] = $product_id;
				}
			}
		}
		return $output;
	}

	private function encodeJson($value) {
		$options = defined('JSON_UNESCAPED_UNICODE') ? JSON_UNESCAPED_UNICODE : 0;
		$encoded = json_encode($value, $options);
		return $encoded === false ? '{}' : $encoded;
	}

	private function enrichAnchors($anchors) {
		$output = array();
		foreach (array_slice(is_array($anchors) ? $anchors : array(), 0, 3) as $anchor) {
			$product_id = isset($anchor['product_id']) ? (int)$anchor['product_id'] : 0;
			$product = $product_id ? $this->model_catalog_product->getProduct($product_id) : false;
			if (!$product) {
				continue;
			}
			$anchor['title'] = $product['name'];
			$anchor['author'] = $product['manufacturer'];
			$anchor['thumb'] = $this->model_tool_image->resize(
				$product['image'] ? $product['image'] : 'placeholder.png',
				96,
				148
			);
			$anchor['href'] = html_entity_decode(
				$this->url->link('product/product', 'product_id=' . $product_id),
				ENT_QUOTES,
				'UTF-8'
			);
			$output[] = $anchor;
		}
		return $output;
	}

	private function formatProduct($product, $result) {
		$image = $this->model_tool_image->resize(
			$product['image'] ? $product['image'] : 'placeholder.png',
			380,
			584
		);
		if ($this->customer->isLogged() || !$this->config->get('config_customer_price')) {
			$price = $this->currency->format(
				$this->tax->calculate($product['price'], $product['tax_class_id'], $this->config->get('config_tax')),
				$this->session->data['currency']
			);
		} else {
			$price = false;
		}
		if (!is_null($product['special']) && (float)$product['special'] >= 0) {
			$special = $this->currency->format(
				$this->tax->calculate($product['special'], $product['tax_class_id'], $this->config->get('config_tax')),
				$this->session->data['currency']
			);
		} else {
			$special = false;
		}
		$band = isset($result['band']) && in_array($result['band'], array('close', 'balanced', 'bold'), true)
			? $result['band']
			: 'balanced';

		return array(
			'product_id' => (int)$product['product_id'],
			'thumb' => $image,
			'name' => $product['name'],
			'author' => $product['manufacturer'],
			'price' => $price,
			'special' => $special,
			'minimum' => $product['minimum'] > 0 ? (int)$product['minimum'] : 1,
			'external_rating' => isset($product['external_rating']) ? (float)$product['external_rating'] : 0,
			'local_rating' => $this->config->get('config_review_status') ? (float)$product['rating'] : 0,
			'local_rating_count' => $this->config->get('config_review_status') ? (int)$product['reviews'] : 0,
			'relevance_score' => isset($result['relevance_score']) ? max(0, min(1, (float)$result['relevance_score'])) : 0,
			'band' => $band,
			'matched' => $this->cleanStringList(isset($result['matched']) ? $result['matched'] : array(), 8),
			'unmet' => $this->cleanStringList(isset($result['unmet']) ? $result['unmet'] : array(), 8),
			'relaxations' => $this->cleanStringList(isset($result['relaxations']) ? $result['relaxations'] : array(), 4),
			'reasons' => $this->cleanStringList(isset($result['reasons']) ? $result['reasons'] : array(), 4),
			'href' => html_entity_decode(
				$this->url->link('product/product', 'product_id=' . (int)$product['product_id']),
				ENT_QUOTES,
				'UTF-8'
			)
		);
	}

	private function cleanStringList($values, $limit) {
		$output = array();
		if (!is_array($values)) {
			return $output;
		}
		foreach (array_slice($values, 0, $limit) as $value) {
			$value = utf8_substr(trim(strip_tags((string)$value)), 0, 120);
			if ($value !== '' && !in_array($value, $output, true)) {
				$output[] = $value;
			}
		}
		return $output;
	}

	private function cleanWarnings($warnings) {
		$output = array();
		if (!is_array($warnings)) {
			return $output;
		}
		foreach (array_slice($warnings, 0, 8) as $warning) {
			if (!is_array($warning) || empty($warning['code'])) {
				continue;
			}
			$output[] = array(
				'code' => utf8_substr(trim((string)$warning['code']), 0, 64),
				'message' => isset($warning['message']) ? utf8_substr(trim(strip_tags((string)$warning['message'])), 0, 300) : ''
			);
		}
		return $output;
	}

	private function assignPageLanguage(&$data) {
		$keys = array(
			'heading_title', 'text_kicker', 'text_intro', 'text_privacy',
			'text_step_request', 'text_request_help', 'text_query_label',
			'text_query_placeholder', 'text_examples', 'text_example_one',
			'text_example_two', 'text_example_three', 'button_analyze',
			'text_step_recipe', 'text_recipe_help', 'text_recipe_empty',
			'text_positive', 'text_negative', 'text_anchors', 'text_filters', 'text_filters_kicker',
			'text_surprise', 'text_surprise_help', 'text_surprise_precise',
			'text_surprise_balanced', 'text_surprise_brave', 'text_surprise_wild',
			'text_anchor_search', 'text_anchor_placeholder', 'text_anchor_empty',
			'text_anchor_limit', 'text_anchor_aspects', 'text_anchor_aspects_hint',
			'text_anchor_aspects_placeholder',
			'text_kind', 'text_value', 'text_weight', 'text_mode', 'text_avoid',
			'text_exclude', 'text_add_positive', 'text_add_negative',
			'text_kind_genre', 'text_kind_theme', 'text_kind_mood',
			'text_kind_pace', 'text_kind_style', 'text_kind_content',
			'text_kind_audience', 'text_kind_freeform', 'text_price',
			'text_pages', 'text_year', 'text_age', 'text_any_age', 'text_from',
			'text_to', 'text_in_stock', 'button_mix', 'button_remove',
			'text_step_results', 'text_results_help', 'text_results_empty',
			'text_results_count', 'text_band_close', 'text_band_balanced',
			'text_band_bold', 'text_matched',
			'text_rating_flowpages', 'text_no_local_reviews', 'button_cart',
			'button_wishlist', 'text_analyzing', 'text_mixing', 'text_dirty',
			'text_analysis_ready', 'text_mix_ready', 'text_relaxations',
			'text_ritual_kicker', 'text_ritual_title', 'text_ritual_phase_intent',
			'text_ritual_phase_balance', 'text_ritual_phase_catalog', 'text_ritual_complete',
			'text_no_results', 'text_retry', 'error_generic', 'error_anchor_limit',
			'text_no_results_filters', 'text_partial_results',
			'error_duplicate', 'error_ingredient_required', 'error_query_required',
			'error_invalid_token', 'error_event_rate', 'error_invalid_event'
		);
		foreach ($keys as $key) {
			$data[$key] = $this->language->get($key);
		}
	}

	private function isAnalysisResponse($response) {
		return is_array($response)
			&& isset($response['normalized_query'])
			&& isset($response['positive'])
			&& is_array($response['positive'])
			&& isset($response['negative'])
			&& is_array($response['negative'])
			&& isset($response['anchors'])
			&& is_array($response['anchors']);
	}

	private function isRankingResponse($response) {
		return is_array($response)
			&& isset($response['total'])
			&& isset($response['results'])
			&& is_array($response['results']);
	}

	private function jsonMlFailure($fallback_message) {
		$error = $this->ml_search->getLastError();
		$code = isset($error['code']) ? (string)$error['code'] : 'service_unavailable';
		$status = isset($error['status']) ? (int)$error['status'] : 503;
		$message = $fallback_message;
		if ($code === 'validation_error' || $code === 'request_rejected') {
			$message = $this->language->get('error_invalid_recipe');
		}
		$details = isset($error['details']) ? $this->cleanErrorDetails($error['details']) : null;
		$this->jsonError($code, $message, $status, $details);
	}

	private function cleanErrorDetails($details) {
		if (isset($details['code'])) {
			return array(
				'code' => utf8_substr(trim((string)$details['code']), 0, 64),
				'message' => isset($details['message']) ? utf8_substr(trim(strip_tags((string)$details['message'])), 0, 200) : ''
			);
		}
		if (!is_array($details)) {
			return null;
		}
		$output = array();
		foreach (array_slice($details, 0, 5) as $detail) {
			if (!is_array($detail)) {
				continue;
			}
			$output[] = array(
				'field' => isset($detail['loc']) && is_array($detail['loc']) ? implode('.', array_map('strval', $detail['loc'])) : '',
				'message' => isset($detail['msg']) ? utf8_substr(trim(strip_tags((string)$detail['msg'])), 0, 200) : '',
				'type' => isset($detail['type']) ? utf8_substr(trim((string)$detail['type']), 0, 80) : ''
			);
		}
		return $output;
	}

	private function jsonError($code, $message, $status, $details = null) {
		$error = array(
			'code' => (string)$code,
			'message' => (string)$message
		);
		if ($details !== null) {
			$error['details'] = $details;
		}
		$this->jsonResponse(array('success' => false, 'error' => $error), $status);
	}

	private function jsonResponse($data, $status = 200) {
		$reasons = array(
			200 => 'OK',
			400 => 'Bad Request',
			403 => 'Forbidden',
			405 => 'Method Not Allowed',
			429 => 'Too Many Requests',
			413 => 'Payload Too Large',
			415 => 'Unsupported Media Type',
			422 => 'Unprocessable Entity',
			500 => 'Internal Server Error',
			502 => 'Bad Gateway',
			503 => 'Service Unavailable'
		);
		$protocol = isset($this->request->server['SERVER_PROTOCOL'])
			? $this->request->server['SERVER_PROTOCOL']
			: 'HTTP/1.1';
		if ($status !== 200) {
			$this->response->addHeader($protocol . ' ' . $status . ' ' . (isset($reasons[$status]) ? $reasons[$status] : 'Error'));
		}
		$this->response->addHeader('Content-Type: application/json; charset=utf-8');
		$this->response->addHeader('Cache-Control: no-store');
		$this->response->addHeader('X-Content-Type-Options: nosniff');
		$this->response->setOutput(json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
	}
}
