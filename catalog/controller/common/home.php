<?php
class ControllerCommonHome extends Controller {
	public function index() {
		$this->document->setTitle($this->config->get('config_meta_title'));
		$this->document->setDescription($this->config->get('config_meta_description'));
		$this->document->setKeywords($this->config->get('config_meta_keyword'));

		$this->load->model('catalog/product');
		$this->load->model('tool/image');

		if (isset($this->request->get['route'])) {
			$canonical = $this->url->link('common/home');
			if ($this->config->get('config_seo_pro') && !$this->config->get('config_seopro_addslash')) {
				$canonical = rtrim($canonical, '/');
			}
			$this->document->addLink($canonical, 'canonical');
		}

		$data['column_left'] = $this->load->controller('common/column_left');
		$data['column_right'] = $this->load->controller('common/column_right');
		$data['content_top'] = $this->load->controller('common/content_top');
		$data['content_bottom'] = $this->load->controller('common/content_bottom');
		$data['book_rows'] = $this->getBookRows();
		$data['footer'] = $this->load->controller('common/footer');
		$data['header'] = $this->load->controller('common/header');

		$this->response->setOutput($this->load->view('common/home', $data));
	}

	private function getBookRows() {
		$used = array();
		$popular_catalog_url = $this->url->link('product/category', 'path=60&sort=external_rating_count&order=DESC');
		$signals = $this->getRecommendationSignals();
		$balanced_products = $this->getRecommendationProducts($signals, 25, 'balanced', 0);
		$explore_products = $this->getRecommendationProducts($signals, 30, 'explore', 7919);
		$first_row = $this->pickUniqueProducts($balanced_products, $used, 15);
		$explore = $this->pickUniqueProducts($explore_products, $used, 15);

		$popular = $this->pickUniqueProducts(
			$this->model_catalog_product->getProducts(array(
				'sort'  => 'external_rating_count',
				'order' => 'DESC',
				'start' => 0,
				'limit' => 60
			)),
			$used,
			15
		);
		$rows = array();
		if (!empty($first_row)) {
			$rows[] = array(
				'index'     => '01',
				'kicker'    => 'С учётом ваших интересов',
				'title'     => 'Рекомендуем вам',
				'link_text' => 'Все книги',
				'href'      => $this->url->link('product/category', 'path=60'),
				'products'  => $this->formatBookProducts($first_row)
			);
		}

		if (!empty($explore)) {
			$rows[] = array(
				'index'     => '02',
				'kicker'    => 'За пределами привычного',
				'title'     => 'Попробуйте другое',
				'link_text' => 'Исследовать каталог',
				'href'      => $this->url->link('product/category', 'path=60'),
				'products'  => $this->formatBookProducts($explore)
			);
		}

		$rows[] = array(
				'index'     => '03',
				'kicker'    => 'Читатели выбирают',
				'title'     => 'Популярное сейчас',
				'link_text' => 'Больше популярных',
				'href'      => $popular_catalog_url,
				'products'  => $this->formatBookProducts($popular)
			);

		foreach ($rows as &$row) {
			$row['slides'] = array_chunk($row['products'], 5);
		}
		unset($row);

		return array_values(array_filter($rows, function ($row) {
			return !empty($row['products']);
		}));
	}

	private function getRecommendationSignals() {
		try {
			$this->load->model('catalog/recommendation');
			$customer_id = $this->customer->isLogged() ? $this->customer->getId() : 0;
			return $this->model_catalog_recommendation->getSignals($customer_id);
		} catch (Exception $error) {
			$this->log->write('Recommendations: unable to load customer signals: ' . $error->getMessage());
			return array();
		}
	}

	private function getRecommendationProducts($signals, $limit, $strategy, $seed_offset) {
		if (!isset($this->session->data['recommendation_seed'])) {
			try {
				$this->session->data['recommendation_seed'] = random_int(0, 2147483647);
			} catch (Exception $error) {
				$this->session->data['recommendation_seed'] = mt_rand(0, 2147483647);
			}
		}
		$random_seed = ((int)$this->session->data['recommendation_seed'] + (int)$seed_offset) % 2147483648;

		$this->load->library('ml_search');
		$response = $this->ml_search->recommend(array(
			'signals'     => $signals,
			'limit'       => max(1, min(100, (int)$limit)),
			'strategy'    => $strategy,
			'random_seed' => $random_seed
		));

		if (!$response || empty($response['results'])) {
			return array();
		}

		$products = array();
		$seen = array();
		foreach ($response['results'] as $recommendation) {
			$product_id = isset($recommendation['product_id']) ? (int)$recommendation['product_id'] : 0;
			if (!$product_id || isset($seen[$product_id])) {
				continue;
			}
			$product = $this->model_catalog_product->getProduct($product_id);
			if ($product) {
				$seen[$product_id] = true;
				$products[] = $product;
			}
		}

		return $products;
	}

	private function pickUniqueProducts($products, &$used, $limit) {
		$selected = array();

		foreach ($products as $product) {
			$product_id = (int)$product['product_id'];

			if (isset($used[$product_id])) {
				continue;
			}

			$used[$product_id] = true;
			$selected[] = $product;

			if (count($selected) >= $limit) {
				break;
			}
		}

		return $selected;
	}

	private function formatBookProducts($products) {
		$formatted = array();

		foreach ($products as $product) {
			$image = $product['image']
				? $this->model_tool_image->resize($product['image'], 380, 584)
				: $this->model_tool_image->resize('placeholder.png', 380, 584);

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

			$formatted[] = array(
				'product_id'      => (int)$product['product_id'],
				'thumb'           => $image,
				'name'            => $product['name'],
				'author'          => $product['manufacturer'],
				'price'           => $price,
				'special'         => $special,
				'external_rating' => isset($product['external_rating']) ? (float)$product['external_rating'] : 0,
				'href'            => $this->url->link('product/product', 'product_id=' . (int)$product['product_id'])
			);
		}

		return $formatted;
	}
}
