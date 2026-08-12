#!/usr/bin/env python3

"""
Nepal News Top 10 - Production News Scraper

Pipeline:
    Google News discovery
        ↓
    RSS feeds
        ↓
    Direct publisher pages
        ↓
    Deduplicate
        ↓
    Categorize
        ↓
    Rank
        ↓
    Top 10 per category
        ↓
    news.json

Important:
- Does NOT require a News API key.
- Does NOT put images inside summaries.
- Does NOT overwrite a valid news.json with an empty database.
- Failed sources are recorded in diagnostics.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import feedparser


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "news.json"
BACKUP_FILE = ROOT / "news.previous.json"

MAX_PER_CATEGORY = 10

# We collect more than 10 before ranking so that poor matches
# do not dominate a category.
COLLECT_PER_QUERY = 30

REQUEST_TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36 "
    "NepalNewsTop10/2.0"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "application/rss+xml;q=0.9,"
        "application/atom+xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Minimum number of usable articles required before replacing
# an existing valid database.
MIN_TOTAL_ARTICLES_TO_REPLACE = 10

# ============================================================
# CATEGORIES
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

KEYWORDS = {
    "weather": [
        "weather",
        "rain",
        "rainfall",
        "flood",
        "flooding",
        "storm",
        "thunderstorm",
        "temperature",
        "monsoon",
        "landslide",
        "landslides",
        "snow",
        "hail",
        "wind",
        "lightning",
        "climate",
        "forecast",
        "heatwave",
        "heat wave",
        "cold wave",
        "disaster",
    ],

    "national": [
        "nepal",
        "kathmandu",
        "pokhara",
        "lalitpur",
        "bhaktapur",
        "province",
        "district",
        "municipality",
        "local level",
        "federal",
        "national",
        "government",
        "ministry",
    ],

    "politics": [
        "politics",
        "political",
        "government",
        "minister",
        "ministry",
        "prime minister",
        "president",
        "parliament",
        "lawmakers",
        "mp",
        "election",
        "vote",
        "coalition",
        "party",
        "cabinet",
        "congress",
        "uml",
        "maoist",
        "opposition",
        "ordinance",
    ],

    "business": [
        "business",
        "economy",
        "economic",
        "bank",
        "banking",
        "finance",
        "financial",
        "market",
        "nepse",
        "stock",
        "share",
        "company",
        "trade",
        "investment",
        "investor",
        "remittance",
        "tourism",
        "industry",
        "manufacturing",
        "startup",
        "revenue",
        "budget",
        "inflation",
    ],

    "sports": [
        "sport",
        "sports",
        "football",
        "soccer",
        "cricket",
        "icc",
        "fifa",
        "tournament",
        "match",
        "player",
        "league",
        "championship",
        "athlete",
        "olympic",
        "world cup",
        "premier league",
        "goal",
        "wicket",
        "runs",
    ],

    "technology": [
        "technology",
        "technology",
        "tech",
        "digital",
        "artificial intelligence",
        "ai",
        "software",
        "hardware",
        "internet",
        "cyber",
        "cybersecurity",
        "computer",
        "smartphone",
        "mobile",
        "app",
        "application",
        "startup",
        "data",
        "robot",
        "robotics",
        "space",
        "satellite",
    ],

    "entertainment": [
        "entertainment",
        "movie",
        "film",
        "cinema",
        "actor",
        "actress",
        "singer",
        "music",
        "song",
        "concert",
        "celebrity",
        "television",
        "tv",
        "series",
        "director",
        "festival",
        "award",
        "bollywood",
        "hollywood",
    ],

    "world": [
        "world",
        "international",
        "global",
        "india",
        "china",
        "united states",
        "usa",
        "america",
        "pakistan",
        "bangladesh",
        "iran",
        "israel",
        "palestine",
        "ukraine",
        "russia",
        "europe",
        "asia",
        "britain",
        "uk",
        "united kingdom",
        "foreign",
    ],

    "health": [
        "health",
        "hospital",
        "doctor",
        "medical",
        "medicine",
        "disease",
        "patient",
        "healthcare",
        "virus",
        "outbreak",
        "dengue",
        "covid",
        "cancer",
        "infection",
        "vaccine",
        "vaccination",
        "epidemic",
        "mental health",
        "public health",
    ],

    "crime": [
        "crime",
        "criminal",
        "police",
        "arrest",
        "arrested",
        "murder",
        "killing",
        "death",
        "fraud",
        "robbery",
        "theft",
        "rape",
        "abuse",
        "investigation",
        "court",
        "lawsuit",
        "jail",
        "prison",
        "smuggling",
        "corruption",
        "accident",
    ],
}


# ============================================================
# GOOGLE NEWS SEARCH QUERIES
# ============================================================

GOOGLE_QUERIES = {
    "weather": [
        "Nepal weather rainfall flood monsoon landslide storm",
        "Nepal rainfall floods landslides temperature",
        "Nepal monsoon weather",
    ],

    "national": [
        "Nepal latest news",
        "Nepal national news",
        "Kathmandu Nepal latest",
    ],

    "politics": [
        "Nepal politics government parliament",
        "Nepal prime minister parliament election",
        "Nepal political news",
    ],

    "business": [
        "Nepal business economy finance",
        "Nepal NEPSE market banking",
        "Nepal investment trade remittance",
    ],

    "sports": [
        "Nepal sports cricket football",
        "Nepal cricket latest",
        "Nepal football latest",
    ],

    "technology": [
        "Nepal technology digital AI",
        "Nepal tech cybersecurity",
        "Nepal startup technology",
    ],

    "entertainment": [
        "Nepal entertainment movie music",
        "Nepali film music celebrity",
        "Nepal cinema entertainment",
    ],

    "world": [
        "Nepal world international news",
        "India China world latest news",
        "Asia international latest",
    ],

    "health": [
        "Nepal health hospital disease",
        "Nepal health medical latest",
        "Nepal dengue health",
    ],

    "crime": [
        "Nepal crime police arrest",
        "Nepal crime investigation court",
        "Nepal accident police",
    ],
}


# ============================================================
# DIRECT PUBLISHER PAGES
# ============================================================

PUBLISHERS = [
    {
        "name": "The Kathmandu Post",
        "homepage": "https://kathmandupost.com/",
        "sections": [
            "https://kathmandupost.com/national",
            "https://kathmandupost.com/politics",
            "https://kathmandupost.com/money",
            "https://kathmandupost.com/sports",
            "https://kathmandupost.com/technology",
            "https://kathmandupost.com/art-culture",
        ],
    },
    {
        "name": "OnlineKhabar",
        "homepage": "https://www.onlinekhabar.com/",
        "sections": [
            "https://www.onlinekhabar.com/content/news",
            "https://www.onlinekhabar.com/content/politics",
            "https://www.onlinekhabar.com/content/business",
            "https://www.onlinekhabar.com/content/sports",
            "https://www.onlinekhabar.com/content/technology",
            "https://www.onlinekhabar.com/content/entertainment",
        ],
    },
    {
        "name": "Setopati",
        "homepage": "https://www.setopati.com/",
        "sections": [
            "https://www.setopati.com/politics",
            "https://www.setopati.com/business",
            "https://www.setopati.com/sports",
            "https://www.setopati.com/art",
        ],
    },
    {
        "name": "Ratopati",
        "homepage": "https://www.ratopati.com/",
        "sections": [
            "https://www.ratopati.com/category/politics",
            "https://www.ratopati.com/category/business",
            "https://www.ratopati.com/category/sports",
            "https://www.ratopati.com/category/technology",
            "https://www.ratopati.com/category/entertainment",
        ],
    },
    {
        "name": "The Himalayan Times",
        "homepage": "https://thehimalayantimes.com/",
        "sections": [
            "https://thehimalayantimes.com/nepal",
            "https://thehimalayantimes.com/business",
            "https://thehimalayantimes.com/sports",
            "https://thehimalayantimes.com/technology",
            "https://thehimalayantimes.com/entertainment",
        ],
    },
]


# ============================================================
# RSS FALLBACKS
# ============================================================

RSS_FEEDS = [
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
        "url": "https://www.ratopati.com/rss",
    },
    {
        "name": "The Himalayan Times",
        "url": "https://thehimalayantimes.com/rssFeed",
    },
    {
        "name": "Nepali Times",
        "url": "https://www.nepalitimes.com/feed/",
    },
]


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("nepal-news-scraper")


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value: object) -> str:
    """Convert HTML/text into clean readable text."""

    if value is None:
        return ""

    text = html.unescape(str(value))

    soup = BeautifulSoup(text, "html.parser")

    text = soup.get_text(" ", strip=True)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_title(title: str) -> str:
    """Normalize titles for duplicate detection."""

    text = clean_text(title).lower()

    text = re.sub(r"[^\w\s]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def article_hash(title: str, link: str) -> str:
    value = (
        normalize_title(title)
        + "|"
        + normalize_url(link)
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def normalize_url(url: str) -> str:
    """Remove tracking parameters from URLs."""

    if not url:
        return ""

    url = url.strip()

    try:
        parsed = urlparse(url)

        # Remove common tracking query strings.
        clean_query = []

        for part in parsed.query.split("&"):
            if not part:
                continue

            key = part.split("=")[0].lower()

            if key.startswith("utm_"):
                continue

            if key in {
                "fbclid",
                "gclid",
                "mc_cid",
                "mc_eid",
            }:
                continue

            clean_query.append(part)

        query = "&".join(clean_query)

        return parsed._replace(
            query=query,
            fragment="",
        ).geturl()

    except Exception:
        return url


def truncate_sentence(text: str, maximum: int = 280) -> str:
    text = clean_text(text)

    if not text:
        return ""

    # Remove common boilerplate.
    text = re.sub(
        r"^(read more|click here|advertisement)\s*:?\s*",
        "",
        text,
        flags=re.I,
    )

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    sentence = sentences[0].strip()

    if len(sentence) > maximum:
        sentence = (
            sentence[: maximum - 3]
            .rsplit(" ", 1)[0]
            + "..."
        )

    if sentence and not sentence.endswith(
        (".", "!", "?")
    ):
        sentence += "."

    return sentence


def one_sentence(title: str, summary: str) -> str:
    """
    Produce a concise one-sentence summary.

    We intentionally avoid external AI APIs so the scraper
    works without an API key.
    """

    summary = clean_text(summary)

    if summary:
        sentence = truncate_sentence(summary)

        if sentence:
            return sentence

    # Safe fallback using the headline.
    title = clean_text(title)

    if title:
        if title.endswith((".", "!", "?")):
            return title

        return title + "."

    return "Latest news update."


# ============================================================
# DATE HELPERS
# ============================================================

def parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None

    value = clean_text(value)

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # ISO-like fallback.
    try:
        normalized = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(normalized)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def iso_date(value: str) -> str:
    dt = parse_date(value)

    if not dt:
        return clean_text(value)

    return dt.isoformat()


# ============================================================
# CATEGORY CLASSIFICATION
# ============================================================

def keyword_score(
    text: str,
    words: List[str],
) -> int:

    text = text.lower()

    score = 0

    for word in words:
        word = word.lower().strip()

        if not word:
            continue

        if word in text:
            score += 1

    return score


def classify_article(
    title: str,
    summary: str,
    preferred: Optional[str] = None,
) -> str:

    text = (
        clean_text(title)
        + " "
        + clean_text(summary)
    ).lower()

    scores = {}

    for section in SECTIONS:
        scores[section] = keyword_score(
            text,
            KEYWORDS.get(section, []),
        )

    # If Google News search was specifically for a category,
    # give that category a small bonus.
    if preferred in scores:
        scores[preferred] += 2

    # Weather receives special treatment because it should
    # contain actual weather/disaster stories rather than
    # a generic Kathmandu weather forecast.
    if preferred == "weather":
        weather_terms = KEYWORDS["weather"]

        if not any(
            word in text
            for word in weather_terms
        ):
            scores["weather"] = 0

    best = max(
        scores,
        key=scores.get,
    )

    if scores[best] <= 0:
        return "national"

    return best


# ============================================================
# IMPORTANCE / RANKING
# ============================================================

IMPORTANT_TERMS = [
    "breaking",
    "latest",
    "urgent",
    "major",
    "government",
    "prime minister",
    "president",
    "election",
    "parliament",
    "death",
    "killed",
    "flood",
    "landslide",
    "earthquake",
    "storm",
    "crisis",
    "decision",
    "agreement",
    "war",
    "victory",
]


def importance(article: Dict) -> float:

    title = article.get(
        "title",
        "",
    ).lower()

    summary = article.get(
        "summary",
        "",
    ).lower()

    score = 0.0

    for term in IMPORTANT_TERMS:
        if term in title:
            score += 3.0

        elif term in summary:
            score += 1.0

    published = parse_date(
        article.get(
            "published",
            "",
        )
    )

    if published:

        age_hours = max(
            0,
            (
                datetime.now(
                    timezone.utc
                )
                - published
            ).total_seconds()
            / 3600,
        )

        # Freshness bonus.
        score += max(
            0,
            8 - min(age_hours / 3, 8),
        )

    # Publisher bonus.
    source = article.get(
        "source",
        "",
    ).lower()

    trusted = [
        "kathmandu post",
        "onlinekhabar",
        "setopati",
        "ratopati",
        "himalayan times",
        "nepali times",
    ]

    if source in trusted:
        score += 1.5

    return score


# ============================================================
# ARTICLE CREATION
# ============================================================

def make_article(
    title: str,
    summary: str,
    link: str,
    source: str,
    published: str = "",
    preferred_section: Optional[str] = None,
) -> Optional[Dict]:

    title = clean_text(title)
    summary = clean_text(summary)
    link = normalize_url(link)
    source = clean_text(source)
    published = iso_date(published)

    if not title or not link:
        return None

    # Reject obvious non-news links.
    if len(title) < 8:
        return None

    if not (
        link.startswith("http://")
        or link.startswith("https://")
    ):
        return None

    section = classify_article(
        title,
        summary,
        preferred_section,
    )

    return {
        "id": article_hash(
            title,
            link,
        ),
        "title": title,
        "summary": one_sentence(
            title,
            summary,
        ),
        "source": source or "Unknown source",
        "link": link,
        "published": published,
        "section": section,
    }


# ============================================================
# GOOGLE NEWS
# ============================================================

def google_news_url(query: str) -> str:
    encoded = quote_plus(query)

    return (
        "https://news.google.com/rss/search?"
        f"q={encoded}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )


def fetch_google_news(
    section: str,
    diagnostics: Dict,
) -> List[Dict]:

    articles = []

    queries = GOOGLE_QUERIES.get(
        section,
        [],
    )

    for query in queries:

        url = google_news_url(query)

        logger.info(
            "Google News | %s | %s",
            section,
            query,
        )

        try:

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            feed = feedparser.parse(
                response.content
            )

            if not feed.entries:
                diagnostics["google_news"]["failed"] += 1
                continue

            diagnostics["google_news"]["successful"] += 1

            for item in feed.entries[
                :COLLECT_PER_QUERY
            ]:

                title = item.get(
                    "title",
                    "",
                )

                summary = item.get(
                    "summary",
                    item.get(
                        "description",
                        "",
                    ),
                )

                link = item.get(
                    "link",
                    "",
                )

                published = item.get(
                    "published",
                    item.get(
                        "updated",
                        "",
                    ),
                )

                article = make_article(
                    title=title,
                    summary=summary,
                    link=link,
                    source=(
                        item.get(
                            "source",
                            {}
                        ).get(
                            "title",
                            "Google News",
                        )
                        if isinstance(
                            item.get(
                                "source",
                                {}
                            ),
                            dict,
                        )
                        else "Google News"
                    ),
                    published=published,
                    preferred_section=section,
                )

                if article:
                    articles.append(article)

        except Exception as error:

            diagnostics["google_news"]["failed"] += 1

            logger.warning(
                "Google News failed: %s",
                error,
            )

        # Avoid hammering the endpoint.
        time.sleep(0.3)

    return articles


# ============================================================
# RSS
# ============================================================

def fetch_rss(
    diagnostics: Dict,
) -> List[Dict]:

    articles = []

    for source in RSS_FEEDS:

        logger.info(
            "RSS | %s",
            source["name"],
        )

        try:

            response = session.get(
                source["url"],
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            feed = feedparser.parse(
                response.content
            )

            if not feed.entries:

                diagnostics["rss"]["failed"] += 1

                logger.warning(
                    "RSS returned no entries: %s",
                    source["name"],
                )

                continue

            diagnostics["rss"]["successful"] += 1

            for item in feed.entries[:60]:

                title = item.get(
                    "title",
                    "",
                )

                summary = item.get(
                    "summary",
                    item.get(
                        "description",
                        "",
                    ),
                )

                link = item.get(
                    "link",
                    "",
                )

                published = item.get(
                    "published",
                    item.get(
                        "updated",
                        "",
                    ),
                )

                article = make_article(
                    title=title,
                    summary=summary,
                    link=link,
                    source=source["name"],
                    published=published,
                )

                if article:
                    articles.append(article)

        except Exception as error:

            diagnostics["rss"]["failed"] += 1

            logger.warning(
                "RSS failed: %s | %s",
                source["name"],
                error,
            )

    return articles


# ============================================================
# DIRECT WEBSITE SCRAPER
# ============================================================

def looks_like_article_url(url: str) -> bool:

    parsed = urlparse(url)

    path = parsed.path.lower()

    if not path:
        return False

    blocked = [
        "/tag/",
        "/tags/",
        "/category/",
        "/author/",
        "/search",
        "/login",
        "/subscribe",
        "/contact",
        "/about",
        "/privacy",
        "/terms",
        "/video",
        "/photos",
        "/gallery",
    ]

    if any(
        value in path
        for value in blocked
    ):
        return False

    return True


def extract_links_from_page(
    page_url: str,
    source_name: str,
    preferred_section: Optional[str],
    diagnostics: Dict,
) -> List[Dict]:

    articles = []

    try:

        response = session.get(
            page_url,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # First preference: article elements.
        candidates = soup.select(
            "article a[href], "
            "h1 a[href], "
            "h2 a[href], "
            "h3 a[href], "
            "h4 a[href]"
        )

        seen = set()

        for anchor in candidates:

            href = anchor.get(
                "href",
                "",
            ).strip()

            title = clean_text(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            )

            if not href or not title:
                continue

            href = normalize_url(
                urljoin(
                    page_url,
                    href,
                )
            )

            if href in seen:
                continue

            seen.add(href)

            if not looks_like_article_url(
                href
            ):
                continue

            # Headlines are generally short but not tiny.
            if len(title) < 20:
                continue

            if len(title) > 300:
                continue

            article = make_article(
                title=title,
                summary="",
                link=href,
                source=source_name,
                preferred_section=preferred_section,
            )

            if article:
                articles.append(article)

            if len(articles) >= 40:
                break

        diagnostics["direct"]["successful"] += 1

    except Exception as error:

        diagnostics["direct"]["failed"] += 1

        logger.warning(
            "Direct page failed: %s | %s",
            page_url,
            error,
        )

    return articles


def enrich_article(
    article: Dict,
) -> Dict:
    """
    Visit an article page and try to obtain:
    - description
    - publication date
    - better source name

    Failure is non-fatal.
    """

    try:

        response = session.get(
            article["link"],
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # Description metadata.
        description = ""

        meta_candidates = [
            ("meta", {"name": "description"}),
            (
                "meta",
                {
                    "property":
                    "og:description"
                },
            ),
            (
                "meta",
                {
                    "name":
                    "twitter:description"
                },
            ),
        ]

        for tag_name, attrs in meta_candidates:

            tag = soup.find(
                tag_name,
                attrs=attrs,
            )

            if tag and tag.get("content"):

                description = clean_text(
                    tag.get("content")
                )

                if description:
                    break

        if description:

            article["summary"] = one_sentence(
                article["title"],
                description,
            )

        # Publication date.
        date_value = ""

        date_selectors = [
            (
                "meta",
                {"property": "article:published_time"},
            ),
            (
                "meta",
                {"name": "article:published_time"},
            ),
            (
                "meta",
                {"name": "pubdate"},
            ),
            (
                "meta",
                {"name": "publishdate"},
            ),
        ]

        for tag_name, attrs in date_selectors:

            tag = soup.find(
                tag_name,
                attrs=attrs,
            )

            if tag and tag.get("content"):

                date_value = clean_text(
                    tag.get("content")
                )

                if date_value:
                    break

        if date_value:

            article["published"] = iso_date(
                date_value
            )

    except Exception as error:

        logger.debug(
            "Article enrichment failed: %s | %s",
            article.get("link"),
            error,
        )

    return article


def fetch_direct_publishers(
    diagnostics: Dict,
) -> List[Dict]:

    articles = []

    for publisher in PUBLISHERS:

        pages = publisher.get(
            "sections",
            [],
        )

        for page_url in pages:

            # Determine likely category from URL.
            preferred = None

            lower_url = page_url.lower()

            for section in SECTIONS:

                if section in lower_url:
                    preferred = section
                    break

            found = extract_links_from_page(
                page_url=page_url,
                source_name=publisher["name"],
                preferred_section=preferred,
                diagnostics=diagnostics,
            )

            articles.extend(found)

            time.sleep(0.4)

    return articles


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate(
    articles: List[Dict],
) -> List[Dict]:

    unique = []

    seen_ids = set()
    seen_titles = set()
    seen_urls = set()

    for article in articles:

        article_id = article.get(
            "id",
            "",
        )

        title_key = normalize_title(
            article.get(
                "title",
                "",
            )
        )

        url_key = normalize_url(
            article.get(
                "link",
                "",
            )
        )

        if article_id in seen_ids:
            continue

        if title_key in seen_titles:
            continue

        if url_key in seen_urls:
            continue

        seen_ids.add(article_id)
        seen_titles.add(title_key)
        seen_urls.add(url_key)

        unique.append(article)

    return unique


# ============================================================
# RECLASSIFY
# ============================================================

def reclassify_articles(
    articles: List[Dict],
) -> None:

    for article in articles:

        article["section"] = classify_article(
            article.get("title", ""),
            article.get("summary", ""),
            article.get("section"),
        )


# ============================================================
# BUILD DATABASE
# ============================================================

def build_database(
    articles: List[Dict],
) -> Dict:

    result = {
        section: []
        for section in SECTIONS
    }

    # Group.
    groups = {
        section: []
        for section in SECTIONS
    }

    for article in articles:

        section = article.get(
            "section",
            "national",
        )

        if section not in groups:
            section = "national"

        groups[section].append(article)

    # Rank each category separately.
    for section in SECTIONS:

        candidates = groups[section]

        candidates.sort(
            key=importance,
            reverse=True,
        )

        selected = candidates[
            :MAX_PER_CATEGORY
        ]

        result[section] = [
            {
                "title": article["title"],
                "summary": article["summary"],
                "source": article["source"],
                "link": article["link"],
                "published": article["published"],
            }
            for article in selected
        ]

    return result


# ============================================================
# VALID DATABASE CHECK
# ============================================================

def count_articles(
    sections: Dict,
) -> int:

    return sum(
        len(
            value
        )
        for value in sections.values()
        if isinstance(value, list)
    )


def database_is_usable(
    database: Dict,
) -> bool:

    sections = database.get(
        "sections",
        {},
    )

    if not isinstance(sections, dict):
        return False

    total = count_articles(
        sections
    )

    return total >= MIN_TOTAL_ARTICLES_TO_REPLACE


def load_existing_database() -> Optional[Dict]:

    if not OUTPUT_FILE.exists():
        return None

    try:

        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if database_is_usable(data):
            return data

    except Exception as error:

        logger.warning(
            "Could not read existing news.json: %s",
            error,
        )

    return None


# ============================================================
# SAFE WRITE
# ============================================================

def write_database(
    database: Dict,
) -> None:

    temporary = OUTPUT_FILE.with_suffix(
        ".json.tmp"
    )

    with temporary.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            database,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write("\n")

    # Keep a backup of the previous valid file.
    if OUTPUT_FILE.exists():

        try:
            shutil.copy2(
                OUTPUT_FILE,
                BACKUP_FILE,
            )
        except Exception as error:

            logger.warning(
                "Could not create backup: %s",
                error,
            )

    # Atomic replacement.
    os.replace(
        temporary,
        OUTPUT_FILE,
    )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    started = datetime.now(
        timezone.utc
    )

    logger.info(
        "=" * 70
    )

    logger.info(
        "Nepal News Top 10 scraper starting"
    )

    logger.info(
        "=" * 70
    )

    diagnostics = {
        "google_news": {
            "successful": 0,
            "failed": 0,
        },
        "rss": {
            "successful": 0,
            "failed": 0,
        },
        "direct": {
            "successful": 0,
            "failed": 0,
        },
    }

    all_articles = []

    # --------------------------------------------------------
    # 1. GOOGLE NEWS
    # --------------------------------------------------------

    logger.info(
        "STEP 1: Google News discovery"
    )

    for section in SECTIONS:

        found = fetch_google_news(
            section,
            diagnostics,
        )

        logger.info(
            "Google News %s: %d articles",
            section,
            len(found),
        )

        all_articles.extend(found)

    logger.info(
        "Google News total: %d",
        len(all_articles),
    )

    # --------------------------------------------------------
    # 2. RSS
    # --------------------------------------------------------

    logger.info(
        "STEP 2: RSS fallback"
    )

    rss_articles = fetch_rss(
        diagnostics
    )

    logger.info(
        "RSS total: %d",
        len(rss_articles),
    )

    all_articles.extend(
        rss_articles
    )

    # --------------------------------------------------------
    # 3. DIRECT WEBSITES
    # --------------------------------------------------------

    logger.info(
        "STEP 3: Direct publisher fallback"
    )

    direct_articles = (
        fetch_direct_publishers(
            diagnostics
        )
    )

    logger.info(
        "Direct scraping total: %d",
        len(direct_articles),
    )

    all_articles.extend(
        direct_articles
    )

    # --------------------------------------------------------
    # 4. DEDUPLICATE
    # --------------------------------------------------------

    logger.info(
        "STEP 4: Deduplicating"
    )

    before = len(all_articles)

    all_articles = deduplicate(
        all_articles
    )

    logger.info(
        "Removed %d duplicates",
        before - len(all_articles),
    )

    logger.info(
        "Unique articles: %d",
        len(all_articles),
    )

    # --------------------------------------------------------
    # 5. ENRICH SOME ARTICLES
    # --------------------------------------------------------

    # Only enrich a reasonable number so GitHub Actions does
    # not make hundreds of requests every run.
    logger.info(
        "STEP 5: Enriching article summaries"
    )

    for index, article in enumerate(
        all_articles[:150]
    ):

        enrich_article(
            article
        )

        if index % 20 == 0:
            logger.info(
                "Enriched %d/150",
                index + 1,
            )

        time.sleep(0.15)

    # --------------------------------------------------------
    # 6. RECLASSIFY
    # --------------------------------------------------------

    logger.info(
        "STEP 6: Classifying articles"
    )

    reclassify_articles(
        all_articles
    )

    # --------------------------------------------------------
    # 7. BUILD TOP 10
    # --------------------------------------------------------

    logger.info(
        "STEP 7: Building category rankings"
    )

    sections = build_database(
        all_articles
    )

    total = count_articles(
        sections
    )

    # --------------------------------------------------------
    # 8. SAFE DATABASE UPDATE
    # --------------------------------------------------------

    finished = datetime.now(
        timezone.utc
    )

    database = {
        "updated": finished.isoformat(),

        "generator": {
            "name": "Nepal News Top 10 Scraper",
            "version": "2.0",
        },

        "diagnostics": {
            "articles_discovered":
                len(all_articles),

            "articles_published":
                total,

            "sources": diagnostics,

            "started":
                started.isoformat(),

            "finished":
                finished.isoformat(),
        },

        "sections": sections,
    }

    existing = load_existing_database()

    if total < MIN_TOTAL_ARTICLES_TO_REPLACE:

        logger.error(
            "Only %d usable articles found.",
            total,
        )

        logger.error(
            "Minimum required: %d",
            MIN_TOTAL_ARTICLES_TO_REPLACE,
        )

        if existing:

            logger.warning(
                "SAFE MODE: Keeping existing news.json"
            )

            return 1

        logger.error(
            "No previous valid database exists."
        )

        # Write a diagnostic database only when there
        # is no previous database at all.
        safe_empty = {
            "updated": "",
            "generator": {
                "name":
                    "Nepal News Top 10 Scraper",
                "version":
                    "2.0",
            },
            "diagnostics": database[
                "diagnostics"
            ],
            "sections": {
                section: []
                for section in SECTIONS
            },
        }

        write_database(
            safe_empty
        )

        return 1

    # Good enough — replace the database.
    write_database(
        database
    )

    # --------------------------------------------------------
    # 9. REPORT
    # --------------------------------------------------------

    logger.info(
        ""
    )

    logger.info(
        "=" * 70
    )

    logger.info(
        "SCRAPER SUCCESS"
    )

    logger.info(
        "=" * 70
    )

    logger.info(
        "Total unique articles: %d",
        len(all_articles),
    )

    logger.info(
        "Published to news.json: %d",
        total,
    )

    logger.info(
        ""
    )

    for section in SECTIONS:

        logger.info(
            "%-16s : %d",
            section,
            len(
                sections[section]
            ),
        )

    logger.info(
        ""
    )

    logger.info(
        "Google News successful: %d",
        diagnostics[
            "google_news"
        ]["successful"],
    )

    logger.info(
        "Google News failed: %d",
        diagnostics[
            "google_news"
        ]["failed"],
    )

    logger.info(
        "RSS successful: %d",
        diagnostics[
            "rss"
        ]["successful"],
    )

    logger.info(
        "RSS failed: %d",
        diagnostics[
            "rss"
        ]["failed"],
    )

    logger.info(
        "Direct pages successful: %d",
        diagnostics[
            "direct"
        ]["successful"],
    )

    logger.info(
        "Direct pages failed: %d",
        diagnostics[
            "direct"
        ]["failed"],
    )

    logger.info(
        ""
    )

    logger.info(
        "Output: %s",
        OUTPUT_FILE,
    )

    logger.info(
        "=" * 70
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
