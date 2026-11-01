import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..', '..');
const catalogPath = path.join(root, 'data', 'book_catalog', 'catalog.json');
const outputPath = path.join(root, 'data', 'book_catalog', 'work-metadata-cache.json');
const catalog = JSON.parse(await fs.readFile(catalogPath, 'utf8'));

let cache = {};
try {
  cache = JSON.parse(await fs.readFile(outputPath, 'utf8'));
} catch {
  cache = {};
}

function textValue(value) {
  if (typeof value === 'string') return value.trim();
  if (value && typeof value.value === 'string') return value.value.trim();
  return '';
}

async function persist() {
  await fs.writeFile(outputPath, `${JSON.stringify(cache, null, 2)}\n`, 'utf8');
}

async function fetchWork(book) {
  const url = `https://openlibrary.org${book.workKey}.json`;
  let lastError = '';
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { 'User-Agent': 'Bookstore-ML-Demo/1.0 (metadata enrichment)' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const work = await response.json();
      return {
        catalogId: book.id,
        workKey: book.workKey,
        title: textValue(work.title),
        description: textValue(work.description),
        firstPublishDate: textValue(work.first_publish_date),
        subjects: Array.isArray(work.subjects) ? work.subjects.slice(0, 80) : [],
        subjectPeople: Array.isArray(work.subject_people) ? work.subject_people.slice(0, 30) : [],
        subjectPlaces: Array.isArray(work.subject_places) ? work.subject_places.slice(0, 30) : [],
        subjectTimes: Array.isArray(work.subject_times) ? work.subject_times.slice(0, 20) : [],
        sourceUrl: `https://openlibrary.org${book.workKey}`,
        fetchedAt: new Date().toISOString(),
      };
    } catch (error) {
      lastError = error.message;
      await new Promise((resolve) => setTimeout(resolve, attempt * 700));
    }
  }
  return {
    catalogId: book.id,
    workKey: book.workKey,
    error: lastError,
    sourceUrl: `https://openlibrary.org${book.workKey}`,
    fetchedAt: new Date().toISOString(),
  };
}

const pending = catalog.filter((book) => !cache[book.workKey] || cache[book.workKey].error);
const concurrency = 8;
let completed = 0;

for (let offset = 0; offset < pending.length; offset += concurrency) {
  const batch = pending.slice(offset, offset + concurrency);
  const results = await Promise.all(batch.map(fetchWork));
  for (const result of results) cache[result.workKey] = result;
  completed += results.length;
  await persist();
  if (completed % 80 === 0 || completed === pending.length) {
    process.stdout.write(`Fetched ${completed}/${pending.length}; cached ${Object.keys(cache).length}/${catalog.length}\n`);
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
}

const values = Object.values(cache);
const report = {
  catalogBooks: catalog.length,
  cached: values.length,
  withDescriptions: values.filter((item) => item.description).length,
  withPeople: values.filter((item) => item.subjectPeople?.length).length,
  withPlaces: values.filter((item) => item.subjectPlaces?.length).length,
  errors: values.filter((item) => item.error).length,
};
console.log(JSON.stringify(report, null, 2));
