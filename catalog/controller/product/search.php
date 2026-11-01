<?php
// *	@source		See SOURCE.txt for OpenCart upstream.
// *	@license	GNU General Public License version 3; see LICENSE.txt

class ControllerProductSearch extends Controller {
	public function index() {
		$this->load->language('product/search');
		$this->load->model('catalog/product');
		$this->load->model('catalog/review');
		$this->load->model('tool/image');
		$this->load->library('ml_search');

		$search = '';
		if (isset($this->request->get['search'])) {
			$search = trim((string)$this->request->get['search']);
		} elseif (isset($this->request->get['tag'])) {
			// Old tag links remain useful, but now pass through the unified search.
			$search = trim((string)$this->request->get['tag']);
		}
		$search = utf8_substr($search, 0, 500);

		$filters = $this->readFilters();
		$filter_count = $this->countActiveFilterGroups($filters);
		$has_filters = $filter_count > 0;

		$allowed_sorts = array('relevance', 'popularity_desc', 'price_asc', 'price_desc', 'rating_external_desc', 'rating_local_desc', 'rating_desc');
		$sort = isset($this->request->get['sort']) ? (string)$this->request->get['sort'] : 'relevance';
		if (!in_array($sort, $allowed_sorts, true)) {
			$sort = 'relevance';
		}
		if ($sort === 'rating_desc') {
			$sort = 'rating_external_desc';
		}

		$page = isset($this->request->get['page']) ? max(1, (int)$this->request->get['page']) : 1;
		$allowed_limits = array(10, 20, 30, 40, 50);
		$limit = isset($this->request->get['limit']) ? (int)$this->request->get['limit'] : 10;
		if (!in_array($limit, $allowed_limits, true)) {
			$limit = 10;
		}

		$this->document->setTitle($search ? 'Поиск — ' . $search : $this->language->get('heading_title'));
		$this->document->setRobots('noindex,follow');

		$data = array();
		$data['breadcrumbs'] = array(
			array(
				'text' => $this->language->get('text_home'),
				'href' => $this->url->link('common/home')
			),
			array(
				'text' => $this->language->get('heading_title'),
				'href' => $this->url->link('product/search', $search ? 'search=' . rawurlencode($search) : '')
			)
		);

		$data['heading_title'] = $this->language->get('heading_title');
		$data['search'] = $search;
		$data['suggest_url'] = $this->url->link('product/search/suggest');
		$data['search_url'] = $this->url->link('product/search');
		$data['filters'] = $filters;
		$data['filter_count'] = $filter_count;
		$data['has_filters'] = $has_filters;
		$data['sort'] = $sort;
		$data['limit'] = $limit;
		$data['products'] = array();
		$data['ml_used'] = false;
		$data['fallback_used'] = false;
		$data['correction_applied'] = false;
		$data['corrected_query'] = '';
		$data['processing_ms'] = 0;
		$data['rating_decimal_point'] = $this->language->get('decimal_point');
		$data['result_state'] = 'welcome';
		$data['empty_title'] = $this->language->get('text_empty');
		$data['empty_message'] = $this->language->get('text_empty_hint');
		$data['partial_notice'] = '';

		$facets = $this->ml_search->facets();
		if ($facets !== false) {
			$this->cache->set('ml_search.facets', $facets);
		} else {
			$facets = $this->cache->get('ml_search.facets');
		}
		$data['facets'] = $this->normaliseFacets($facets);

		$product_total = 0;
		$has_criteria = $search !== '' || $has_filters;

		if ($has_criteria) {
			$local_ratings = $this->config->get('config_review_status')
				? $this->model_catalog_review->getApprovedRatingSummary()
				: array();
			$ml_response = $this->ml_search->search(array(
				'query' => $search,
				'filters' => $filters,
				'sort' => $sort,
				'local_ratings' => (object)$local_ratings,
				'limit' => $limit,
				'offset' => ($page - 1) * $limit,
				'include_debug' => false
			));

			if ($this->isValidSearchResponse($ml_response)) {
				$data['ml_used'] = true;
				$allowed_states = array('results', 'empty_query', 'invalid_query', 'no_matches', 'partial');
				$data['result_state'] = isset($ml_response['state']) && in_array($ml_response['state'], $allowed_states, true)
					? $ml_response['state']
					: 'results';
				$data['correction_applied'] = !empty($ml_response['correction_applied']);
				$data['corrected_query'] = isset($ml_response['corrected_query']) ? (string)$ml_response['corrected_query'] : '';
				$data['processing_ms'] = isset($ml_response['processing_ms']) ? (float)$ml_response['processing_ms'] : 0;
				$product_total = max(0, (int)$ml_response['total']);

				foreach ($ml_response['results'] as $result) {
					if (!isset($result['product_id'])) {
						continue;
					}

					$product = $this->model_catalog_product->getProduct((int)$result['product_id']);
					if ($product) {
						$data['products'][] = $this->formatProduct($product, $result, $search);
					}
				}
			} else {
				$data['fallback_used'] = true;
				$fallback = $this->fallbackSearch($search, $sort, $page, $limit);
				$product_total = $fallback['total'];
				$data['result_state'] = $product_total > 0 ? 'results' : 'no_matches';

				foreach ($fallback['products'] as $product) {
					$data['products'][] = $this->formatProduct(
						$product,
						array('explanation' => array($this->language->get('text_fallback_badge'))),
						$search
					);
				}
			}
		}

		if ($data['result_state'] === 'invalid_query') {
			$data['empty_title'] = $this->language->get('text_invalid_query_title');
			$data['empty_message'] = $this->language->get('text_invalid_query_hint');
		} elseif ($data['result_state'] === 'no_matches' && $has_filters) {
			$data['empty_title'] = $this->language->get('text_empty_filters_title');
			$data['empty_message'] = $this->language->get('text_empty_filters_hint');
		} elseif ($data['result_state'] === 'no_matches') {
			$data['empty_message'] = $this->language->get('text_empty_query_hint');
		} elseif ($data['result_state'] === 'partial') {
			$data['partial_notice'] = $this->language->get('text_partial_results');
		}

		$params = $this->buildQueryParams($search, $filters, $sort, $limit);
		$data['clear_url'] = $this->url->link('product/search', $search ? 'search=' . rawurlencode($search) : '');
		$data['sorts'] = $this->buildSorts($params, $sort);
		$data['limits'] = $this->buildLimits($params, $limit);

		$pagination_params = $params;
		unset($pagination_params['page']);
		$pagination = new Pagination();
		$pagination->total = $product_total;
		$pagination->page = $page;
		$pagination->limit = $limit;
		$pagination->url = $this->url->link(
			'product/search',
			http_build_query($pagination_params, '', '&') . '&page={page}'
		);
		$data['pagination'] = $pagination->render();

		$page_start = $product_total ? (($page - 1) * $limit) + 1 : 0;
		$page_end = min($product_total, $page * $limit);
		$data['results'] = sprintf(
			$this->language->get('text_pagination'),
			$page_start,
			$page_end,
			$product_total,
			$limit ? ceil($product_total / $limit) : 1
		);
		$data['product_total'] = $product_total;
		$data['compare'] = $this->url->link('product/compare');
		$data['example_short_url'] = $this->url->link(
			'product/search',
			'search=' . rawurlencode('короткий страшный детектив')
		);
		$data['example_cozy_url'] = $this->url->link(
			'product/search',
			'search=' . rawurlencode('что-нибудь уютное на вечер')
		);
		$data['example_mystery_url'] = $this->url->link(
			'product/search',
			'search=' . rawurlencode('книга с тайной')
		);
		$data['text_compare'] = sprintf(
			$this->language->get('text_compare'),
			isset($this->session->data['compare']) ? count($this->session->data['compare']) : 0
		);

		$this->recordSearch($search, $product_total);
		$this->assignLanguage($data);

		$data['column_left'] = $this->load->controller('common/column_left');
		$data['column_right'] = $this->load->controller('common/column_right');
		$data['content_top'] = $this->load->controller('common/content_top');
		$data['content_bottom'] = $this->load->controller('common/content_bottom');
		$data['footer'] = $this->load->controller('common/footer');
		$data['header'] = $this->load->controller('common/header');

		$this->response->setOutput($this->load->view('product/search', $data));
	}

	public function suggest() {
		$this->load->model('tool/image');

		$query = isset($this->request->get['q'])
			? trim(strip_tags((string)$this->request->get['q']))
			: '';
		$query = utf8_substr($query, 0, 200);
		$limit = isset($this->request->get['limit'])
			? max(1, min(20, (int)$this->request->get['limit']))
			: 8;

		$output = array(
			'query' => $query,
			'corrected_query' => $query,
			'suggestions' => array()
		);

		if (utf8_strlen($query) >= 2) {
			$this->load->library('ml_search');
			$response = $this->ml_search->suggest($query, $limit);

			if (is_array($response) && isset($response['suggestions']) && is_array($response['suggestions'])) {
				$output['corrected_query'] = isset($response['corrected_query'])
					? (string)$response['corrected_query']
					: $query;

				foreach (array_slice($response['suggestions'], 0, $limit) as $suggestion) {
					$type = isset($suggestion['type']) ? (string)$suggestion['type'] : '';
					$value = isset($suggestion['value']) ? trim((string)$suggestion['value']) : '';
					$label = isset($suggestion['label']) ? trim((string)$suggestion['label']) : $value;

					if (!in_array($type, array('book', 'author', 'genre', 'phrase'), true) || $value === '' || $label === '') {
						continue;
					}

					if ($type === 'book' && !empty($suggestion['product_id'])) {
						$url = $this->url->link('product/product', 'product_id=' . (int)$suggestion['product_id']);
						$image_path = isset($suggestion['image']) ? trim((string)$suggestion['image']) : '';
						$image = $this->model_tool_image->resize(
							$image_path !== '' ? $image_path : 'placeholder.png',
							72,
							104
						);
					} else {
						$url = $this->url->link('product/search', 'search=' . rawurlencode($value));
						$image = null;
					}

					$output['suggestions'][] = array(
						'type' => $type,
						'value' => $value,
						'label' => $label,
						'image' => $image,
						'url' => html_entity_decode($url, ENT_QUOTES, 'UTF-8')
					);
				}
			}
		}

		$this->response->addHeader('Content-Type: application/json; charset=utf-8');
		$this->response->addHeader('Cache-Control: no-store');
		$this->response->setOutput(json_encode($output, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
	}

	private function readFilters() {
		$filters = array(
			'price_min' => $this->readNumber('price_min', false),
			'price_max' => $this->readNumber('price_max', false),
			'authors' => $this->readList('authors'),
			'genres' => $this->readList('genres'),
			'pages_min' => $this->readNumber('pages_min', true),
			'pages_max' => $this->readNumber('pages_max', true),
			'year_min' => $this->readNumber('year_min', true),
			'year_max' => $this->readNumber('year_max', true),
			'age_ratings' => $this->readList('age_ratings'),
			'moods' => $this->readList('moods'),
			'paces' => $this->readList('paces')
		);

		foreach (array('price', 'pages', 'year') as $name) {
			$min = $name . '_min';
			$max = $name . '_max';
			if ($filters[$min] !== null && $filters[$max] !== null && $filters[$min] > $filters[$max]) {
				$value = $filters[$min];
				$filters[$min] = $filters[$max];
				$filters[$max] = $value;
			}
		}

		return $filters;
	}

	private function readNumber($name, $integer) {
		if (!isset($this->request->get[$name]) || $this->request->get[$name] === '') {
			return null;
		}

		$value = str_replace(',', '.', trim((string)$this->request->get[$name]));
		if (!is_numeric($value) || (float)$value < 0) {
			return null;
		}

		return $integer ? (int)$value : round((float)$value, 2);
	}

	private function readList($name) {
		if (!isset($this->request->get[$name])) {
			return array();
		}

		$values = is_array($this->request->get[$name])
			? $this->request->get[$name]
			: array($this->request->get[$name]);
		$clean = array();

		foreach (array_slice($values, 0, 50) as $value) {
			$value = trim(strip_tags((string)$value));
			if ($value !== '') {
				$clean[] = utf8_substr($value, 0, 120);
			}
		}

		return array_values(array_unique($clean));
	}

	private function countActiveFilterGroups($filters) {
		$count = 0;
		foreach (array('price', 'pages', 'year') as $name) {
			if ($filters[$name . '_min'] !== null || $filters[$name . '_max'] !== null) {
				$count++;
			}
		}
		foreach (array('authors', 'genres', 'age_ratings', 'moods', 'paces') as $name) {
			if ($filters[$name]) {
				$count++;
			}
		}
		return $count;
	}

	private function normaliseFacets($facets) {
		$empty = array(
			'price' => array('min' => '', 'max' => ''),
			'pages' => array('min' => '', 'max' => ''),
			'year' => array('min' => '', 'max' => ''),
			'authors' => array(),
			'genres' => array(),
			'age_ratings' => array(),
			'moods' => array(),
			'paces' => array()
		);

		if (!is_array($facets)) {
			return $empty;
		}

		foreach ($empty as $key => $default) {
			if (!isset($facets[$key]) || !is_array($facets[$key])) {
				$facets[$key] = $default;
			}
		}

		return $facets;
	}

	private function isValidSearchResponse($response) {
		return is_array($response)
			&& isset($response['total'])
			&& isset($response['results'])
			&& is_array($response['results']);
	}

	private function fallbackSearch($search, $sort, $page, $limit) {
		$sort_map = array(
			'relevance' => array('p.sort_order', 'ASC'),
			'popularity_desc' => array('external_rating_count', 'DESC'),
			'price_asc' => array('p.price', 'ASC'),
			'price_desc' => array('p.price', 'DESC'),
			'rating_external_desc' => array('external_rating', 'DESC'),
			'rating_local_desc' => array('rating', 'DESC'),
			'rating_desc' => array('rating', 'DESC')
		);
		$mapped = $sort_map[$sort];
		$filter_data = array(
			'filter_name' => $search,
			'filter_tag' => $search,
			'sort' => $mapped[0],
			'order' => $mapped[1],
			'start' => ($page - 1) * $limit,
			'limit' => $limit
		);

		return array(
			'total' => $this->model_catalog_product->getTotalProducts($filter_data),
			'products' => $this->model_catalog_product->getProducts($filter_data)
		);
	}

	private function formatProduct($product, $meta, $search) {
		if ($product['image']) {
			$image = $this->model_tool_image->resize(
				$product['image'],
				380,
				584
			);
		} else {
			$image = $this->model_tool_image->resize(
				'placeholder.png',
				380,
				584
			);
		}

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
			$tax_price = (float)$product['special'];
		} else {
			$special = false;
			$tax_price = (float)$product['price'];
		}

		$tax = $this->config->get('config_tax')
			? $this->currency->format($tax_price, $this->session->data['currency'])
			: false;
		if (isset($meta['external_rating'])) {
			$external_rating = (float)$meta['external_rating'];
			$external_rating_count = isset($meta['external_rating_count']) ? (int)$meta['external_rating_count'] : 0;
		} else {
			$external_rating = (float)$product['external_rating'];
			$external_rating_count = (int)$product['external_rating_count'];
		}
		$local_rating = $this->config->get('config_review_status') ? (float)$product['rating'] : 0.0;
		$local_rating_count = $this->config->get('config_review_status') ? (int)$product['reviews'] : 0;
		$description = preg_replace(
			'/\s+/u',
			' ',
			trim(strip_tags(html_entity_decode($product['description'], ENT_QUOTES, 'UTF-8')))
		);
		$description_limit = 320;
		if (utf8_strlen($description) > $description_limit) {
			$description = utf8_substr($description, 0, $description_limit);
			$last_space = utf8_strrpos($description, ' ');
			if ($last_space !== false && $last_space > 240) {
				$description = utf8_substr($description, 0, $last_space);
			}
			$description = rtrim($description, " \t\n\r\0\x0B,.;:—-") . '…';
		}

		return array(
			'product_id' => (int)$product['product_id'],
			'thumb' => $image,
			'name' => $product['name'],
			'author' => isset($meta['author']) ? (string)$meta['author'] : (string)$product['manufacturer'],
			'description' => $description,
			'price' => $price,
			'special' => $special,
			'tax' => $tax,
			'minimum' => $product['minimum'] > 0 ? $product['minimum'] : 1,
			'external_rating' => round($external_rating, 1),
			'external_rating_count' => $external_rating_count,
			'local_rating' => round($local_rating, 1),
			'local_rating_count' => $local_rating_count,
			'year' => isset($meta['year']) ? (int)$meta['year'] : null,
			'pages' => isset($meta['pages']) ? (int)$meta['pages'] : null,
			'age_rating' => isset($meta['age_rating']) ? (string)$meta['age_rating'] : '',
			'pace' => isset($meta['pace']) ? (string)$meta['pace'] : '',
			'relevance_score' => isset($meta['relevance_score']) ? max(0, min(1, (float)$meta['relevance_score'])) : null,
			'explanation' => isset($meta['explanation']) && is_array($meta['explanation'])
				? array_slice($meta['explanation'], 0, 4)
				: array(),
			'href' => $this->url->link(
				'product/product',
				'product_id=' . (int)$product['product_id'] . ($search ? '&search=' . rawurlencode($search) : '')
			)
		);
	}

	private function buildQueryParams($search, $filters, $sort, $limit) {
		$params = array();
		if ($search !== '') {
			$params['search'] = $search;
		}
		foreach ($filters as $name => $value) {
			if ($value !== null && $value !== array()) {
				$params[$name] = $value;
			}
		}
		$params['sort'] = $sort;
		$params['limit'] = $limit;
		return $params;
	}

	private function buildSorts($params, $selected) {
		$options = array(
			'relevance' => $this->language->get('text_relevance'),
			'popularity_desc' => $this->language->get('text_popularity'),
			'price_asc' => $this->language->get('text_price_asc'),
			'price_desc' => $this->language->get('text_price_desc'),
			'rating_external_desc' => $this->language->get('text_rating_external_desc'),
			'rating_local_desc' => $this->language->get('text_rating_local_desc')
		);
		$sorts = array();

		foreach ($options as $value => $text) {
			$link_params = $params;
			$link_params['sort'] = $value;
			unset($link_params['page']);
			$sorts[] = array(
				'text' => $text,
				'value' => $value,
				'selected' => $selected === $value,
				'href' => $this->url->link('product/search', http_build_query($link_params, '', '&'))
			);
		}
		return $sorts;
	}

	private function buildLimits($params, $selected) {
		$values = array(10, 20, 30, 40, 50);
		$limits = array();

		foreach ($values as $value) {
			if ($value < 1 || $value > 100) {
				continue;
			}
			$link_params = $params;
			$link_params['limit'] = $value;
			unset($link_params['page']);
			$limits[] = array(
				'text' => $value,
				'value' => $value,
				'selected' => (int)$selected === (int)$value,
				'href' => $this->url->link('product/search', http_build_query($link_params, '', '&'))
			);
		}
		return $limits;
	}

	private function recordSearch($search, $product_total) {
		if ($search === '' || !$this->config->get('config_customer_search')) {
			return;
		}

		$this->load->model('account/search');
		$this->model_account_search->addSearch(array(
			'keyword' => $search,
			'category_id' => 0,
			'sub_category' => 0,
			'description' => 0,
			'products' => $product_total,
			'customer_id' => $this->customer->isLogged() ? $this->customer->getId() : 0,
			'ip' => isset($this->request->server['REMOTE_ADDR']) ? $this->request->server['REMOTE_ADDR'] : ''
		));
	}

	private function assignLanguage(&$data) {
		$keys = array(
			'button_cart', 'button_wishlist', 'button_compare', 'text_tax',
			'text_empty', 'text_search_intro', 'text_search_hint', 'text_filters',
			'text_clear_filters', 'text_price', 'text_author', 'text_genre',
			'text_pages', 'text_year', 'text_age', 'text_mood', 'text_pace',
			'text_from', 'text_to', 'text_apply_filters', 'text_results_found',
			'text_ml_label', 'text_fallback_notice', 'text_corrected_query',
			'text_sort', 'text_limit', 'text_explanation', 'text_filter_authors',
			'text_no_facets', 'text_rating_openlibrary', 'text_rating_flowpages',
			'text_external_votes', 'text_local_reviews', 'text_no_local_reviews',
			'text_empty_hint', 'text_empty_query_hint', 'text_empty_filters_title',
			'text_empty_filters_hint', 'text_invalid_query_title',
			'text_invalid_query_hint', 'text_partial_results'
		);
		foreach ($keys as $key) {
			$data[$key] = $this->language->get($key);
		}
	}
}
