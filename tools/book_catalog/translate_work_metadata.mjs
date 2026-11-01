import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..', '..');
const sourcePath = path.join(root, 'data', 'book_catalog', 'work-metadata-cache.json');
const outputPath = path.join(root, 'data', 'book_catalog', 'work-metadata-ru.json');
const source = JSON.parse(await fs.readFile(sourcePath, 'utf8'));

let cache = {};
try {
  cache = JSON.parse(await fs.readFile(outputPath, 'utf8'));
} catch {
  cache = {};
}

function clean(value) {
  return String(value ?? '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\[(.*?)\]\([^)]*\)/g, '$1')
    .replace(/[*_#`]+/g, '')
    .replace(/\r?\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isMostlyRussian(value) {
  const cyrillic = (value.match(/[А-Яа-яЁё]/g) ?? []).length;
  const latin = (value.match(/[A-Za-z]/g) ?? []).length;
  return cyrillic > latin * 1.5;
}

async function translate(value) {
  const sourceText = clean(value);
  if (!sourceText || isMostlyRussian(sourceText)) return sourceText;
  let lastError = '';
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const params = new URLSearchParams({
        client: 'gtx', sl: 'auto', tl: 'ru', dt: 't', q: sourceText.slice(0, 12000),
      });
      const response = await fetch('https://translate.googleapis.com/translate_a/single', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'User-Agent': 'Bookstore-ML-Demo/1.0 (metadata translation)',
        },
        body: params,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      return clean((payload[0] ?? []).map((part) => part[0]).join(''));
    } catch (error) {
      lastError = error.message;
      await new Promise((resolve) => setTimeout(resolve, attempt * 1000));
    }
  }
  throw new Error(lastError || 'translation failed');
}

async function persist() {
  await fs.writeFile(outputPath, `${JSON.stringify(cache, null, 2)}\n`, 'utf8');
}

const entries = Object.values(source);
const pending = entries.filter((item) => item.description && !cache[item.workKey]?.descriptionRu);
const concurrency = 5;
let completed = 0;

for (let offset = 0; offset < pending.length; offset += concurrency) {
  const batch = pending.slice(offset, offset + concurrency);
  const results = await Promise.all(batch.map(async (item) => {
    try {
      return [item.workKey, {
        catalogId: item.catalogId,
        workKey: item.workKey,
        descriptionRu: await translate(item.description),
        sourceUrl: item.sourceUrl,
        translatedAt: new Date().toISOString(),
      }];
    } catch (error) {
      return [item.workKey, {
        catalogId: item.catalogId,
        workKey: item.workKey,
        error: error.message,
        sourceUrl: item.sourceUrl,
        translatedAt: new Date().toISOString(),
      }];
    }
  }));
  for (const [key, result] of results) cache[key] = result;
  completed += results.length;
  if (completed % 25 === 0 || completed === pending.length) {
    await persist();
    process.stdout.write(`Translated ${completed}/${pending.length}\n`);
  }
  await new Promise((resolve) => setTimeout(resolve, 120));
}

await persist();
const values = Object.values(cache);
console.log(JSON.stringify({
  sourceDescriptions: entries.filter((item) => item.description).length,
  translated: values.filter((item) => item.descriptionRu).length,
  errors: values.filter((item) => item.error).length,
}, null, 2));
