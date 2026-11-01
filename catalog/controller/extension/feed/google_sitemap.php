<?php
class ControllerExtensionFeedGoogleSitemap extends Controller {
	public function index() {
		if (!$this->config->get('feed_google_sitemap_status')) {
			return;
		}

		$output  = '<?xml version="1.0" encoding="UTF-8"?>';
		$output .= '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">';
		$output .= $this->urlEntry($this->url->link('common/home'), 'daily', '1.0');
		$output .= $this->urlEntry($this->url->link('product/alchemy'), 'weekly', '0.8');

		$this->load->model('catalog/product');
		$products = $this->model_catalog_product->getProducts();

		foreach ($products as $product) {
			$last_modified = !empty($product['date_modified'])
				? date('Y-m-d\TH:i:sP', strtotime($product['date_modified']))
				: '';
			$output .= $this->urlEntry(
				$this->url->link('product/product', 'product_id=' . (int)$product['product_id']),
				'weekly',
				'0.9',
				$last_modified
			);
		}

		$this->load->model('catalog/category');
		$output .= $this->getCategories(0);

		$this->load->model('catalog/information');
		$informations = $this->model_catalog_information->getInformations();

		foreach ($informations as $information) {
			$output .= $this->urlEntry(
				$this->url->link('information/information', 'information_id=' . (int)$information['information_id']),
				'monthly',
				'0.5'
			);
		}

		$output .= '</urlset>';

		$this->response->addHeader('Content-Type: application/xml; charset=utf-8');
		$this->response->addHeader('Cache-Control: public, max-age=3600');
		$this->response->setOutput($output);
	}

	protected function getCategories($parent_id, $current_path = '') {
		$output = '';
		$results = $this->model_catalog_category->getCategories($parent_id);

		foreach ($results as $result) {
			$new_path = $current_path
				? $current_path . '_' . (int)$result['category_id']
				: (string)(int)$result['category_id'];

			$output .= $this->urlEntry(
				$this->url->link('product/category', 'path=' . $new_path),
				'weekly',
				'0.7'
			);
			$output .= $this->getCategories($result['category_id'], $new_path);
		}

		return $output;
	}

	private function urlEntry($url, $change_frequency, $priority, $last_modified = '') {
		$output = '<url>';
		$output .= '<loc>' . htmlspecialchars($url, ENT_QUOTES, 'UTF-8') . '</loc>';
		if ($last_modified !== '') {
			$output .= '<lastmod>' . htmlspecialchars($last_modified, ENT_QUOTES, 'UTF-8') . '</lastmod>';
		}
		$output .= '<changefreq>' . $change_frequency . '</changefreq>';
		$output .= '<priority>' . $priority . '</priority>';
		$output .= '</url>';
		return $output;
	}
}
