import fs from 'node:fs/promises';
import path from 'node:path';
import { buildSearchText } from './search_text.mjs';

const root = path.resolve(import.meta.dirname, '..', '..');
const dataDir = path.join(root, 'data', 'book_catalog');
const catalogPath = path.join(dataDir, 'catalog.json');
const sourcePath = path.join(dataDir, 'openlibrary-raw.json');
const catalog = JSON.parse(await fs.readFile(catalogPath, 'utf8'));
const source = JSON.parse(await fs.readFile(sourcePath, 'utf8'));
const works = new Map(source.map((work) => [work.key, work]));

for (const book of catalog) {
  book.searchText = buildSearchText(book, works.get(book.workKey) ?? {});
}

await fs.writeFile(catalogPath, JSON.stringify(catalog, null, 2), 'utf8');

const wordCounts = catalog.map((book) => book.searchText.split(/\s+/u).filter(Boolean).length);
const average = wordCounts.reduce((sum, value) => sum + value, 0) / wordCounts.length;
console.log(JSON.stringify({
  books: catalog.length,
  minimumWords: Math.min(...wordCounts),
  averageWords: Number(average.toFixed(1)),
  maximumWords: Math.max(...wordCounts),
  withSourceSubjects: catalog.filter((book) => (works.get(book.workKey)?.subject ?? []).length > 0).length
}, null, 2));
