import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..', '..');
const catalogFile = path.join(root, 'data', 'book_catalog', 'catalog.json');
const outputDir = path.join(root, 'image', 'catalog', 'books');
const reportFile = path.join(root, 'data', 'book_catalog', 'cover-report.json');
const catalog = JSON.parse(await fs.readFile(catalogFile, 'utf8'));
const concurrency = 8;
let cursor = 0;
let downloaded = 0;
let reused = 0;
const failures = [];

await fs.mkdir(outputDir, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function download(book) {
  const filename = `book-${String(book.id).padStart(4, '0')}.jpg`;
  const destination = path.join(outputDir, filename);

  try {
    const stat = await fs.stat(destination);
    if (stat.size > 1500) {
      reused += 1;
      return;
    }
  } catch {
    // Download missing files.
  }

  let lastError;

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const response = await fetch(`${book.coverUrl}?default=false`, {
        headers: { 'User-Agent': 'FlowPages-Demo-Catalog/1.0' }
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const contentType = response.headers.get('content-type') ?? '';
      if (!contentType.startsWith('image/')) throw new Error(`Unexpected ${contentType}`);

      const bytes = Buffer.from(await response.arrayBuffer());
      if (bytes.length < 1500) throw new Error(`Image too small: ${bytes.length}`);

      await fs.writeFile(destination, bytes);
      downloaded += 1;
      return;
    } catch (error) {
      lastError = error;
      await sleep(attempt * 500);
    }
  }

  failures.push({ id: book.id, title: book.title, url: book.coverUrl, error: lastError?.message });
}

async function worker() {
  while (cursor < catalog.length) {
    const index = cursor;
    cursor += 1;
    await download(catalog[index]);

    const complete = downloaded + reused + failures.length;
    if (complete % 50 === 0) {
      process.stdout.write(
        `${complete}/${catalog.length}: downloaded=${downloaded}, reused=${reused}, failed=${failures.length}\n`
      );
    }
  }
}

await Promise.all(Array.from({ length: concurrency }, worker));

const report = {
  total: catalog.length,
  downloaded,
  reused,
  failed: failures.length,
  failures
};

await fs.writeFile(reportFile, JSON.stringify(report, null, 2), 'utf8');
console.log(JSON.stringify(report, null, 2));

if (failures.length > 0) process.exitCode = 2;
