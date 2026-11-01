-- Idempotent local setup for the defense/demo environment.
DELETE FROM oc_setting
WHERE store_id = 0
  AND code = 'feed_google_sitemap'
  AND `key` = 'feed_google_sitemap_status';

INSERT INTO oc_setting (store_id, code, `key`, value, serialized)
VALUES (0, 'feed_google_sitemap', 'feed_google_sitemap_status', '1', 0);

DELETE FROM oc_seo_url
WHERE store_id = 0
  AND language_id = 1
  AND query = 'product/alchemy';

INSERT INTO oc_seo_url (store_id, language_id, query, keyword)
VALUES (0, 1, 'product/alchemy', 'alchemy');

DELETE FROM oc_seo_url
WHERE store_id = 0
  AND language_id = 2
  AND query = 'product/alchemy';

INSERT INTO oc_seo_url (store_id, language_id, query, keyword)
VALUES (0, 2, 'product/alchemy', 'book-alchemy');

-- ocStore uses 1 to allow indexing and 0 to emit noindex,follow.
UPDATE oc_product SET noindex = 1 WHERE status = 1;
UPDATE oc_category SET noindex = 1 WHERE status = 1;
