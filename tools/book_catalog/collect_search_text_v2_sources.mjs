import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';


const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const outputDir = path.join(root, 'data', 'book_catalog', 'search-text-v2');
const sourcePacksPath = path.join(outputDir, 'source-packs.jsonl');
const collectionReportPath = path.join(outputDir, 'source-collection-report.json');

const args = new Map();
for (let index = 2; index < process.argv.length; index += 1) {
  const token = process.argv[index];
  if (!token.startsWith('--')) continue;
  const value = process.argv[index + 1];
  if (!value || value.startsWith('--')) args.set(token.slice(2), true);
  else {
    args.set(token.slice(2), value);
    index += 1;
  }
}

const scope = String(args.get('scope') ?? 'thin');
const selectedProviders = new Set(
  String(args.get('providers') ?? 'wikipedia-ru,wikipedia-en,google-books')
    .split(',').map((value) => value.trim()).filter(Boolean),
);
const delayMs = Math.max(300, Number(args.get('delay-ms') ?? 700));
const workersPerProvider = Math.max(1, Math.min(2, Number(args.get('workers-per-provider') ?? 1)));
const limit = Math.max(0, Number(args.get('limit') ?? 0));
const refresh = Boolean(args.get('refresh'));
const requestedCatalogIds = new Set(
  String(args.get('catalog-ids') ?? '')
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isInteger(value) && value > 0),
);
const allowedProviders = new Set(['wikipedia-ru', 'wikipedia-en', 'google-books']);
const matcherVersion = '2.1';
for (const provider of selectedProviders) {
  if (!allowedProviders.has(provider)) throw new Error(`Unknown provider: ${provider}`);
}
if (!['thin', 'single', 'all'].includes(scope)) throw new Error(`Unknown scope: ${scope}`);

const clean = (value) => String(value ?? '').replace(/\s+/gu, ' ').trim();
const plainText = (value) => clean(String(value ?? '')
  .replace(/<[^>]+>/gu, ' ')
  .replace(/&quot;/gu, '"')
  .replace(/&#39;|&apos;/gu, "'")
  .replace(/&amp;/gu, '&')
  .replace(/&lt;/gu, '<')
  .replace(/&gt;/gu, '>'));
const normalize = (value) => clean(value)
  .toLocaleLowerCase('ru')
  .replace(/ё/gu, 'е')
  .replace(/[^a-zа-я0-9]+/giu, ' ')
  .trim();
const words = (value) => clean(value).match(/[a-zа-яё0-9]+/giu)?.length ?? 0;
const sourceNoise = /\b(?:publish(?:ed|er|ing|ation)?|edition|isbn|award|prize|bestseller|перво(?:е|го)\s+издани|издан(?:ие|ия|ию|ием)|опубликован|публикаци|преми|наград|бестселлер|источник\s*:|source\s*:)\b/iu;
const usableSourceWords = (value) => clean(value).split(/(?<=[.!?])\s+/u)
  .filter((sentence) => !sourceNoise.test(sentence))
  .reduce((total, sentence) => total + words(sentence), 0);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function readJson(file, fallback = {}) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return fallback; }
}

function writeJson(file, value) {
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  fs.copyFileSync(temporary, file);
  fs.unlinkSync(temporary);
}

const packs = fs.readFileSync(sourcePacksPath, 'utf8')
  .split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line));

function isTarget(pack) {
  if (requestedCatalogIds.size) return requestedCatalogIds.has(Number(pack.catalogId));
  if (scope === 'all') return true;
  const content = pack.sources.filter((source) => [
    'source_description', 'encyclopedia_extract', 'publisher_description',
  ].includes(source.kind));
  const hasHuman = pack.sources.some((source) => source.trust === 'human_curated');
  if (scope === 'single') {
    return !hasHuman && new Set(content.map((source) => source.kind)).size < 2;
  }
  const description = pack.sources.find((source) => source.kind === 'source_description');
  return !hasHuman && usableSourceWords(description?.text) < 45;
}

const targets = packs.filter(isTarget).slice(0, limit || undefined);
const cacheFiles = {
  'wikipedia-ru': path.join(outputDir, 'wikipedia-ru-cache.json'),
  'wikipedia-en': path.join(outputDir, 'wikipedia-en-cache.json'),
  'google-books': path.join(outputDir, 'google-books-cache.json'),
};
const caches = Object.fromEntries(
  [...allowedProviders].map((provider) => [provider, readJson(cacheFiles[provider])]),
);

async function fetchJson(url) {
  let lastError;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { 'User-Agent': 'FlowPages-SearchTextV2/2.0 (local educational book catalog)' },
      });
      if (response.status === 429) {
        const retryAfter = Number(response.headers.get('retry-after') ?? 0);
        const waitMs = Math.min(60000, Math.max(retryAfter * 1000, attempt * 5000));
        lastError = new Error('HTTP 429');
        await sleep(waitMs);
        continue;
      }
      if (response.status >= 500) throw new Error(`HTTP ${response.status}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      await sleep(attempt * 1200);
    }
  }
  throw lastError;
}

function bookPageScore(pack, page, language) {
  const identity = pack.identity;
  const wanted = normalize(language === 'ru' ? identity.title : identity.sourceTitle || identity.title);
  const title = normalize(page.title).replace(/ (?:роман|повесть|книга|произведение|novel|book)$/u, '');
  const extract = normalize(page.extract);
  if (!wanted || !title || words(page.extract) < 25) return -20;
  if (/^[^.!?]{0,220}\b(?:фильм|телесериал|мультфильм|film|television series|tv series)\b/iu.test(page.extract)) {
    return -20;
  }
  let score = 0;
  if (title === wanted) score += 12;
  else if (title.includes(wanted) || wanted.includes(title)) score += 6;
  else return -20;
  const hasBookCue = /\b(?:роман|повесть|книга|пьеса|поэма|сборник|трактат|эссе|novel|book|play|poem|collection|memoir|treatise|essay)\b/iu.test(page.extract);
  if (hasBookCue) {
    score += 2;
  }
  const authorNames = language === 'en' && identity.sourceAuthors?.length
    ? identity.sourceAuthors : identity.authors;
  const authorParts = normalize(authorNames.join(' ')).split(' ').filter((part) => part.length >= 5);
  if (authorParts.length && !authorParts.some((part) => extract.includes(part))) return -20;
  if (!authorParts.length && !hasBookCue) return -20;
  if (authorParts.some((part) => extract.includes(part))) score += 3;
  return score;
}

async function collectWikipedia(pack, language) {
  const identity = pack.identity;
  const title = language === 'ru' ? identity.title : identity.sourceTitle || identity.title;
  const author = language === 'ru' ? identity.authors[0] ?? '' : '';
  const query = clean(`\"${title}\" ${author}`);
  const params = new URLSearchParams({
    action: 'query', format: 'json', formatversion: '2', generator: 'search',
    gsrsearch: query, gsrnamespace: '0', gsrlimit: '5', prop: 'extracts|info',
    exintro: '1', explaintext: '1', exchars: '5000', inprop: 'url', origin: '*',
  });
  const payload = await fetchJson(`https://${language}.wikipedia.org/w/api.php?${params}`);
  const ranked = (payload?.query?.pages ?? [])
    .map((page) => ({ ...page, score: bookPageScore(pack, page, language) }))
    .sort((left, right) => right.score - left.score);
  const best = ranked[0];
  if (!best || best.score < 12) {
    return { catalogId: pack.catalogId, matcherVersion, status: 'not-found', query, fetchedAt: new Date().toISOString() };
  }
  return {
    catalogId: pack.catalogId,
    matcherVersion,
    status: 'ok',
    query,
    pageTitle: best.title,
    pageUrl: best.fullurl,
    score: best.score,
    extract: clean(best.extract),
    fetchedAt: new Date().toISOString(),
  };
}

function googleScore(pack, volume) {
  const info = volume.volumeInfo ?? {};
  const candidates = [pack.identity.sourceTitle, pack.identity.title].map(normalize).filter(Boolean);
  const title = normalize(info.title);
  if (!title || words(plainText(info.description)) < 25) return -20;
  let score = 0;
  if (candidates.includes(title)) score += 12;
  else if (candidates.some((wanted) => title.includes(wanted) || wanted.includes(title))) score += 6;
  else return -20;
  const wantedAuthorParts = normalize((pack.identity.sourceAuthors ?? pack.identity.authors).join(' '))
    .split(' ').filter((part) => part.length >= 5);
  const foundAuthors = normalize((info.authors ?? []).join(' '));
  if (wantedAuthorParts.length && !wantedAuthorParts.some((part) => foundAuthors.includes(part))) return -20;
  if (Array.isArray(info.authors) && info.authors.length) score += 1;
  if (clean(info.language)) score += 1;
  return score;
}

async function collectGoogleBooks(pack) {
  const title = pack.identity.sourceTitle || pack.identity.title;
  const query = `intitle:\"${title}\"`;
  const params = new URLSearchParams({ q: query, maxResults: '10', printType: 'books' });
  const payload = await fetchJson(`https://www.googleapis.com/books/v1/volumes?${params}`);
  const ranked = (payload.items ?? [])
    .map((volume) => ({ volume, score: googleScore(pack, volume) }))
    .sort((left, right) => right.score - left.score);
  const best = ranked[0];
  if (!best || best.score < 12) {
    return { catalogId: pack.catalogId, matcherVersion, status: 'not-found', query, fetchedAt: new Date().toISOString() };
  }
  const info = best.volume.volumeInfo;
  return {
    catalogId: pack.catalogId,
    matcherVersion,
    status: 'ok',
    query,
    volumeId: best.volume.id,
    title: clean(info.title),
    authors: info.authors ?? [],
    score: best.score,
    description: plainText(info.description),
    infoLink: clean(info.infoLink),
    language: clean(info.language),
    fetchedAt: new Date().toISOString(),
  };
}

const jobsByProvider = Object.fromEntries([...selectedProviders].map((provider) => [provider, []]));
for (const pack of targets) {
  for (const provider of selectedProviders) {
    const current = caches[provider][pack.workKey];
    if (!refresh && current?.matcherVersion === matcherVersion && current.status !== 'error') continue;
    jobsByProvider[provider].push({ pack, provider });
  }
}
const jobs = Object.values(jobsByProvider).flat();

let done = 0;
const providerCursors = Object.fromEntries([...selectedProviders].map((provider) => [provider, 0]));
async function providerWorker(provider) {
  const queue = jobsByProvider[provider];
  while (providerCursors[provider] < queue.length) {
    const job = queue[providerCursors[provider]];
    providerCursors[provider] += 1;
    let result;
    try {
      if (job.provider === 'wikipedia-ru') result = await collectWikipedia(job.pack, 'ru');
      else if (job.provider === 'wikipedia-en') result = await collectWikipedia(job.pack, 'en');
      else result = await collectGoogleBooks(job.pack);
    } catch (error) {
      result = {
        catalogId: job.pack.catalogId,
        matcherVersion,
        status: 'error',
        error: String(error?.message ?? error),
        fetchedAt: new Date().toISOString(),
      };
    }
    caches[job.provider][job.pack.workKey] = result;
    done += 1;
    if (done % 10 === 0 || done === jobs.length) {
      writeJson(cacheFiles[provider], caches[provider]);
      process.stdout.write(`${done}/${jobs.length}\n`);
    }
    const providerDelay = provider.startsWith('wikipedia') ? Math.max(1000, delayMs) : delayMs;
    await sleep(providerDelay);
  }
}

await Promise.all(
  [...selectedProviders].flatMap((provider) =>
    Array.from({ length: workersPerProvider }, () => providerWorker(provider))),
);
for (const provider of selectedProviders) writeJson(cacheFiles[provider], caches[provider]);

const report = {
  matcherVersion,
  createdAt: new Date().toISOString(),
  scope,
  requestedCatalogIds: [...requestedCatalogIds].sort((left, right) => left - right),
  targets: targets.length,
  attempted: jobs.length,
  selectedProviders: [...selectedProviders],
  providers: {},
};
for (const provider of allowedProviders) {
  const allValues = Object.values(caches[provider]);
  const values = allValues.filter((item) => item.matcherVersion === matcherVersion);
  report.providers[provider] = {
    cached: values.length,
    stale: allValues.length - values.length,
    ok: values.filter((item) => item.status === 'ok').length,
    notFound: values.filter((item) => item.status === 'not-found').length,
    errors: values.filter((item) => item.status === 'error').length,
  };
}
writeJson(collectionReportPath, report);
console.log(JSON.stringify(report, null, 2));
