import json
import re
import hashlib
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

OUTPUT_FILE = "news.json"

MAX_PER_CATEGORY = 10
MAX_ENTRIES_PER_SOURCE = 50

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NepalNewsTop10/2.0; "
        "+https://github.com/Backtakg/Nepal-News-Top-10)"
    ),
    "Accept": (
        "application/rss+xml, application/xml, text/xml, "
        "text/html;q=0.9, */*;q=0.8"
    ),
}

SECTIONS = [
    "national",
    "politics",
    "business",
    "sports",
    "technology",
    "entertainment",
    "world",
    "crime",
    "health",
    "weather",
]


# ============================================================
# DIRECT NEWS SOURCES
# ============================================================

SOURCES = [
    {
        "name": "The Kathmandu Post",
        "url": "https://kathmandupost.com/rss",
    },
    {
        "name": "OnlineKhabar",
        "url": "https://www.onlinekhabar.com/feed",
    },
    {
        "name": "Setopati",
        "url": "https://www.setopati.com/feed",
    },
    {
        "name": "Ratopati",
        "url": "https://www.ratopati.com/feed",
    },
    {
        "name": "The Himalayan Times",
        "url": "https://thehimalayantimes.com/rssFeed",
    },
    {
        "name": "Nepali Times",
        "url": "https://www.nepalitimes.com/feed/",
    },
    {
        "name": "Ujyaalo Online",
        "url": "https://ujyaaloonline.com/rss",
    },
    {
        "name": "Nagarik News",
        "url": "https://nagariknews.nagariknetwork.com/feed",
    },
    {
        "name": "Naya Patrika",
        "url": "https://www.nayapatrikadaily.com/feed",
    },
    {
        "name": "Baahrakhari",
        "url": "https://baahrakhari.com/feed",
    },
    {
        "name": "Gorkhapatra Online",
        "url": "https://gorkhapatraonline.com/rss",
    },
    {
        "name": "The Rising Nepal",
        "url": "https://risingnepaldaily.com/rss",
    },
]


# ============================================================
# GOOGLE NEWS RSS FALLBACK
#
# These are NOT used instead of working official sources.
# They are used when direct feeds don't provide enough articles.
# ============================================================

GOOGLE_QUERIES = {
    "national": "Nepal national news",
    "politics": "Nepal politics government parliament",
    "business": "Nepal business economy NEPSE",
    "sports": "Nepal sports cricket football",
    "technology": "Nepal technology AI cyber",
    "entertainment": "Nepal entertainment movies music",
    "world": "Nepal world international news",
    "crime": "Nepal crime police court arrest",
    "health": "Nepal health hospital disease",
    "weather": "Nepal weather rainfall flood monsoon landslide storm",
}


# ============================================================
# CATEGORY KEYWORDS
# ============================================================

KEYWORDS = {
    "politics": [
        "government",
        "minister",
        "parliament",
        "election",
        "political",
        "prime minister",
        "cabinet",
        "party",
        "president",
        "coalition",
        "ruling",
        "opposition",
        "lawmaker",
        "senator",
        "constitution",
    ],

    "business": [
        "business",
        "economy",
        "economic",
        "bank",
        "market",
        "company",
        "trade",
        "finance",
        "investment",
        "stock",
        "nepse",
        "remittance",
        "industry",
        "tourism",
        "startup",
        "shares",
        "inflation",
        "interest rate",
    ],

    "sports": [
        "football",
        "cricket",
        "sport",
        "tournament",
        "player",
        "match",
        "league",
        "championship",
        "olympic",
        "athlete",
        "fifa",
        "icc",
        "goal",
        "wicket",
        "runs",
        "coach",
    ],

    "technology": [
        "technology",
        "technology",
        "tech",
        "digital",
        "artificial intelligence",
        "ai",
        "software",
        "internet",
        "cyber",
        "computer",
        "app",
        "startup",
        "robot",
        "data",
        "smartphone",
        "google",
        "microsoft",
        "apple",
    ],

    "entertainment": [
        "movie",
        "film",
        "music",
        "actor",
        "actress",
        "entertainment",
        "concert",
        "singer",
        "cinema",
        "television",
        "celebrity",
        "bollywood",
        "hollywood",
        "album",
        "song",
    ],

    "world": [
        "world",
        "international",
        "india",
        "china",
        "america",
        "iran",
        "israel",
        "usa",
        "ukraine",
        "russia",
        "pakistan",
        "united states",
        "europe",
        "britain",
        "global",
        "foreign",
    ],

    "crime": [
        "crime",
        "police",
        "arrest",
        "murder",
        "fraud",
        "accident",
        "security",
        "court",
        "criminal",
        "investigation",
        "robbery",
        "abuse",
        "theft",
        "scam",
        "kidnap",
        "corruption",
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
        "cancer",
        "vaccine",
        "epidemic",
        "infection",
    ],

    "weather": [
        "weather",
        "rain",
        "rainfall",
        "flood",
        "flooding",
        "storm",
        "snow",
        "temperature",
        "monsoon",
        "landslide",
        "climate",
        "thunderstorm",
        "heatwave",
        "cold wave",
        "heavy rain",
        "wind",
    ],
}


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""

    soup = BeautifulSoup(str(value), "html.parser")

    text = soup.get_text(" ", strip=True)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_title(title):
    title = clean_text(title).lower()

    title = re.sub(
        r"[^a-z0-9\u0900-\u097f\s]",
        " ",
        title,
    )

    title = re.sub(r"\s+", " ", title)

    return title.strip()


def article_id(title):
    return hashlib.sha256(
        normalize_title(title).encode("utf-8")
    ).hexdigest()[:20]


def parse_date(value):
    if not value:
        return 0

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.timestamp()

    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        return dt.timestamp()

    except Exception:
        return 0


def iso_date(value):
    timestamp = parse_date(value)

    if not timestamp:
        return ""

    return datetime.fromtimestamp(
        timestamp,
        timezone.utc,
    ).isoformat()


# ============================================================
# ONE-SENTENCE SUMMARY
# ============================================================

def one_sentence(text, title=""):
    """
    Creates a short extractive one-sentence summary.

    We deliberately don't invent facts.
    The scraper takes the first useful sentence from
    the publisher's RSS description or metadata.
    """

    text = clean_text(text)

    if not text:
        text = clean_text(title)

    if not text:
        return "Latest news update."

    # Remove common junk.
    text = re.sub(
        r"^(read more|click here|advertisement)\s*[:\-]?\s*",
        "",
        text,
        flags=re.I,
    )

    # Split sentences.
    sentences = re.split(
        r"(?<=[.!?।])\s+",
        text,
    )

    sentence = ""

    for item in sentences:
        item = item.strip()

        if len(item) >= 30:
            sentence = item
            break

    if not sentence:
        sentence = text

    # Avoid extremely long descriptions.
    if len(sentence) > 280:
        sentence = (
            sentence[:277]
            .rsplit(" ", 1)[0]
            + "..."
        )

    if not sentence.endswith((".", "!", "?", "।")):
        sentence += "."

    return sentence


# ============================================================
# CATEGORY CLASSIFICATION
# ============================================================

def classify(title, summary):
    text = (
        clean_text(title)
        + " "
        + clean_text(summary)
    ).lower()

    scores = {
        section: 0
        for section in KEYWORDS
    }

    for section, words in KEYWORDS.items():
        for word in words:
            if word in text:
                scores[section] += 1

    best = max(
        scores,
        key=scores.get,
    )

    best_score = scores[best]

    if best_score == 0:
        return "national"

    return best


# ============================================================
# IMAGE EXTRACTION
#
# Images are stored separately from summary.
# They are NEVER inserted into the summary.
# ============================================================

def extract_image(entry, article_url):
    # RSS media fields.
    for key in [
        "media_content",
        "media_thumbnail",
    ]:
        values = entry.get(key, [])

        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    url = item.get("url")

                    if url:
                        return url

    # Enclosure.
    enclosure = entry.get("enclosures", [])

    if isinstance(enclosure, list):
        for item in enclosure:
            if isinstance(item, dict):
                url = item.get("href") or item.get("url")

                if url:
                    return url

    # Try article OpenGraph image.
    if article_url:
        try:
            response = requests.get(
                article_url,
                headers=HEADERS,
                timeout=10,
            )

            if response.ok:
                soup = BeautifulSoup(
                    response.text,
                    "html.parser",
                )

                for prop in [
                    "og:image",
                    "twitter:image",
                ]:
                    meta = soup.find(
                        "meta",
                        attrs={
                            "property": prop,
                        },
                    )

                    if not meta:
                        meta = soup.find(
                            "meta",
                            attrs={
                                "name": prop,
                            },
                        )

                    if meta and meta.get("content"):
                        return meta["content"]

        except Exception:
            pass

    return ""


# ============================================================
# FETCH RSS
# ============================================================

def fetch_feed(source):
    print("")
    print("=" * 70)
    print("SOURCE:", source["name"])
    print("URL:", source["url"])

    try:
        response = requests.get(
            source["url"],
            headers=HEADERS,
            timeout=25,
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content,
        )

        entries = feed.entries

        if not entries:
            raise RuntimeError(
                "RSS feed returned zero entries"
            )

        print(
            "SUCCESS:",
            len(entries),
            "entries",
        )

        return entries

    except Exception as error:
        print(
            "FAILED:",
            source["name"],
            "-",
            error,
        )

        return []


# ============================================================
# GOOGLE NEWS FALLBACK
# ============================================================

def google_news_feed(section):
    query = GOOGLE_QUERIES[section]

    url = (
        "https://news.google.com/rss/search?"
        "q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    return fetch_feed({
        "name": "Google News — " + section.title(),
        "url": url,
    })


# ============================================================
# CONVERT ENTRY
# ============================================================

def convert_entry(entry, source_name, forced_section=None):
    title = clean_text(
        entry.get("title", "")
    )

    link = clean_text(
        entry.get("link", "")
    )

    if not title or not link:
        return None

    summary = clean_text(
        entry.get("summary")
        or entry.get("description")
        or ""
    )

    published_raw = (
        entry.get("published")
        or entry.get("updated")
        or entry.get("created")
        or ""
    )

    published = iso_date(
        published_raw
    )

    section = (
        forced_section
        if forced_section
        else classify(
            title,
            summary,
        )
    )

    image = extract_image(
        entry,
        link,
    )

    return {
        "id": article_id(title),
        "title": title,
        "summary": one_sentence(
            summary,
            title,
        ),
        "source": source_name,
        "link": link,
        "published": published,
        "section": section,
        "image": image,
    }


# ============================================================
# RANKING
# ============================================================

def rank_article(article):
    """
    Newer articles rank higher.
    Slight keyword relevance boost.
    """

    timestamp = parse_date(
        article.get("published", "")
    )

    title = article["title"].lower()

    boost_words = [
        "breaking",
        "latest",
        "major",
        "urgent",
        "new",
        "announced",
        "government",
        "minister",
        "election",
        "flood",
        "earthquake",
        "storm",
    ]

    boost = 0

    for word in boost_words:
        if word in title:
            boost += 1

    return timestamp + (boost * 3600)


# ============================================================
# MAIN
# ============================================================

def main():

    all_articles = []

    seen_urls = set()
    seen_titles = set()

    working_sources = []
    failed_direct_sources = []

    # --------------------------------------------------------
    # STEP 1 — DIRECT SOURCES
    # --------------------------------------------------------

    for source in SOURCES:

        entries = fetch_feed(source)

        if not entries:
            failed_direct_sources.append(
                source["name"]
            )
            continue

        working_sources.append(
            source["name"]
        )

        for entry in entries[
            :MAX_ENTRIES_PER_SOURCE
        ]:

            article = convert_entry(
                entry,
                source["name"],
            )

            if not article:
                continue

            normalized = normalize_title(
                article["title"]
            )

            if article["link"] in seen_urls:
                continue

            if normalized in seen_titles:
                continue

            seen_urls.add(
                article["link"]
            )

            seen_titles.add(
                normalized
            )

            all_articles.append(
                article
            )

    print("")
    print("=" * 70)
    print("DIRECT ARTICLES:", len(all_articles))

    # --------------------------------------------------------
    # STEP 2 — FILL CATEGORIES WITH GOOGLE NEWS RSS
    #
    # Only fetch fallback for categories that have fewer
    # than 10 stories.
    # --------------------------------------------------------

    category_counts = {
        section: 0
        for section in SECTIONS
    }

    for article in all_articles:
        if article["section"] in category_counts:
            category_counts[
                article["section"]
            ] += 1

    for section in SECTIONS:

        if section == "national":
            continue

        if category_counts[section] >= MAX_PER_CATEGORY:
            continue

        print("")
        print(
            "Fallback required for:",
            section,
        )

        entries = google_news_feed(
            section
        )

        for entry in entries[
            :MAX_ENTRIES_PER_SOURCE
        ]:

            article = convert_entry(
                entry,
                "Google News",
                forced_section=section,
            )

            if not article:
                continue

            normalized = normalize_title(
                article["title"]
            )

            if article["link"] in seen_urls:
                continue

            if normalized in seen_titles:
                continue

            seen_urls.add(
                article["link"]
            )

            seen_titles.add(
                normalized
            )

            all_articles.append(
                article
            )

    # --------------------------------------------------------
    # STEP 3 — REMOVE EMPTY / INVALID ARTICLES
    # --------------------------------------------------------

    all_articles = [
        article
        for article in all_articles
        if article.get("title")
        and article.get("link")
        and article.get("summary")
    ]

    # --------------------------------------------------------
    # STEP 4 — RANK
    # --------------------------------------------------------

    all_articles.sort(
        key=rank_article,
        reverse=True,
    )

    # --------------------------------------------------------
    # STEP 5 — BUILD 10 CATEGORIES × 10 STORIES
    # --------------------------------------------------------

    result = {
        section: []
        for section in SECTIONS
    }

    for article in all_articles:

        section = article["section"]

        if section not in result:
            continue

        if len(result[section]) >= MAX_PER_CATEGORY:
            continue

        # Frontend-compatible object.
        result[section].append({
            "title": article["title"],
            "summary": article["summary"],
            "source": article["source"],
            "link": article["link"],
            "published": article["published"],
            "image": article["image"],
        })

    # --------------------------------------------------------
    # STEP 6 — TOP 10 OVERALL
    # --------------------------------------------------------

    overall = sorted(
        all_articles,
        key=rank_article,
        reverse=True,
    )[:10]

    top10 = []

    for article in overall:
        top10.append({
            "title": article["title"],
            "summary": article["summary"],
            "source": article["source"],
            "link": article["link"],
            "published": article["published"],
            "image": article["image"],
            "section": article["section"],
        })

    # --------------------------------------------------------
    # STEP 7 — OUTPUT
    # --------------------------------------------------------

    output = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),

        "top10": top10,

        "sources": {
            "working": working_sources,
            "failed": failed_direct_sources,
        },

        "sections": result,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print("NEWS DATABASE CREATED")
    print("=" * 70)

    print(
        "Total collected:",
        len(all_articles),
    )

    print(
        "Working direct sources:",
        len(working_sources),
    )

    print("")

    for source in working_sources:
        print(" ✓", source)

    print("")
    print("CATEGORY RESULTS")
    print("")

    for section in SECTIONS:
        print(
            f"{section:16} : "
            f"{len(result[section])} articles"
        )

    print("")
    print(
        "Output:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
