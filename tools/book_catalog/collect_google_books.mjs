import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..', '..');
const dataDir = path.join(root, 'data', 'book_catalog');
const rawDir = path.join(dataDir, 'raw');
const pages = 60;
const limit = 100;
const fields = [
  'key', 'title', 'author_name', 'first_publish_year', 'cover_i',
  'ratings_count', 'ratings_average', 'subject', 'number_of_pages_median',
  'readinglog_count', 'edition_count', 'editions', 'editions.key',
  'editions.title', 'editions.cover_i', 'editions.isbn',
  'editions.number_of_pages', 'editions.language', 'editions.publish_date'
].join(',');

await fs.mkdir(rawDir, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const all = [];
const failures = [];

async function fetchWithRetry(url, attempts = 4) {
  let lastError;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          'User-Agent': 'FlowPages-Demo-Catalog/1.0 (local educational project)'
        }
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      lastError = error;
      await sleep(attempt * 1200);
    }
  }

  throw lastError;
}

for (let page = 1; page <= pages; page += 1) {
  const params = new URLSearchParams({
    q: 'language:rus',
    lang: 'ru',
    sort: 'readinglog',
    page: String(page),
    limit: String(limit),
    fields
  });
  const url = `https://openlibrary.org/search.json?${params}`;
  const file = path.join(rawDir, `openlibrary-${String(page).padStart(3, '0')}.json`);

  try {
    let payload;

    try {
      payload = JSON.parse(await fs.readFile(file, 'utf8'));
    } catch {
      payload = await fetchWithRetry(url);
      await fs.writeFile(file, JSON.stringify(payload, null, 2), 'utf8');
    }

    for (let rank = 0; rank < (payload.docs ?? []).length; rank += 1) {
      all.push({
        sourceRank: (page - 1) * limit + rank,
        ...payload.docs[rank]
      });
    }

    process.stdout.write(`[${page}/${pages}] ${(payload.docs ?? []).length} works\n`);
  } catch (error) {
    failures.push({ page, error: error.message });
    process.stderr.write(`[${page}/${pages}] ${error.message}\n`);
  }

  await sleep(250);
}

await fs.writeFile(
  path.join(dataDir, 'openlibrary-raw.json'),
  JSON.stringify(all, null, 2),
  'utf8'
);
await fs.writeFile(
  path.join(dataDir, 'collection-report.json'),
  JSON.stringify({ pages, limit, items: all.length, failures }, null, 2),
  'utf8'
);

console.log(`Collected ${all.length} records; failed pages: ${failures.length}`);
