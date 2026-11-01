import fs from 'node:fs/promises';
import path from 'node:path';
import { buildSearchText } from './search_text.mjs';

const root = path.resolve(import.meta.dirname, '..', '..');
const dataDir = path.join(root, 'data', 'book_catalog');
const source = JSON.parse(
  await fs.readFile(path.join(dataDir, 'openlibrary-raw.json'), 'utf8')
);
const cacheFile = path.join(dataDir, 'translations-cache.json');
let translationCache = {};

try {
  translationCache = JSON.parse(await fs.readFile(cacheFile, 'utf8'));
} catch {
  translationCache = {};
}

const cyrillic = /[А-Яа-яЁё]/;
const excluded = /\b(journal|magazine|notebook|planner|calendar|coloring|workbook|study guide|summary|cliffsnotes|sparknotes|manual)\b/i;
const nonfictionGenres = new Set([
  'Психология', 'Саморазвитие', 'Бизнес и экономика', 'История',
  'Биографии и мемуары', 'Научно-популярная литература', 'Философия',
  'Искусство и культура', 'Здоровье', 'Родительство',
  'Компьютеры и технологии', 'Религия'
]);

const fictionGenreRules = [
  ['Ужасы', /^horror$|^horror fiction$|^fiction, horror|^horror (stories|tales)$|ужас/i],
  ['Триллеры', /^thrillers?$|^suspense$|fiction, thrillers?|триллер|саспенс/i],
  ['Детективы', /^detective|^mystery|mystery and detective|crime fiction|murder mysteries|police procedurals?|детектив|расследован/i],
  ['Фантастика', /^science fiction$|english science fiction|fiction, science fiction|^dystopias?$|dystopian|антиутоп|научная фантастика/i],
  ['Фэнтези', /^fantasy$|fantasy fiction|fiction, fantasy|^magic$|magic in fiction|wizards in fiction|witches in fiction|фэнтези|магия/i],
  ['Романтика', /^romance$|fiction, romance|romance fiction|love stories|man-woman relationships|любовный роман/i],
  ['Приключения', /^adventure$|action & adventure|adventure and adventurers, fiction|^voyages$|^expeditions$|^survival$|^pirates$|приключ/i],
  ['Историческая проза', /^historical fiction$|^historical novels$|fiction, historical|исторический роман/i],
  ['Юмор', /^humou?r$|^satire$|^comic fiction$|юмор|сатира/i],
  ['Поэзия', /^poetry$|^poems$|^verse$|поэз|стих/i],
  ['Подростковая литература', /^young adult fiction|^teen fiction|^adolescence$|^coming of age$|подрост/i],
  ['Детская литература', /^juvenile fiction$|^children's fiction$|^children's stories$|^picture books$|^fairy tales$|детская литература|сказк/i],
  ['Комиксы и манга', /^comics$|^comic books|^graphic novels$|^manga$|комикс|манга/i]
];

const nonfictionGenreRules = [
  ['Компьютеры и технологии', /(^|, |\/ )(computers?|computer programming|programming|software|internet|artificial intelligence|technology)(,|$)|программирован|компьютер/i],
  ['Бизнес и экономика', /(^|, |\/ )(business|economics|finance|personal finance|investments?|management|marketing|leadership|entrepreneurship)(,|$)|бизнес|экономик|финанс|инвестиц/i],
  ['Психология', /(^|, |\/ )(psychology|psychotherapy|mental health|cognitive psychology|emotions?)(,|$)|психолог|психотерап/i],
  ['Саморазвитие', /(^|, |\/ )(self-help|self-improvement|self-realization|personal growth|motivation|success|habits|productivity|conduct of life)(,|$)|саморазвит|мотивац|привычк/i],
  ['Здоровье', /(^|, |\/ )(health|medicine|medical|diet|nutrition|fitness|disease)(,|$)|здоров|медицин|питани/i],
  ['Родительство', /(^|, |\/ )(parenting|child rearing|motherhood|fatherhood)(,|$)|родител|воспитание детей/i],
  ['Биографии и мемуары', /(^|, |\/ )(biography|autobiography|memoirs?|personal narratives|diaries)(,|$)|биограф|мемуар|дневник/i],
  ['История', /(^|, |\/ )(history|historical account|world history|military history|social history)(,|$)|история$|исторические науки/i],
  ['Научно-популярная литература', /(^|, |\/ )(popular science|physics|biology|astronomy|evolution|mathematics|neuroscience)(,|$)|научно-популяр|физик|биолог|астроном/i],
  ['Философия', /(^|, |\/ )(philosophy|ethics)(,|$)|философ|этик/i],
  ['Искусство и культура', /(^|, |\/ )(art|arts|music|cinema|architecture|photography)(,|$)|искусств|музык|кино|архитектур/i],
  ['Религия', /(^|, |\/ )(religion|christianity|islam|buddhism|theology|spirituality)(,|$)|религи|христиан|ислам|будд/i]
];

const titleOverrides = new Map([
  ['O Alquimista', 'Алхимик'],
  ['Nineteen Eighty-Four', '1984'],
  ['Fahrenheit 451', '451° по Фаренгейту'],
  ['The Count of Monte Cristo', 'Граф Монте-Кристо'],
  ["Gulliver's Travels", 'Путешествия Гулливера'],
  ["The Handmaid's Tale", 'Рассказ служанки'],
  ['A Christmas Carol', 'Рождественская песнь'],
  ['The Drawing of the Three', 'Извлечение троих'],
  ['Das Glasperlenspiel', 'Игра в бисер'],
  ['Ὀδύσσεια', 'Одиссея'],
  ['Ἰλιάς', 'Илиада'],
  ['海辺のカフカ', 'Кафка на пляже'],
  ['ねじまき鳥クロニクル', 'Хроники Заводной Птицы'],
  ['JavaScript', 'JavaScript. Подробное руководство'],
  ['Ab urbe condita', 'История Рима от основания города'],
  ['キッチン', 'Кухня'],
  ["Les Contes de ma mère l'Oye", 'Сказки матушки Гусыни'],
  ['Erinnerungen, Träume, Gedanken', 'Воспоминания, сновидения, размышления'],
  ['スプートニクの恋人', 'Мой любимый Sputnik'],
  ['国境の南、太陽の西', 'К югу от границы, на запад от солнца'],
  ['雪国', 'Снежная страна'],
  ['Doce cuentos peregrinos', 'Двенадцать странствующих рассказов'],
  ['Die Entwicklung des Sozialismus von der Utopie zur Wissenschaft', 'Развитие социализма от утопии к науке'],
  ['アフターダーク', 'Послемрак'],
  ['羊をめぐる冒険', 'Охота на овец'],
  ['色彩を持たない多崎つくると、彼の巡礼の年', 'Бесцветный Цкуру Тадзаки и годы его странствий'],
  ['ダンス・ダンス・ダンス', 'Дэнс, дэнс, дэнс'],
  ['世界の終りとハードボイルド・ワンダーランド', 'Страна Чудес без тормозов и Конец Света']
]);

const authorOverrides = new Map([
  ['村上春樹', 'Харуки Мураками'],
  ['吉本 ばなな', 'Банана Ёсимото'],
  ['川端康成', 'Ясунари Кавабата'],
  ['Όμηρος', 'Гомер'],
  ['孙武', 'Сунь-цзы']
]);

const coverOverrides = new Map([
  ['/works/OL1938306W', 200453]
]);

const themeRules = [
  ['расследование и тайны', /(mystery|detective|investigation|secret|crime|расслед|тайн|преступ)/i],
  ['любовь и отношения', /(love|romance|marriage|relationship|любов|отношен|брак)/i],
  ['семья и поколения', /(family|parents|mothers|fathers|family life|семь|родител|поколен)/i],
  ['дружба и взаимопомощь', /(friendship|friends|friend|дружб|товарищ)/i],
  ['война и её последствия', /(war|soldiers|military|войн|солдат|фронт)/i],
  ['власть и общество', /(power|politics|society|government|social conditions|власт|политик|обществ)/i],
  ['магия и сверхъестественное', /(magic|wizard|witch|supernatural|occult|маг|колдун|сверхъест)/i],
  ['будущее и технологии', /(future|technology|robots|artificial intelligence|dystopia|будущ|технолог|робот|антиутоп)/i],
  ['космос и открытия', /(space|planet|astronomy|universe|alien|космос|планет|вселен)/i],
  ['путешествия и приключения', /(travel|voyage|journey|adventure|expedition|путешеств|приключ)/i],
  ['выживание и испытания', /(survival|danger|disaster|struggle|выжив|опасност|испытан)/i],
  ['взросление и поиск себя', /(coming of age|adolescence|identity|self-discovery|взрослен|поиск себя)/i],
  ['страх и неизвестность', /(fear|horror|ghost|haunted|terror|страх|ужас|призрак)/i],
  ['история и память', /(history|memory|past|historical|истори|памят|прошл)/i],
  ['мышление и поведение', /(psychology|behavior|cognitive|mind|emotion|мышлен|поведен|эмоц)/i],
  ['привычки и личный рост', /(habits|success|motivation|self-help|personal growth|привыч|успех|саморазвит)/i],
  ['деньги и управление', /(money|finance|business|management|investment|деньг|финанс|бизнес|управлен)/i],
  ['наука и устройство мира', /(science|physics|biology|evolution|nature|наук|физик|биолог|природ)/i],
  ['здоровье и образ жизни', /(health|medicine|diet|fitness|nutrition|здоров|медицин|питани)/i],
  ['искусство и творчество', /(art|music|writing|creative|искусств|музык|творчеств)/i],
  ['смысл жизни и выбор', /(philosophy|ethics|meaning|moral|choice|философ|смысл|морал|выбор)/i]
];

const seriesRules = [
  ['Гарри Поттер', /harry potter|гарри поттер/i],
  ['Голодные игры', /hunger games|голодные игры/i],
  ['Властелин колец', /lord of the rings|властелин колец/i],
  ['Хроники Нарнии', /narnia|нарни/i],
  ['Песнь льда и огня', /song of ice and fire|game of thrones|игра престолов/i],
  ['Ведьмак', /witcher|wiedźmin|ведьмак/i],
  ['Дюна', /\bdune\b|дюна/i],
  ['Шерлок Холмс', /sherlock holmes|шерлок холмс/i],
  ['Перси Джексон', /percy jackson|перси джексон/i],
  ['Сумерки', /twilight saga|сумерки/i],
  ['Дивергент', /divergent|дивергент/i],
  ['Бегущий в лабиринте', /maze runner|бегущий в лабиринте/i],
  ['Основание', /foundation series|foundation trilogy|основание/i],
  ['Плоский мир', /discworld|плоский мир/i],
  ['Миллениум', /millennium series|girl with the dragon tattoo|миллениум/i]
];

function sanitizeText(value) {
  return String(value ?? '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/[\u{10000}-\u{10FFFF}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeKey(value) {
  return sanitizeText(value)
    .toLocaleLowerCase('ru')
    .replace(/ё/g, 'е')
    .replace(/[^\p{L}\p{N}]+/gu, '');
}

function hashCode(value) {
  let hash = 2166136261;
  for (const char of value) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function transliterateFallback(value) {
  const pairs = [
    [/shch/gi, 'щ'], [/sch/gi, 'щ'], [/zh/gi, 'ж'], [/kh/gi, 'х'],
    [/ts/gi, 'ц'], [/ch/gi, 'ч'], [/sh/gi, 'ш'], [/yu/gi, 'ю'],
    [/ya/gi, 'я'], [/yo/gi, 'ё'], [/ye/gi, 'е']
  ];
  let result = value;
  for (const [pattern, replacement] of pairs) result = result.replace(pattern, replacement);
  const map = {
    a: 'а', b: 'б', c: 'к', d: 'д', e: 'е', f: 'ф', g: 'г', h: 'х',
    i: 'и', j: 'дж', k: 'к', l: 'л', m: 'м', n: 'н', o: 'о', p: 'п',
    q: 'к', r: 'р', s: 'с', t: 'т', u: 'у', v: 'в', w: 'в', x: 'кс',
    y: 'й', z: 'з'
  };
  return result.replace(/[a-z]/gi, (letter) => {
    const mapped = map[letter.toLowerCase()] ?? letter;
    return letter === letter.toUpperCase()
      ? mapped.charAt(0).toUpperCase() + mapped.slice(1)
      : mapped;
  });
}

async function translateBatch(values) {
  const missing = [...new Set(values)]
    .filter((value) => value && !cyrillic.test(value) && !translationCache[value]);

  for (let offset = 0; offset < missing.length; offset += 15) {
    const batch = missing.slice(offset, offset + 15);
    const marked = batch
      .map((value, index) => `[ID${String(index).padStart(3, '0')}] ${value}`)
      .join('\n');
    const params = new URLSearchParams({
      client: 'gtx', sl: 'auto', tl: 'ru', dt: 't', q: marked
    });

    try {
      const response = await fetch(
        `https://translate.googleapis.com/translate_a/single?${params}`,
        { headers: { 'User-Agent': 'FlowPages-Demo-Catalog/1.0' } }
      );

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const translated = (payload[0] ?? []).map((part) => part[0]).join('');
      const matches = [...translated.matchAll(
        /\[ID(\d{3})\]\s*([\s\S]*?)(?=\n?\[ID\d{3}\]|$)/g
      )];

      for (const match of matches) {
        const index = Number(match[1]);
        if (batch[index]) translationCache[batch[index]] = sanitizeText(match[2]);
      }
    } catch (error) {
      process.stderr.write(`Translation batch ${offset}: ${error.message}\n`);
    }

    for (const value of batch) {
      if (!translationCache[value]) translationCache[value] = transliterateFallback(value);
    }

    await fs.writeFile(cacheFile, JSON.stringify(translationCache, null, 2), 'utf8');
    await new Promise((resolve) => setTimeout(resolve, 350));
    process.stdout.write(`Translated ${Math.min(offset + batch.length, missing.length)}/${missing.length}\n`);
  }
}

const seen = new Set();
const candidates = [];

for (const work of source) {
  const edition = work.editions?.docs?.[0] ?? {};
  const editionTitle = sanitizeText(edition.title);
  const workTitle = sanitizeText(work.title);
  const sourceTitle = cyrillic.test(editionTitle) ? editionTitle : workTitle || editionTitle;
  const authors = (work.author_name ?? []).map(sanitizeText).filter(Boolean).slice(0, 3);
  const coverId = coverOverrides.get(work.key) ?? edition.cover_i ?? work.cover_i;

  if (!sourceTitle || !authors.length || !coverId || excluded.test(sourceTitle)) continue;

  const key = `${normalizeKey(workTitle || sourceTitle)}:${normalizeKey(authors[0])}`;
  if (seen.has(key)) continue;
  seen.add(key);

  candidates.push({ work, edition, sourceTitle, authors, coverId });
  if (candidates.length >= 1100) break;
}

await translateBatch(candidates.map((item) => item.sourceTitle));
await translateBatch(candidates.flatMap((item) => item.authors));

function translated(value) {
  if (cyrillic.test(value)) return sanitizeText(value);
  return sanitizeText(translationCache[value] || transliterateFallback(value));
}

function classifyGenres(work, year) {
  const subjects = (work.subject ?? []).slice(0, 40).map(sanitizeText);
  const genres = [];
  const hasFiction = subjects.some((subject) =>
    /(^|, |\/ )(fiction|novels?|stories)(,|$)|fictional works/i.test(subject)
  );
  const hasNonfiction = subjects.some((subject) => /^nonfiction$|^non-fiction$/i.test(subject));
  const isFiction = hasFiction && !hasNonfiction;
  const rules = isFiction ? fictionGenreRules : nonfictionGenreRules;

  for (const [name, pattern] of rules) {
    if (subjects.some((subject) => pattern.test(subject))) genres.push(name);
    if (genres.length === 3) break;
  }

  if (!genres.length) {
    genres.push(isFiction && year && year < 1970 ? 'Классическая литература' : 'Современная проза');
  } else if (
    isFiction &&
    year && year < 1970 &&
    genres.length < 3 &&
    !genres.includes('Классическая литература')
  ) {
    genres.push('Классическая литература');
  }

  return [...new Set(genres)].slice(0, 3);
}

function classifyThemes(work, genres) {
  const haystack = [work.title, ...(work.subject ?? [])].join(' ');
  const themes = themeRules
    .filter(([, pattern]) => pattern.test(haystack))
    .map(([name]) => name)
    .slice(0, 4);

  if (themes.length < 2) {
    if (genres.some((genre) => nonfictionGenres.has(genre))) {
      themes.push('знания и развитие', 'практические идеи');
    } else {
      themes.push('человеческие отношения', 'личный выбор');
    }
  }

  return [...new Set(themes)].slice(0, 4);
}

function classifyMood(genres, haystack) {
  const mood = [];
  const add = (...values) => mood.push(...values);

  if (genres.includes('Ужасы')) add('страшная', 'мрачная', 'напряжённая');
  else if (genres.includes('Триллеры')) add('напряжённая', 'мрачная', 'динамичная');
  else if (genres.includes('Детективы')) add('загадочная', 'напряжённая');
  else if (genres.includes('Романтика')) add('романтичная', 'эмоциональная');
  else if (genres.includes('Юмор')) add('лёгкая', 'ироничная');
  else if (genres.includes('Приключения')) add('динамичная', 'приключенческая');
  else if (genres.includes('Фэнтези')) add('волшебная', 'приключенческая');
  else if (genres.includes('Фантастика')) add('интеллектуальная', 'загадочная');
  else if (genres.some((genre) => nonfictionGenres.has(genre))) add('познавательная', 'вдумчивая');
  else add('драматичная', 'атмосферная');

  if (/(cozy|comfort|уют)/i.test(haystack)) add('уютная');
  if (/(melanchol|grief|loss|меланхол|утрат)/i.test(haystack)) add('меланхоличная');
  return [...new Set(mood)].slice(0, 3);
}

function classifyPace(genres) {
  if (genres.some((genre) => ['Триллеры', 'Детективы', 'Приключения', 'Ужасы'].includes(genre))) {
    return 'быстрый';
  }
  if (genres.some((genre) => ['Философия', 'Поэзия', 'Классическая литература'].includes(genre))) {
    return 'медленный';
  }
  return 'средний';
}

function classifyAge(genres, haystack) {
  if (genres.includes('Детская литература')) return '6+';
  if (genres.includes('Подростковая литература')) return '12+';
  if (genres.some((genre) => ['Ужасы', 'Триллеры'].includes(genre))) return '18+';
  if (/(erotic|sexual|graphic violence|эрот|сексуаль|жесток)/i.test(haystack)) return '18+';
  return genres.some((genre) => nonfictionGenres.has(genre)) ? '12+' : '16+';
}

function classifySeries(work, title) {
  const haystack = [title, work.title, ...(work.subject ?? [])].join(' ');
  return seriesRules.find(([, pattern]) => pattern.test(haystack))?.[0] ?? '';
}

function buildAnnotation(book, variant) {
  const themes = book.themes.join(', ');
  const moods = book.mood.join(', ');
  const genre = book.genres[0].toLocaleLowerCase('ru');
  const fiction = !book.genres.some((item) => nonfictionGenres.has(item));

  const fictionTemplates = [
    `«${book.title}» — ${genre} автора ${book.author}. В центре книги — ${themes}. ${moods} атмосфера и ${book.pace} темп помогают истории удерживать внимание до последних страниц.`,
    `Книга «${book.title}» объединяет темы: ${themes}. ${book.author} создаёт настроение: ${moods}. Темп повествования — ${book.pace}; жанровая основа — «${book.genres[0]}».`,
    `В «${book.title}» ${book.author} обращается к темам ${themes}. История сохраняет настроение: ${moods}. Темп развития событий — ${book.pace}.`,
    `«${book.title}» предлагает историю о том, как переплетаются ${themes}. Настроение книги: ${moods}; темп — ${book.pace}. В основе лежит жанр «${book.genres[0]}».`
  ];
  const nonfictionTemplates = [
    `В книге «${book.title}» ${book.author} рассматривает темы: ${themes}. Темп изложения — ${book.pace}. Книга подойдёт читателям, которым интересны практические идеи и понятное знакомство с предметом.`,
    `«${book.title}» — книга о том, как связаны ${themes}. ${book.author} последовательно раскрывает основные идеи, сохраняя ${moods} тон изложения.`,
    `Книга ${book.author} «${book.title}» посвящена темам ${themes}. Это ${moods} чтение для тех, кто хочет расширить кругозор и по-новому взглянуть на знакомые вопросы.`,
    `В центре книги «${book.title}» — ${themes}. Автор ${book.author} собирает ключевые идеи в последовательное и доступное повествование.`
  ];

  return (fiction ? fictionTemplates : nonfictionTemplates)[variant % 4];
}

const catalog = [];
const finalSeen = new Set();

for (const candidate of candidates) {
  const title = titleOverrides.get(candidate.work.title)
    ?? titleOverrides.get(candidate.sourceTitle)
    ?? translated(candidate.sourceTitle);
  let authors = candidate.authors
    .slice(0, 2)
    .map((name) => authorOverrides.get(name) ?? translated(name))
    .filter((name) => !/Дополнительная информация/i.test(name));
  if (candidate.work.title === 'The Art of War') authors = ['Сунь-цзы'];
  const author = authors.join(', ');
  const titleKey = normalizeKey(title);
  if (!title || !author || finalSeen.has(titleKey)) continue;
  finalSeen.add(titleKey);

  const work = candidate.work;
  const year = Number(work.first_publish_year) || 2000;
  const hash = hashCode(work.key || `${title}:${author}`);
  const pages = Math.max(48, Math.min(1600, Number(work.number_of_pages_median) || (160 + hash % 440)));
  const genres = classifyGenres(work, year);
  const themes = classifyThemes(work, genres);
  const haystack = [work.title, ...(work.subject ?? [])].join(' ');
  const mood = classifyMood(genres, haystack);
  const pace = classifyPace(genres);
  const ageRating = classifyAge(genres, haystack);
  const series = classifySeries(work, title);
  const rawIsbn = candidate.edition.isbn?.find((value) => /^\d{13}$/.test(value))
    ?? candidate.edition.isbn?.[0]
    ?? '';
  const basePrice = 330 + pages * 1.18 + (year >= 2020 ? 120 : 0);
  const priceRub = Math.max(299, Math.min(1899, Math.round(basePrice / 10) * 10 - 1));
  const price = Math.round(priceRub * 0.036095 * 10) / 10;
  const book = {
    id: catalog.length + 1,
    workKey: work.key,
    title,
    author,
    authors,
    year,
    pages,
    genres,
    themes,
    mood,
    pace,
    ageRating,
    language: 'Русский',
    series,
    isbn: sanitizeText(rawIsbn).slice(0, 17),
    price,
    quantity: 4 + hash % 43,
    popularity: Number(work.readinglog_count) || Math.max(1, 6000 - work.sourceRank),
    rating: Number(work.ratings_average) || 0,
    ratingCount: Number(work.ratings_count) || 0,
    coverId: candidate.coverId,
    coverUrl: `https://covers.openlibrary.org/b/id/${candidate.coverId}-L.jpg`,
    coverSource: `https://openlibrary.org${work.key}`,
    sourceTitle: sanitizeText(work.title)
  };

  book.annotation = buildAnnotation(book, hash);
  book.searchText = buildSearchText(book, work);
  book.tags = [
    ...book.genres, ...book.themes, ...book.mood, book.pace,
    pages <= 250 ? 'короткая книга' : pages >= 600 ? 'длинная книга' : 'средний объём'
  ];
  catalog.push(book);

  if (catalog.length === 1000) break;
}

await fs.writeFile(
  path.join(dataDir, 'catalog.json'),
  JSON.stringify(catalog, null, 2),
  'utf8'
);

const report = {
  generatedAt: new Date().toISOString(),
  sourceRecords: source.length,
  candidates: candidates.length,
  books: catalog.length,
  authors: new Set(catalog.flatMap((book) => book.authors)).size,
  withCyrillicTitles: catalog.filter((book) => cyrillic.test(book.title)).length,
  withCovers: catalog.filter((book) => book.coverId).length,
  genres: Object.fromEntries(
    [...new Set(catalog.flatMap((book) => book.genres))]
      .sort()
      .map((genre) => [genre, catalog.filter((book) => book.genres.includes(genre)).length])
  )
};

await fs.writeFile(
  path.join(dataDir, 'catalog-report.json'),
  JSON.stringify(report, null, 2),
  'utf8'
);

console.log(JSON.stringify(report, null, 2));
