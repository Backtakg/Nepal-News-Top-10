import os
import re
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://gnews.io/api/v4/search"

API_KEY = os.environ.get("NEWS_API_KEY", "").strip()

OUTPUT_FILE = Path("news.json")

MAX_PER_CATEGORY = 10

REQUEST_TIMEOUT = 30

# GNews free tier allows 100 requests/day.
# We use exactly 10 requests per workflow run.
REQUEST_DELAY = 1.2


# ============================================================
# REQUIRED SECTIONS
# ============================================================

SECTIONS = [
    "weather",
    "national",
    "politics",
    "business",
    "sports",
    "technology",
    "entertainment",
    "world",
    "health",
    "crime",
]


# ============================================================
# CATEGORY SEARCH QUERIES
# ============================================================

# These are deliberately targeted toward Nepal.
#
# The API searches title + description.
# We use OR heavily so that one narrow keyword does not
# cause an entire category to become empty.

QUERIES = {

    "weather": (
        'Nepal weather OR Nepal rainfall OR Nepal flood OR '
        'Nepal monsoon OR Nepal landslide OR Nepal storm OR '
        'Nepal temperature OR Nepal climate'
    ),

    "national": (
        'Nepal OR Kathmandu OR government of Nepal OR '
        'Nepal country'
    ),

    "politics": (
        'Nepal politics OR Nepal government OR parliament Nepal OR '
        'Nepal election OR prime minister Nepal OR president Nepal OR '
        'Nepali Congress OR UML Nepal'
    ),

    "business": (
        'Nepal business OR Nepal economy OR Nepal bank OR '
        'NEPSE OR Nepal investment OR Nepal trade OR '
        'Nepal tourism OR Nepal finance'
    ),

    "sports": (
        'Nepal cricket OR Nepal football OR Nepal sports OR '
        'Nepal tournament OR Nepali athlete OR '
        'Nepal national team OR ICC Nepal'
    ),

    "technology": (
        'Nepal technology OR Nepal tech OR Nepal AI OR '
        'Nepal digital OR Nepal startup OR Nepal cybersecurity OR '
        'Nepal internet'
    ),

    "entertainment": (
        'Nepal entertainment OR Nepali movie OR Nepali film OR '
        'Nepali music OR Nepali actor OR Nepali singer OR '
        'Nepal cinema OR Nepali celebrity'
    ),

    "world": (
        'world news OR international news OR India OR China OR '
        'United States OR Europe OR Middle East OR Ukraine OR '
        'Russia OR Israel OR Iran'
    ),

    "health": (
        'Nepal health OR Nepal hospital OR Nepal disease OR '
        'Nepal doctor OR Nepal medicine OR Nepal healthcare OR '
        'Nepal dengue OR Nepal outbreak'
    ),

    "crime": (
        'Nepal crime OR Nepal police OR Nepal arrest OR '
        'Nepal murder OR Nepal fraud OR Nepal robbery OR '
        'Nepal court OR Nepal investigation OR Nepal accident'
    ),
}


# ============================================================
# CATEGORY KEYWORDS
# ============================================================

# Used as a second filtering/ranking layer.
# This helps prevent unrelated results from appearing
# in a category simply because the search engine returned them.

CATEGORY_KEYWORDS = {

    "weather": [
        "weather",
        "rain",
        "rainfall",
        "flood",
        "flooding",
        "monsoon",
        "landslide",
        "storm",
        "temperature",
        "climate",
        "snow",
        "thunderstorm",
        "lightning",
        "heatwave",
        "cold wave",
        "forecast",
    ],

    "national": [
        "nepal",
        "kathmandu",
        "government",
        "nation",
        "national",
        "ministry",
        "province",
        "municipality",
    ],

    "politics": [
        "politics",
        "political",
        "government",
        "minister",
        "prime minister",
        "president",
        "parliament",
        "election",
        "party",
        "coalition",
        "cabinet",
        "uml",
        "congress",
        "maoist",
    ],

    "business": [
        "business",
        "economy",
        "economic",
        "bank",
        "banking",
        "finance",
        "market",
        "nepse",
        "stock",
        "investment",
        "trade",
        "tourism",
        "company",
        "industry",
        "remittance",
    ],

    "sports": [
        "sports",
        "sport",
        "cricket",
        "football",
        "soccer",
        "match",
        "tournament",
        "league",
        "player",
        "athlete",
        "fifa",
        "icc",
        "championship",
        "olympic",
    ],

    "technology": [
        "technology",
        "tech",
        "artificial intelligence",
        "ai",
        "digital",
        "software",
        "internet",
        "cyber",
        "cybersecurity",
        "computer",
        "startup",
        "app",
        "mobile",
    ],

    "entertainment": [
        "entertainment",
        "movie",
        "film",
        "cinema",
        "music",
        "actor",
        "actress",
        "singer",
        "concert",
        "television",
        "celebrity",
        "festival",
    ],

    "world": [
        "world",
        "international",
        "india",
        "china",
        "america",
        "united states",
        "usa",
        "europe",
        "russia",
        "ukraine",
        "israel",
        "iran",
        "pakistan",
        "middle east",
    ],

    "health": [
        "health",
        "hospital",
        "doctor",
        "disease",
        "medical",
        "medicine",
        "patient",
        "healthcare",
        "virus",
        "outbreak",
        "dengue",
        "infection",
        "vaccine",
        "epidemic",
    ],

    "crime": [
        "crime",
        "police",
        "arrest",
        "murder",
        "fraud",
        "robbery",
        "theft",
        "court",
        "criminal",
        "investigation",
        "accident",
        "abuse",
        "drug",
        "scam",
    ],
}


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; NepalNewsTop10/1.0; "
        "+https://github.com/Backtakg/Nepal-News-Top-10)"
    ),
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    """
    Remove HTML and normalize whitespace.
    """

    if value is None:
        return ""

    value = str(value)

    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_title(title):
    """
    Used for duplicate detection.
    """

    title = clean_text(title).lower()

    title = re.sub(
        r"[^a-z0-9\u0900-\u097f]+",
        " ",
        title,
    )

    return re.sub(r"\s+", " ", title).strip()


def article_id(title, url):
    """
    Stable article identifier.
    """

    value = (
        normalize_title(title)
        + "|"
        + str(url).strip().lower()
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def parse_datetime(value):
    """
    Convert GNews publishedAt into a sortable timestamp.
    """

    if not value:
        return 0

    try:
        value = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.timestamp()

    except Exception:
        return 0


def one_sentence(text, fallback):
    """
    Convert description/content into one clean sentence.
    """

    text = clean_text(text)

    if not text:
        return fallback

    # Remove common feed prefixes.
    text = re.sub(
        r"^(read more|continue reading)\s*[:\-]?\s*",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    # Split into sentences.
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    sentence = sentences[0].strip()

    # Sometimes descriptions start with a very short fragment.
    if len(sentence) < 35 and len(sentences) > 1:
        sentence = (
            sentence + " " + sentences[1].strip()
        )

    # Keep summaries suitable for your frontend.
    if len(sentence) > 280:
        sentence = (
            sentence[:277]
            .rsplit(" ", 1)[0]
            + "..."
        )

    if not sentence.endswith(
        (".", "!", "?")
    ):
        sentence += "."

    return sentence


def keyword_score(article, section):
    """
    Score how strongly an article belongs to a category.
    """

    title = clean_text(
        article.get("title", "")
    ).lower()

    description = clean_text(
        article.get("description", "")
    ).lower()

    text = title + " " + description

    score = 0

    for keyword in CATEGORY_KEYWORDS.get(
        section,
        [],
    ):

        keyword = keyword.lower()

        if keyword in title:
            score += 5

        elif keyword in description:
            score += 2

        elif keyword in text:
            score += 1

    return score


def article_quality_score(article, section):
    """
    Ranking score.

    More relevant articles receive a higher score.
    Recent articles receive a smaller bonus.
    """

    score = keyword_score(
        article,
        section,
    )

    title = clean_text(
        article.get("title", "")
    ).lower()

    important_words = [
        "breaking",
        "latest",
        "major",
        "update",
        "decision",
        "government",
        "prime minister",
        "president",
        "election",
        "flood",
        "earthquake",
        "landslide",
        "storm",
        "war",
        "death",
        "victory",
    ]

    for word in important_words:
        if word in title:
            score += 2

    published = parse_datetime(
        article.get("publishedAt")
    )

    if published:
        # Small freshness bonus.
        age_hours = max(
            0,
            (
                datetime.now(timezone.utc).timestamp()
                - published
            ) / 3600,
        )

        if age_hours < 6:
            score += 5

        elif age_hours < 24:
            score += 3

        elif age_hours < 72:
            score += 1

    return score


def is_valid_article(article):
    """
    Make sure the API returned usable article data.
    """

    if not isinstance(article, dict):
        return False

    title = clean_text(
        article.get("title")
    )

    url = clean_text(
        article.get("url")
    )

    if not title:
        return False

    if not url:
        return False

    if not url.startswith(
        ("http://", "https://")
    ):
        return False

    # GNews sometimes returns "[Removed]"
    # for unavailable articles.
    if title.lower() in {
        "[removed]",
        "removed",
    }:
        return False

    return True


# ============================================================
# GNEWS REQUEST
# ============================================================

def fetch_category(section):
    """
    Fetch one category from GNews.
    """

    query = QUERIES[section]

    params = {
        "q": query,
        "lang": "en",
        "country": "np",
        "max": 10,
        "sortby": "publishedAt",
        "apikey": API_KEY,
    }

    print("")
    print("=" * 70)
    print(f"FETCHING: {section.upper()}")
    print(f"Query: {query}")

    try:

        response = session.get(
            API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            "HTTP status:",
            response.status_code,
        )

        if response.status_code != 200:

            try:
                error_data = response.json()
            except Exception:
                error_data = response.text[:500]

            raise RuntimeError(
                f"GNews API error "
                f"{response.status_code}: "
                f"{error_data}"
            )

        data = response.json()

        articles = data.get(
            "articles",
            [],
        )

        if not isinstance(
            articles,
            list,
        ):
            articles = []

        print(
            "API returned:",
            len(articles),
            "articles",
        )

        return articles

    except requests.RequestException as error:

        raise RuntimeError(
            f"Network error: {error}"
        ) from error


# ============================================================
# CONVERT GNEWS ARTICLE
# ============================================================

def convert_article(article, section):
    """
    Convert GNews response to your site's exact format.
    """

    title = clean_text(
        article.get("title")
    )

    description = clean_text(
        article.get("description")
    )

    content = clean_text(
        article.get("content")
    )

    url = clean_text(
        article.get("url")
    )

    published = clean_text(
        article.get("publishedAt")
    )

    source = article.get(
        "source",
        {},
    )

    if not isinstance(
        source,
        dict,
    ):
        source = {}

    source_name = clean_text(
        source.get("name")
    )

    if not source_name:
        source_name = "GNews source"

    summary_source = (
        description
        or content
        or title
    )

    summary = one_sentence(
        summary_source,
        "Read the original article for the latest information.",
    )

    return {
        "id": article_id(
            title,
            url,
        ),

        "title": title,

        "summary": summary,

        "source": source_name,

        "link": url,

        "published": published,

        "section": section,
    }


# ============================================================
# LOAD EXISTING DATABASE
# ============================================================

def load_existing_database():
    """
    Load the previous news.json.

    This is important:
    if the API fails, we don't destroy a good database
    with empty arrays.
    """

    if not OUTPUT_FILE.exists():
        return None

    try:

        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(
            data,
            dict,
        ):
            return None

        sections = data.get(
            "sections"
        )

        if not isinstance(
            sections,
            dict,
        ):
            return None

        return data

    except Exception as error:

        print(
            "Could not load existing news.json:",
            error,
        )

        return None


# ============================================================
# BUILD DATABASE
# ============================================================

def build_database():
    """
    Fetch every category and create the final database.
    """

    if not API_KEY:

        raise RuntimeError(
            "GNEWS_API_KEY is missing. "
            "Add it to GitHub repository "
            "Settings > Secrets and variables > Actions."
        )

    result = {
        section: []
        for section in SECTIONS
    }

    diagnostics = {
        "successful_categories": [],
        "failed_categories": [],
        "api_articles": 0,
        "final_articles": 0,
    }

    global_seen_urls = set()
    global_seen_titles = set()

    for index, section in enumerate(
        SECTIONS
    ):

        try:

            raw_articles = fetch_category(
                section
            )

            diagnostics[
                "api_articles"
            ] += len(raw_articles)

            candidates = []

            for raw in raw_articles:

                if not is_valid_article(
                    raw
                ):
                    continue

                title = clean_text(
                    raw.get("title")
                )

                url = clean_text(
                    raw.get("url")
                )

                normalized = normalize_title(
                    title
                )

                # Remove duplicates globally.
                if url in global_seen_urls:
                    continue

                if normalized in global_seen_titles:
                    continue

                # Calculate category relevance.
                relevance = keyword_score(
                    raw,
                    section,
                )

                # Because GNews already selected the article
                # for our query, we allow it even if keyword
                # scoring is low. This prevents empty sections.
                candidates.append(
                    (
                        article_quality_score(
                            raw,
                            section,
                        ),
                        raw,
                        relevance,
                    )
                )

            # Highest quality first.
            candidates.sort(
                key=lambda item: (
                    item[0],
                    parse_datetime(
                        item[1].get(
                            "publishedAt"
                        )
                    ),
                ),
                reverse=True,
            )

            selected = []

            for score, raw, relevance in candidates:

                if len(selected) >= MAX_PER_CATEGORY:
                    break

                converted = convert_article(
                    raw,
                    section,
                )

                url = converted["link"]

                normalized = normalize_title(
                    converted["title"]
                )

                if url in global_seen_urls:
                    continue

                if normalized in global_seen_titles:
                    continue

                global_seen_urls.add(url)
                global_seen_titles.add(
                    normalized
                )

                selected.append(
                    converted
                )

            result[section] = selected

            diagnostics[
                "successful_categories"
            ].append(section)

            diagnostics[
                "final_articles"
            ] += len(selected)

            print(
                f"{section}: "
                f"{len(selected)} selected"
            )

        except Exception as error:

            print(
                f"FAILED CATEGORY: {section}"
            )

            print(
                "Reason:",
                error,
            )

            diagnostics[
                "failed_categories"
            ].append({
                "section": section,
                "error": str(error),
            })

        # Stay below API rate limits.
        if index < len(SECTIONS) - 1:
            time.sleep(
                REQUEST_DELAY
            )

    return result, diagnostics


# ============================================================
# SAFE WRITE
# ============================================================

def write_database(
    sections,
    diagnostics,
):
    """
    Write news.json only when we have usable data.
    """

    total = sum(
        len(sections.get(section, []))
        for section in SECTIONS
    )

    existing = load_existing_database()

    # --------------------------------------------------------
    # IMPORTANT SAFETY CHECK
    # --------------------------------------------------------

    if total == 0:

        print("")
        print("=" * 70)
        print("ERROR: ZERO ARTICLES")
        print("=" * 70)

        if existing:

            print(
                "Keeping previous news.json."
            )

            return False

        raise RuntimeError(
            "GNews returned zero usable articles "
            "and no previous news.json exists."
        )

    updated = datetime.now(
        timezone.utc
    ).isoformat()

    output = {
        "updated": updated,

        "provider": "GNews",

        "sections": {
            section: sections.get(
                section,
                [],
            )[:MAX_PER_CATEGORY]
            for section in SECTIONS
        },

        "diagnostics": diagnostics,
    }

    temporary_file = Path(
        "news.json.tmp"
    )

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temporary_file.replace(
        OUTPUT_FILE
    )

    print("")
    print("=" * 70)
    print("NEWS DATABASE UPDATED")
    print("=" * 70)

    print(
        "Updated:",
        updated,
    )

    print(
        "Total articles:",
        total,
    )

    for section in SECTIONS:

        print(
            f"  {section:15} "
            f"{len(output['sections'][section])}"
        )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("NEPAL NEWS TOP 10 SCRAPER")
    print("=" * 70)

    print(
        "Provider: GNews API"
    )

    print(
        "Output:",
        OUTPUT_FILE,
    )

    print(
        "Categories:",
        len(SECTIONS),
    )

    print(
        "Maximum articles/category:",
        MAX_PER_CATEGORY,
    )

    # Never print the API key.

    try:

        sections, diagnostics = (
            build_database()
        )

        write_database(
            sections,
            diagnostics,
        )

        print("")
        print(
            "Scraper completed successfully."
        )

    except Exception as error:

        print("")
        print("=" * 70)
        print("SCRAPER FAILED")
        print("=" * 70)

        print(
            str(error)
        )

        # Do not overwrite news.json.
        raise


if __name__ == "__main__":
    main()
