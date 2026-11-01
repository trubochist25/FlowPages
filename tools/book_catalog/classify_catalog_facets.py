from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder


DATA = ROOT / "data" / "book_catalog"
CATALOG_PATH = DATA / "catalog.json"
WORKS_PATH = DATA / "work-metadata-cache.json"
TRANSLATIONS_PATH = DATA / "work-metadata-ru.json"
OUTPUT_PATH = DATA / "semantic-facets.json"

FICTION_GENRES = {
    "Ужасы": "страшная художественная литература, хоррор, пугающая история, кошмары и сверхъестественная угроза",
    "Триллеры": "напряжённый триллер, опасность, преследование, заговор, саспенс и быстрый сюжет",
    "Детективы": "детективное произведение, расследование преступления, убийство, поиск улик и разгадка тайны",
    "Фантастика": "научная фантастика, будущее, космос, технологии, роботы, антиутопия или альтернативная реальность",
    "Фэнтези": "фэнтези, магия, волшебники, мифические существа, вымышленный мир и героическое приключение",
    "Романтика": "любовный роман, романтические отношения, влюблённость, брак и эмоциональный выбор пары",
    "Приключения": "приключенческая история, путешествие, экспедиция, квест, опасности, открытия и испытания",
    "Историческая проза": "исторический роман или художественная проза о событиях и людях прошлого",
    "Юмор": "юмористическая литература, комедия, ирония, сатира, забавные ситуации и остроумие",
    "Поэзия": "поэзия, стихи, поэмы, лирические произведения и стихотворные сборники",
    "Подростковая литература": "литература для подростков, школьники, первая любовь, взросление и поиск себя",
    "Детская литература": "детская книга, сказка, семейное чтение, история для детей и младших читателей",
    "Комиксы и манга": "комикс, графический роман, манга, последовательное визуальное повествование",
    "Классическая литература": "классическое художественное произведение, каноническая литература прошлых эпох",
    "Современная проза": "современный художественный роман о людях, отношениях и повседневной жизни",
}

NONFICTION_GENRES = {
    "Психология": "психология, эмоции, мышление, психическое здоровье и поведение человека",
    "Саморазвитие": "саморазвитие, привычки, мотивация, продуктивность, жизненные навыки и личный рост",
    "Бизнес и экономика": "бизнес, предпринимательство, менеджмент, экономика, финансы, маркетинг и лидерство",
    "История": "документальная история стран, обществ, войн, эпох и исторических событий",
    "Биографии и мемуары": "биография, автобиография, мемуары, воспоминания и жизнь реального человека",
    "Научно-популярная литература": "научно-популярная книга, физика, биология, космос, математика и устройство природы",
    "Философия": "философия, этика, идеи о познании, морали, сознании и смысле жизни",
    "Искусство и культура": "искусство, живопись, музыка, кино, архитектура, литература и история культуры",
    "Здоровье": "здоровье, медицина, заболевания, лечение, питание, фитнес и образ жизни",
    "Родительство": "родительство, воспитание детей, развитие ребёнка и отношения в семье",
    "Компьютеры и технологии": "компьютеры, программирование, разработка программ, интернет и цифровые технологии",
    "Религия": "религия, богословие, духовные традиции, вера и священные тексты",
}

THEMES = {
    "расследование и тайны": "тайна, загадка, расследование, преступление, улики и поиск истины",
    "любовь и отношения": "любовь, романтические отношения, близость, брак и расставание",
    "семья и поколения": "семья, родители и дети, родственники, семейные конфликты и поколения",
    "дружба и взаимопомощь": "дружба, верность, поддержка, команда и взаимопомощь",
    "война и её последствия": "война, фронт, солдаты, вооружённый конфликт, травма и последствия войны",
    "власть и общество": "власть, политика, государство, социальная иерархия, несправедливость и общество",
    "магия и сверхъестественное": "магия, сверхъестественные силы, волшебство, колдовство и мифические существа",
    "будущее и технологии": "будущее, технологии, искусственный интеллект, роботы, антиутопия и цифровой мир",
    "космос и открытия": "космос, планеты, звёзды, вселенная, астрономия и научные открытия",
    "путешествия и приключения": "путешествие, дорога, экспедиция, приключение и открытие новых мест",
    "выживание и испытания": "выживание, опасность, катастрофа, тяжёлые испытания и борьба за жизнь",
    "взросление и поиск себя": "взросление, подростковый возраст, самоопределение, идентичность и поиск себя",
    "страх и неизвестность": "страх, ужас, тревога, неизвестная угроза и пугающая тайна",
    "история и память": "историческая память, прошлое, воспоминания, наследие и влияние истории",
    "мышление и поведение": "мышление, психология, эмоции, решения и поведение человека",
    "привычки и личный рост": "привычки, мотивация, дисциплина, саморазвитие и личный рост",
    "деньги и управление": "деньги, финансы, инвестиции, предпринимательство, менеджмент и управление",
    "наука и устройство мира": "наука, природа, физика, биология, закономерности и устройство мира",
    "здоровье и образ жизни": "здоровье, медицина, питание, сон, физическая активность и образ жизни",
    "искусство и творчество": "искусство, творчество, литература, музыка, живопись и работа автора",
    "смысл жизни и выбор": "смысл жизни, мораль, этика, свобода, ответственность и сложный выбор",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def choose(scores: np.ndarray, labels: list[str], limit: int, delta: float) -> tuple[list[str], dict[str, float]]:
    order = np.argsort(-scores)
    top = float(scores[order[0]])
    selected = [labels[index] for index in order if float(scores[index]) >= top - delta][:limit]
    return selected, {labels[index]: round(float(scores[index]), 4) for index in order[:6]}


def main() -> None:
    catalog = read_json(CATALOG_PATH)
    works = read_json(WORKS_PATH)
    translated = read_json(TRANSLATIONS_PATH)
    settings = Settings.from_env()
    embedder = E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
    )

    passages = []
    domains = []
    for book in catalog:
        work = works[book["workKey"]]
        description = translated.get(book["workKey"], {}).get("descriptionRu") or work.get("description", "")
        subjects = "; ".join(work.get("subjects", [])[:30])
        passages.append(
            f"Название: {book['title']}. Оригинальное название: {book['sourceTitle']}. "
            f"Описание содержания: {description[:2500]}. Библиотечные рубрики: {subjects[:1400]}."
        )
        current = set(book.get("genres", []))
        fiction_votes = len(current & set(FICTION_GENRES))
        nonfiction_votes = len(current & set(NONFICTION_GENRES))
        domains.append("nonfiction" if nonfiction_votes > fiction_votes else "fiction")

    passage_vectors = embedder.encode_passages(passages)
    fiction_labels = list(FICTION_GENRES)
    nonfiction_labels = list(NONFICTION_GENRES)
    fiction_vectors = embedder.encode_queries(list(FICTION_GENRES.values()))
    nonfiction_vectors = embedder.encode_queries(list(NONFICTION_GENRES.values()))
    theme_labels = list(THEMES)
    theme_vectors = embedder.encode_queries(list(THEMES.values()))

    output = []
    for index, book in enumerate(catalog):
        vector = passage_vectors[index]
        if domains[index] == "fiction":
            labels = fiction_labels
            genre_scores = fiction_vectors @ vector
        else:
            labels = nonfiction_labels
            genre_scores = nonfiction_vectors @ vector
        genres, genre_top = choose(genre_scores, labels, 3, 0.035)
        if domains[index] == "fiction" and book["year"] < 1970 and "Классическая литература" not in genres:
            genres = (genres[:2] + ["Классическая литература"])[:3]

        themes, theme_top = choose(theme_vectors @ vector, theme_labels, 4, 0.045)
        output.append({
            "catalogId": book["id"],
            "workKey": book["workKey"],
            "domain": domains[index],
            "genres": genres,
            "themes": themes,
            "genreScores": genre_top,
            "themeScores": theme_top,
        })

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Semantic facets generated: {len(output)}")


if __name__ == "__main__":
    main()
