<?php
class ModelProductAlchemy extends Model {
	public function addEvent($data) {
		$this->db->query("INSERT INTO `" . DB_PREFIX . "alchemy_event` SET "
			. "anonymous_id = '" . $this->db->escape($data['anonymous_id']) . "', "
			. "customer_id = '" . (int)$data['customer_id'] . "', "
			. "selection_id = '" . $this->db->escape($data['selection_id']) . "', "
			. "event_type = '" . $this->db->escape($data['event_type']) . "', "
			. "product_id = '" . (int)$data['product_id'] . "', "
			. "position = '" . (int)$data['position'] . "', "
			. "recipe_fingerprint = '" . $this->db->escape($data['recipe_fingerprint']) . "', "
			. "recipe_json = '" . $this->db->escape($data['recipe_json']) . "', "
			. "metadata_json = '" . $this->db->escape($data['metadata_json']) . "', "
			. "date_added = NOW(), expires_at = DATE_ADD(NOW(), INTERVAL 180 DAY)");
		return (int)$this->db->getLastId();
	}

	public function deleteExpiredEvents() {
		$this->db->query("DELETE FROM `" . DB_PREFIX . "alchemy_event` WHERE expires_at < NOW() LIMIT 500");
	}
}
