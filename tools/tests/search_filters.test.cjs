const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../catalog/view/javascript/common.js'), 'utf8');
const helper = source.slice(0, source.indexOf('function getURLVar'));
let form = null;
const context = {
  URL,
  document: { baseURI: 'http://bookstore/', querySelector: () => form },
  FormData: class {
    constructor(current) { this.entries = current.entries; }
    forEach(callback) { this.entries.forEach(([name, value]) => callback(value, name)); }
  }
};
vm.createContext(context);
vm.runInContext(helper, context);

function build(target, query) { return new URL(context.flowpagesSearchUrl(target, query)); }
let result = build('index.php?route=product/search&page=3', 'Дюна');
assert.equal(result.searchParams.get('search'), 'Дюна');
assert.equal(result.searchParams.has('page'), false);

form = {
  elements: [
    { name: 'price_min', type: 'number' },
    { name: 'price_max', type: 'number' },
    { name: 'genres[]', type: 'checkbox' },
    { name: 'authors[]', type: 'checkbox' },
    { name: 'search', type: 'hidden' }
  ],
  entries: [
    ['route', 'product/search'], ['search', 'старый запрос'],
    ['sort', 'price_asc'], ['limit', '20'],
    ['price_min', '0'], ['price_max', ''],
    ['genres[]', 'Детективы'], ['genres[]', 'Фантастика']
  ],
  querySelector: selector => ({ value: selector.includes('sort') ? 'price_asc' : '20' })
};
result = build('index.php?route=product/search&price_max=1000&authors[]=старый&page=2', 'новый запрос');
assert.equal(result.searchParams.get('search'), 'новый запрос');
assert.equal(result.searchParams.get('price_min'), '0');
assert.equal(result.searchParams.has('price_max'), false);
assert.equal(result.searchParams.has('authors[]'), false);
assert.deepEqual(result.searchParams.getAll('genres[]'), ['Детективы', 'Фантастика']);
assert.equal(result.searchParams.get('sort'), 'price_asc');
assert.equal(result.searchParams.get('limit'), '20');
assert.equal(result.searchParams.has('page'), false);
result = build('index.php?route=product/search', '');
assert.equal(result.searchParams.has('search'), false);
assert.equal(result.searchParams.get('price_min'), '0');

const template = fs.readFileSync(path.join(__dirname, '../../catalog/view/theme/flowpages/template/product/search.twig'), 'utf8');
assert.equal(template.includes('class="fp-filter-submit"'), false);
console.log('Search filter regressions: OK');
