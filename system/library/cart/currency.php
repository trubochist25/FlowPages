<?php
namespace Cart;
class Currency {
	private $db;
	private $language;
	private $config;
	private $currencies = array();

	public function __construct($registry) {
		$this->db = $registry->get('db');
		$this->language = $registry->get('language');
		$this->config = $registry->get('config');

		$query = $this->db->query("SELECT * FROM " . DB_PREFIX . "currency");

		foreach ($query->rows as $result) {
			$this->currencies[$result['code']] = array(
				'currency_id'   => $result['currency_id'],
				'title'         => $result['title'],
				'symbol_left'   => $result['symbol_left'],
				'symbol_right'  => $result['symbol_right'],
				'decimal_place' => $result['decimal_place'],
				'value'         => $result['value'],
				'status'        => $result['status']
			);
		}
	}

	private function resolve($currency) {
		if (!isset($this->currencies[$currency]) || !$this->currencies[$currency]['status']) {
			$fallback = $this->config->get('config_currency');

			if (isset($this->currencies[$fallback])) {
				return $fallback;
			}
		}

		return $currency;
	}

	public function format($number, $currency, $value = '', $format = true) {
		$currency = $this->resolve($currency);
		$symbol_left = $this->currencies[$currency]['symbol_left'];
		$symbol_right = $this->currencies[$currency]['symbol_right'];
		$decimal_place = $this->currencies[$currency]['decimal_place'];

		if (!$value) {
			$value = $this->currencies[$currency]['value'];
		}

		$amount = $value ? (float)$number * $value : (float)$number;
		
		$amount = round($amount, (int)$decimal_place);
		
		if (!$format) {
			return $amount;
		}

		$string = '';

		if ($symbol_left) {
			$string .= $symbol_left;
		}

		$string .= number_format($amount, (int)$decimal_place, $this->language->get('decimal_point'), $this->language->get('thousand_point'));

		if ($symbol_right) {
			$string .= $symbol_right;
		}

		return $string;
	}

	public function convert($value, $from, $to) {
		$from = $this->resolve($from);
		$to = $this->resolve($to);

		if (isset($this->currencies[$from])) {
			$from = $this->currencies[$from]['value'];
		} else {
			$from = 1;
		}

		if (isset($this->currencies[$to])) {
			$to = $this->currencies[$to]['value'];
		} else {
			$to = 1;
		}

		return $value * ($to / $from);
	}
	
	public function getId($currency) {
		$currency = $this->resolve($currency);

		if (isset($this->currencies[$currency])) {
			return $this->currencies[$currency]['currency_id'];
		} else {
			return 0;
		}
	}

	public function getSymbolLeft($currency) {
		$currency = $this->resolve($currency);

		if (isset($this->currencies[$currency])) {
			return $this->currencies[$currency]['symbol_left'];
		} else {
			return '';
		}
	}

	public function getSymbolRight($currency) {
		$currency = $this->resolve($currency);

		if (isset($this->currencies[$currency])) {
			return $this->currencies[$currency]['symbol_right'];
		} else {
			return '';
		}
	}

	public function getDecimalPlace($currency) {
		$currency = $this->resolve($currency);

		if (isset($this->currencies[$currency])) {
			return $this->currencies[$currency]['decimal_place'];
		} else {
			return 0;
		}
	}

	public function getValue($currency) {
		$currency = $this->resolve($currency);

		if (isset($this->currencies[$currency])) {
			return $this->currencies[$currency]['value'];
		} else {
			return 0;
		}
	}

	public function has($currency) {
		return isset($this->currencies[$currency]) && $this->currencies[$currency]['status'];
	}
}
