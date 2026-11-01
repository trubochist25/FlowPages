import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const dataDir = path.join(root, 'data', 'book_catalog');
const catalog = JSON.parse(fs.readFileSync(path.join(dataDir, 'full-enrichment-draft.json'), 'utf8'));
const outputPath = path.join(dataDir, 'wikipedia-ru-cache.json');
const cache = fs.existsSync(outputPath)
  ? JSON.parse(fs.readFileSync(outputPath, 'utf8'))
  : {};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
const normalize = (value) => clean(value)
  .toLocaleLowerCase('ru')
  .replace(/ё/g, 'е')
  .replace(/[^a-zа-я0-9]+/gi, ' ')
  .trim();

function candidateScore(book, page) {
  const wanted = normalize(book.title);
  const title = normalize(page.title).replace(/ роман$| повесть$| книга$| произведение$/g, '');
  const extract = normalize(page.extract);
  if (/^[^.!?]{0,180}\b(?:фильм|телесериал|мультфильм)\b/.test(extract)) return -10;
  const authorParts = normalize(book.author).split(' ').filter((part) => part.length >= 4);
  if (!authorParts.some((part) => extract.includes(part))) return -10;
  let score = 0;
  if (title === wanted) score += 8;
  if (title.includes(wanted) || wanted.includes(title)) score += 4;
  if (authorParts.some((part) => extract.includes(part))) score += 3;
  if (/ роман | повесть | книга | произведение | сборник | трактат /.test(` ${extract} `)) score += 1;
  return score;
}

async function fetchOne(item) {
  const book = item.book;
  const query = `\"${book.title}\" ${book.author.split(',')[0]}`;
  const params = new URLSearchParams({
    action: 'query',
    format: 'json',
    formatversion: '2',
    generator: 'search',
    gsrsearch: query,
    gsrnamespace: '0',
    gsrlimit: '3',
    prop: 'extracts|info',
    exintro: '1',
    explaintext: '1',
    exchars: '2400',
    inprop: 'url',
    origin: '*',
  });
  let response;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    response = await fetch(`https://ru.wikipedia.org/w/api.php?${params}`, {
      headers: { 'User-Agent': 'BookstoreSearchDemo/1.0 (local educational catalog)' },
    });
    if (response.status !== 429) break;
    await sleep(2500 * (attempt + 1));
  }
  if (!response?.ok) throw new Error(`HTTP ${response?.status ?? 'network'}`);
  const payload = await response.json();
  const pages = payload?.query?.pages ?? [];
  const ranked = pages
    .map((page) => ({ ...page, score: candidateScore(book, page) }))
    .sort((a, b) => b.score - a.score);
  const best = ranked[0];
  if (!best || best.score < 7 || clean(best.extract).split(/\s+/).length < 20) {
    return { catalogId: book.id, status: 'not-found', query, fetchedAt: new Date().toISOString() };
  }
  return {
    catalogId: book.id,
    status: 'ok',
    query,
    pageTitle: best.title,
    pageUrl: best.fullurl,
    score: best.score,
    extract: clean(best.extract),
    fetchedAt: new Date().toISOString(),
  };
}

async function worker(queue, state) {
  while (queue.length) {
    const item = queue.shift();
    try {
      cache[item.book.workKey] = await fetchOne(item);
    } catch (error) {
      cache[item.book.workKey] = {
        catalogId: item.book.id,
        status: 'error',
        error: String(error?.message ?? error),
        fetchedAt: new Date().toISOString(),
      };
    }
    state.done += 1;
    if (state.done % 25 === 0 || queue.length === 0) {
      fs.writeFileSync(outputPath, `${JSON.stringify(cache, null, 2)}\n`);
      console.log(`${state.done}/${state.total}`);
    }
    await sleep(1100);
  }
}

const queue = catalog.filter((item) => {
  const words = clean(item.book.annotation).split(/\s+/).length;
  return words < 80 && (!cache[item.book.workKey] || cache[item.book.workKey].status === 'error');
});
const state = { done: 0, total: queue.length };
await worker(queue, state);
fs.writeFileSync(outputPath, `${JSON.stringify(cache, null, 2)}\n`);
const values = Object.values(cache);
console.log(JSON.stringify({
  cached: values.length,
  ok: values.filter((item) => item.status === 'ok').length,
  notFound: values.filter((item) => item.status === 'not-found').length,
  errors: values.filter((item) => item.status === 'error').length,
}, null, 2));
