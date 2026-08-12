#!/usr/bin/env python3

import json
import os
import re
import html
import hashlib
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests
import feedparser


# ============================================================
# CONFIG
# ============================================================

OUTPUT_FILE = "news.json"
TOP_N = 10
TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36 "
    "NepalNewsTop10/1.0"
)

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
# GOOGLE NEWS SEARCHES
# ============================================================

GOOGLE_QUERIES = {
    "weather": [
        "Nepal weather rainfall flood monsoon landslide storm",
        "Nepal rain flood landslide temperature weather",
        "Kathmandu weather rainfall Nepal",
    ],

    "national": [
        "Nepal latest news",
        "Nepal breaking news today",
        "Nepal news today",
    ],

    "politics": [
        "Nepal politics government parliament",
        "Nepal prime minister minister cabinet",
        "Nepal political parties election",
    ],

    "business": [
        "Nepal business economy finance",
        "Nepal NEPSE stock market banking",
        "Nepal trade investment remittance",
    ],

    "sports": [
        "Nepal cricket football sports",
        "Nepal cricket latest news",
        "Nepal football latest news",
    ],

    "technology": [
        "Nepal technology digital AI cyber",
        "Nepal technology startup internet",
        "Nepal artificial intelligence technology",
    ],

    "entertainment": [
        "Nepal entertainment movie music film",
        "Nepali movie cinema music",
        "Nepal singer actor entertainment",
    ],

    "world": [
        "world latest news",
        "India China international news",
        "global breaking news",
    ],

    "health": [
        "Nepal health hospital disease medical",
        "Nepal dengue health outbreak",
        "Nepal healthcare doctor medicine",
    ],

    "crime": [
        "Nepal crime police arrest",
        "Nepal murder fraud court investigation",
        "Nepal accident security crime",
    ],
}


# ============================================================
# DIRECT RSS FALLBACKS
# ============================================================

RSS_SOURCES = [
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
        "name": "Gorkhapatra Online",
        "url": "https://gorkhapatraonline.com/rss",
    },
]


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = {
    "weather": [
        "weather", "rain", "rainfall", "flood", "flooding",
        "monsoon", "landslide", "storm", "temperature",
        "snow", "thunderstorm", "lightning", "climate",
        "वर्षा", "बाढी", "मनसुन", "पहिरो", "मौसम",
        "तापक्रम",
    ],

    "politics": [
        "government", "minister", "parliament", "election",
        "political", "prime minister", "cabinet", "party",
        "president", "coalition",
        "सरकार", "मन्त्री", "संसद", "निर्वाचन", "राजनीति",
    ],

    "business": [
        "business", "economy", "bank", "market", "company",
        "trade", "finance", "investment", "stock", "nepse",
        "remittance", "industry", "tourism",
        "व्यापार", "अर्थतन्त्र", "बैंक", "लगानी",
    ],

    "sports": [
        "football", "cricket", "sports", "sport", "tournament",
        "player", "match", "league", "championship",
        "olympic", "athlete", "fifa", "icc",
        "क्रिकेट", "फुटबल", "खेल",
    ],

    "technology": [
        "technology", "tech", "digital", "artificial intelligence",
        " ai ", "software", "internet", "cyber", "computer",
        "app", "startup", "प्रविधि", "डिजिटल",
    ],

    "entertainment": [
        "movie", "film", "music", "actor", "actress",
        "entertainment", "concert", "singer", "cinema",
        "television", "celebrity",
        "चलचित्र", "संगीत", "मनोरञ्जन",
    ],

    "world": [
        "world", "international", "india", "china", "america",
        "iran", "israel", "usa", "ukraine", "russia",
        "pakistan", "united states", "अन्तर्राष्ट्रिय",
        "भारत", "चीन",
    ],

    "crime": [
        "crime", "police", "arrest", "murder", "fraud",
        "accident", "security", "court", "criminal",
        "investigation", "robbery", "abuse",
        "प्रहरी", "गिरफ्तार", "हत्या", "अपराध",
    ],

    "health": [
        "health", "hospital", "doctor", "disease", "medical",
        "medicine", "patient", "healthcare", "virus",
        "outbreak", "dengue", "स्वास्थ्य", "अस्पताल",
        "डाक्टर", "रोग",
    ],
}


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": (
        "application/rss+xml, application/xml, text/xml, "
        "text/html;q=0.9, */*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
})


# ============================================================
# TEXT
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = html.unescape(str(value))

    value = re.sub(
        r"<script.*?</script>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<style.*?</style>",
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
    title = clean_text(title).lower()

    title = re.sub(
        r"[^a-z0-9\u0900-\u097f ]",
        " ",
        title,
    )

    return re.sub(r"\s+", " ", title).strip()


def make_id(title, link):
    raw = (
        normalize_title(title)
        + "|"
        + link.strip().lower()
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


# ============================================================
# SUMMARY
# ============================================================

def make_summary(title, description):
    title = clean_text(title)
    description = clean_text(description)

    text = description or title

    if not text:
        return "Latest news update."

    text = re.sub(
        r"^(read more|continue reading)\s*:?\s*",
        "",
        text,
        flags=re.I,
    )

    sentences = re.split(
        r"(?<=[.!?।])\s+",
        text,
    )

    result = sentences[0].strip()

    if not result:
        result = title

    if len(result) > 260:
        result = (
            result[:257]
            .rsplit(" ", 1)[0]
            + "..."
        )

    if not result.endswith(
        (".", "!", "?", "।")
    ):
        result += "."

    return result


# ============================================================
# CATEGORY
# ============================================================

def classify(title, description):
    text = (
        clean_text(title)
        + " "
        + clean_text(description)
    ).lower()

    scores = {
        section: 0
        for section in SECTIONS
    }

    for section, words in KEYWORDS.items():

        for word in words:

            if word.lower() in text:
                scores[section] += 1

    # Weather gets priority when strongly matched.
    if scores["weather"] >= 2:
        return "weather"

    best = max(
        scores,
        key=scores.get,
    )

    if scores[best] == 0:
        return "national"

    return best


# ============================================================
# RANKING
# ============================================================

def rank_score(article):
    title = article["title"].lower()

    score = 0

    important = [
        "breaking",
        "latest",
        "major",
        "government",
        "prime minister",
        "president",
        "minister",
        "election",
        "parliament",
        "decision",
        "crisis",
        "agreement",
        "earthquake",
        "flood",
        "landslide",
        "storm",
        "victory",
        "death",
    ]

    for word in important:
        if word in title:
            score += 3

    if article.get("published"):
        score += 1

    if article.get("source") != "Google News":
        score += 2

    return score


# ============================================================
# GOOGLE NEWS
# ============================================================

def google_url(query):
    return (
        "https://news.google.com/rss/search?"
        "q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )


def fetch_google(query):
    url = google_url(query)

    response = session.get(
        url,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    feed = feedparser.parse(
        response.content
    )

    if not feed.entries:
        return []

    results = []

    for entry in feed.entries[:40]:

        title = clean_text(
            entry.get("title", "")
        )

        description = clean_text(
            entry.get(
                "summary",
                entry.get(
                    "description",
                    "",
                ),
            )
        )

        link = clean_text(
            entry.get("link", "")
        )

        published = clean_text(
            entry.get(
                "published",
                entry.get(
                    "updated",
                    "",
                ),
            )
        )

        if not title or not link:
            continue

        source = "Google News"

        try:
            source_data = entry.get(
                "source",
                None,
            )

            if source_data:

                source_name = clean_text(
                    source_data.get(
                        "title",
                        "",
                    )
                )

                if source_name:
                    source = source_name

        except Exception:
            pass

        results.append({
            "title": title,
            "summary": description,
            "source": source,
            "link": link,
            "published": published,
        })

    return results


# ============================================================
# DIRECT RSS
# ============================================================

def fetch_rss(source):
    response = session.get(
        source["url"],
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    feed = feedparser.parse(
        response.content
    )

    if not feed.entries:
        return []

    results = []

    for entry in feed.entries[:50]:

        title = clean_text(
            entry.get("title", "")
        )

        description = clean_text(
            entry.get(
                "summary",
                entry.get(
                    "description",
                    "",
                ),
            )
        )

        link = clean_text(
            entry.get("link", "")
        )

        published = clean_text(
            entry.get(
                "published",
                entry.get(
                    "updated",
                    "",
                ),
            )
        )

        if not title or not link:
            continue

        results.append({
            "title": title,
            "summary": description,
            "source": source["name"],
            "link": link,
            "published": published,
        })

    return results


# ============================================================
# NORMALIZE
# ============================================================

def normalize_article(raw, section):
    title = clean_text(
        raw.get("title", "")
    )

    description = clean_text(
        raw.get("summary", "")
    )

    link = clean_text(
        raw.get("link", "")
    )

    source = clean_text(
        raw.get(
            "source",
            "Unknown source",
        )
    )

    published = clean_text(
        raw.get(
            "published",
            "",
        )
    )

    if not title or not link:
        return None

    return {
        "id": make_id(
            title,
            link,
        ),

        "title": title,

        "summary": make_summary(
            title,
            description,
        ),

        "source": source,

        "link": link,

        "published": published,

        "section": section,
    }


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate(articles):
    result = []

    seen_ids = set()
    seen_titles = set()
    seen_links = set()

    for article in articles:

        article_id = article["id"]

        title_key = normalize_title(
            article["title"]
        )

        link = article["link"].strip()

        if article_id in seen_ids:
            continue

        if title_key in seen_titles:
            continue

        if link in seen_links:
            continue

        seen_ids.add(article_id)
        seen_titles.add(title_key)
        seen_links.add(link)

        result.append(article)

    return result


# ============================================================
# LOAD OLD DATABASE
# ============================================================

def load_existing():
    if not os.path.exists(OUTPUT_FILE):
        return None

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        return data

    except Exception as error:

        print(
            "Could not read existing news.json:",
            error,
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NEPAL NEWS TOP 10 SCRAPER")
    print("=" * 70)

    print(
        "Started:",
        datetime.now(
            timezone.utc
        ).isoformat(),
    )

    print()

    all_articles = []

    diagnostics = {
        "google_news": {},
        "rss": {},
    }


    # --------------------------------------------------------
    # GOOGLE NEWS
    # --------------------------------------------------------

    print("=" * 70)
    print("GOOGLE NEWS DISCOVERY")
    print("=" * 70)

    for section in SECTIONS:

        queries = GOOGLE_QUERIES.get(
            section,
            [],
        )

        section_articles = []

        print()
        print(
            f"[{section.upper()}]"
        )

        for query in queries:

            print(
                "Searching:",
                query,
            )

            try:

                found = fetch_google(
                    query
                )

                print(
                    "  Found:",
                    len(found),
                )

                section_articles.extend(
                    found
                )

                time.sleep(0.4)

            except Exception as error:

                print(
                    "  FAILED:",
                    error,
                )

        section_articles = deduplicate(
            [
                normalize_article(
                    article,
                    section,
                )
                for article in section_articles
                if normalize_article(
                    article,
                    section,
                )
            ]
        )

        diagnostics["google_news"][
            section
        ] = len(section_articles)

        print(
            f"  Total {section}:",
            len(section_articles),
        )

        all_articles.extend(
            section_articles
        )


    # --------------------------------------------------------
    # DIRECT RSS FALLBACK
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("DIRECT RSS FALLBACK")
    print("=" * 70)

    for source in RSS_SOURCES:

        print()
        print(
            "Testing:",
            source["name"],
        )

        try:

            found = fetch_rss(
                source
            )

            print(
                "  SUCCESS:",
                len(found),
                "articles",
            )

            diagnostics["rss"][
                source["name"]
            ] = {
                "status": "working",
                "articles": len(found),
            }

            for raw in found:

                section = classify(
                    raw["title"],
                    raw["summary"],
                )

                article = normalize_article(
                    raw,
                    section,
                )

                if article:
                    all_articles.append(
                        article
                    )

        except Exception as error:

            print(
                "  FAILED:",
                error,
            )

            diagnostics["rss"][
                source["name"]
            ] = {
                "status": "failed",
                "error": str(error),
            }


    # --------------------------------------------------------
    # DEDUPLICATE
    # --------------------------------------------------------

    all_articles = deduplicate(
        all_articles
    )

    print()
    print(
        "Unique articles:",
        len(all_articles),
    )


    # --------------------------------------------------------
    # RECLASSIFY
    # --------------------------------------------------------

    for article in all_articles:

        article["section"] = classify(
            article["title"],
            article["summary"],
        )


    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    all_articles.sort(
        key=rank_score,
        reverse=True,
    )


    # --------------------------------------------------------
    # BUILD SECTIONS
    # --------------------------------------------------------

    sections = {
        section: []
        for section in SECTIONS
    }

    for article in all_articles:

        section = article["section"]

        if section not in sections:
            section = "national"

        if len(
            sections[section]
        ) >= TOP_N:
            continue

        sections[section].append({
            "title": article["title"],
            "summary": article["summary"],
            "source": article["source"],
            "link": article["link"],
            "published": article["published"],
        })


    # --------------------------------------------------------
    # DIAGNOSTICS
    # --------------------------------------------------------

    counts = {
        section: len(
            sections[section]
        )
        for section in SECTIONS
    }

    total = sum(
        counts.values()
    )

    print()
    print("=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)

    for section in SECTIONS:

        print(
            f"{section:15} : "
            f"{counts[section]}"
        )

    print()
    print(
        "TOTAL STORIES:",
        total,
    )


    # --------------------------------------------------------
    # SAFETY CHECK
    #
    # Never destroy a good database because all
    # external sources temporarily failed.
    # --------------------------------------------------------

    existing = load_existing()

    existing_total = 0

    if existing:

        existing_sections = existing.get(
            "sections",
            {},
        )

        if isinstance(
            existing_sections,
            dict,
        ):

            existing_total = sum(
                len(
                    existing_sections.get(
                        section,
                        [],
                    )
                )
                for section in SECTIONS
                if isinstance(
                    existing_sections.get(
                        section,
                        [],
                    ),
                    list,
                )
            )

    print(
        "Existing stories:",
        existing_total,
    )


    if total == 0:

        print()
        print(
            "ERROR: No articles were retrieved."
        )

        if existing_total > 0:

            print(
                "Keeping existing news.json."
            )

            return 0

        print(
            "No existing database is available."
        )

        return 1


    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    output = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),

        "generated_by": "Nepal News Top 10 scraper",

        "article_count": total,

        "sources": diagnostics,

        "sections": sections,
    }


    temporary_file = (
        OUTPUT_FILE
        + ".tmp"
    )

    with open(
        temporary_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

        f.write("\n")


    # Atomic replacement.
    os.replace(
        temporary_file,
        OUTPUT_FILE,
    )


    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    with open(
        OUTPUT_FILE,
        "r",
        encoding="utf-8",
    ) as f:

        check = json.load(f)


    if not check.get("updated"):
        raise RuntimeError(
            "Generated news.json has no timestamp."
        )

    if not isinstance(
        check.get("sections"),
        dict,
    ):
        raise RuntimeError(
            "Generated news.json has invalid sections."
        )


    print()
    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)

    print(
        "Created:",
        OUTPUT_FILE,
    )

    print(
        "Stories:",
        total,
    )

    print(
        "Updated:",
        output["updated"],
    )

    print()
    print(
        "news.json is ready for GitHub Pages."
    )

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
