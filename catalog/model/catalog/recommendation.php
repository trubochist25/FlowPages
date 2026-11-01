<?php
class ModelCatalogRecommendation extends Model {
	public function recordView($customer_id, $product_id) {
		$this->db->query("INSERT INTO " . DB_PREFIX . "customer_product_view SET customer_id = '" . (int)$customer_id . "', product_id = '" . (int)$product_id . "', view_count = '1', first_viewed = NOW(), last_viewed = NOW() ON DUPLICATE KEY UPDATE view_count = LEAST(view_count + 1, 65535), last_viewed = NOW()");
	}

	public function recordSessionView($product_id) {
		$product_id = (int)$product_id;
		$now = time();
		if (!isset($this->session->data['recommendation_views']) || !is_array($this->session->data['recommendation_views'])) {
			$this->session->data['recommendation_views'] = array();
		}

		if (isset($this->session->data['recommendation_views'][$product_id])) {
			$view = $this->session->data['recommendation_views'][$product_id];
			$view['count'] = min(65535, (int)$view['count'] + 1);
			$view['last'] = $now;
		} else {
			$view = array('count' => 1, 'first' => $now, 'last' => $now);
		}
		$this->session->data['recommendation_views'][$product_id] = $view;

		uasort($this->session->data['recommendation_views'], function ($left, $right) {
			return (int)$right['last'] <=> (int)$left['last'];
		});
		$this->session->data['recommendation_views'] = array_slice(
			$this->session->data['recommendation_views'],
			0,
			30,
			true
		);
	}

	public function getSignals($customer_id = 0) {
		$customer_id = (int)$customer_id;
		$signals = $customer_id > 0 ? array() : $this->getSessionViewSignals();

		if ($customer_id > 0) {
			$views = $this->db->query("SELECT product_id, view_count AS strength, TIMESTAMPDIFF(HOUR, last_viewed, NOW()) / 24 AS age_days FROM " . DB_PREFIX . "customer_product_view WHERE customer_id = '" . $customer_id . "' AND last_viewed >= DATE_SUB(NOW(), INTERVAL 90 DAY) ORDER BY last_viewed DESC LIMIT 30");
			foreach ($views->rows as $row) {
				$signals[] = $this->signal($row, 'view');
			}

			$wishlist = $this->db->query("SELECT product_id, 1 AS strength, TIMESTAMPDIFF(HOUR, date_added, NOW()) / 24 AS age_days FROM " . DB_PREFIX . "customer_wishlist WHERE customer_id = '" . $customer_id . "' AND date_added >= DATE_SUB(NOW(), INTERVAL 365 DAY) ORDER BY date_added DESC LIMIT 50");
			foreach ($wishlist->rows as $row) {
				$signals[] = $this->signal($row, 'wishlist');
			}

			$purchases = $this->db->query("SELECT op.product_id, LEAST(SUM(op.quantity), 20) AS strength, TIMESTAMPDIFF(HOUR, MAX(o.date_added), NOW()) / 24 AS age_days FROM " . DB_PREFIX . "order_product op INNER JOIN `" . DB_PREFIX . "order` o ON (o.order_id = op.order_id) WHERE o.customer_id = '" . $customer_id . "' AND o.order_status_id > '0' AND o.date_added >= DATE_SUB(NOW(), INTERVAL 730 DAY) GROUP BY op.product_id ORDER BY MAX(o.date_added) DESC LIMIT 100");
			foreach ($purchases->rows as $row) {
				$signals[] = $this->signal($row, 'purchase');
			}
		} elseif (!empty($this->session->data['wishlist']) && is_array($this->session->data['wishlist'])) {
			foreach (array_slice(array_unique($this->session->data['wishlist']), 0, 50) as $product_id) {
				$signals[] = array(
					'product_id' => (int)$product_id,
					'kind'       => 'wishlist',
					'age_days'   => 0,
					'strength'   => 1
				);
			}
		}

		$cart = $this->db->query("SELECT product_id, LEAST(SUM(quantity), 20) AS strength, TIMESTAMPDIFF(HOUR, MAX(date_added), NOW()) / 24 AS age_days FROM " . DB_PREFIX . "cart WHERE customer_id = '" . $customer_id . "' AND session_id = '" . $this->db->escape($this->session->getId()) . "' GROUP BY product_id ORDER BY MAX(date_added) DESC LIMIT 50");
		foreach ($cart->rows as $row) {
			$signals[] = $this->signal($row, 'cart');
		}

		return $signals;
	}

	private function getSessionViewSignals() {
		$signals = array();
		$views = isset($this->session->data['recommendation_views']) && is_array($this->session->data['recommendation_views'])
			? $this->session->data['recommendation_views']
			: array();
		$minimum_time = time() - 90 * 86400;

		foreach (array_slice($views, 0, 30, true) as $product_id => $view) {
			if (empty($view['last']) || (int)$view['last'] < $minimum_time) {
				continue;
			}
			$signals[] = array(
				'product_id' => (int)$product_id,
				'kind'       => 'view',
				'age_days'   => max(0, (time() - (int)$view['last']) / 86400),
				'strength'   => max(1, (int)$view['count'])
			);
		}

		return $signals;
	}

	private function signal($row, $kind) {
		return array(
			'product_id' => (int)$row['product_id'],
			'kind'       => $kind,
			'age_days'   => max(0, (float)$row['age_days']),
			'strength'   => max(1, (float)$row['strength'])
		);
	}
}
