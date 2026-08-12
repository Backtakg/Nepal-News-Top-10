import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import requests

API_URL = "https://api.worldnewsapi.com/search-news"
API_KEY = os.environ.get("NEWS_API_KEY", "").strip()
OUTPUT_FILE = Path("news.json")

MAX_PER_CATEGORY = 10
MIN_TOTAL_ARTICLES = 20
REQUEST_TIMEOUT = 30

SECTIONS = [
    "weather", "national", "politics", "business", "sports",
    "technology", "entertainment", "world", "health", "crime"
]

# Only three API calls per run. The first two strongly prioritize Nepal;
# the third supplies international/world coverage.
REQUESTS = [
    {
        "name": "Nepal English",
        "params": {
            "source-country": "np",
            "language": "en",
            "number": 100,
            "sort": "publish-time",
            "sort-direction": "DESC",
        },
    },
    {
        "name": "Nepal Nepali",
        "params": {
            "source-country": "np",
            "language": "ne",
            "number": 100,
            "sort": "publish-time",
            "sort-direction": "DESC",
        },
    },
    {
        "name": "World",
        "params": {
            "text": "world OR international OR India OR China OR Asia OR Europe OR America OR Middle East",
            "language": "en",
            "number": 100,
            "sort": "publish-time",
            "sort-direction": "DESC",
        },
    },
]

KEYWORDS = {
    "weather": ["weather","rain","rainfall","flood","flooding","monsoon","landslide","storm",
                "temperature","climate","snow","thunderstorm","lightning","heatwave","forecast",
                "बाढ","पहिरो","वर्षा","मौसम","मनसुन","हावाहुरी"],
    "national": ["nepal","kathmandu","national","ministry","province","municipality",
                 "नेपाल","काठमाडौं","राष्ट्रिय","मन्त्रालय","प्रदेश","पालिका"],
    "politics": ["politics","political","government","minister","prime minister","president",
                 "parliament","election","party","coalition","cabinet","uml","congress","maoist",
                 "राजनीति","सरकार","मन्त्री","प्रधानमन्त्री","राष्ट्रपति","संसद","निर्वाचन","दल"],
    "business": ["business","economy","economic","bank","banking","finance","market","nepse",
                 "stock","investment","trade","tourism","company","industry","remittance",
                 "व्यापार","अर्थतन्त्र","बैंक","वित्त","लगानी","पर्यटन","रेमिट्यान्स","शेयर"],
    "sports": ["sports","sport","cricket","football","soccer","match","tournament","league",
               "player","athlete","fifa","icc","championship","olympic",
               "खेल","क्रिकेट","फुटबल","प्रतियोगिता","खेलाडी"],
    "technology": ["technology","tech","artificial intelligence","ai","digital","software",
                   "internet","cyber","cybersecurity","computer","startup","app","mobile",
                   "प्रविधि","डिजिटल","सफ्टवेयर","इन्टरनेट","साइबर","स्टार्टअप"],
    "entertainment": ["entertainment","movie","film","cinema","music","actor","actress","singer",
                      "concert","television","celebrity","festival","मनोरञ्जन","चलचित्र","फिल्म",
                      "सिनेमा","संगीत","गायक","अभिनेता","कलाकार"],
    "world": ["world","international","india","china","america","united states","usa","europe",
              "russia","ukraine","israel","iran","pakistan","middle east","विश्व","अन्तर्राष्ट्रिय",
              "भारत","चीन","अमेरिका","युरोप"],
    "health": ["health","hospital","doctor","disease","medical","medicine","patient","healthcare",
               "virus","outbreak","dengue","infection","vaccine","epidemic","स्वास्थ्य","अस्पताल",
               "डाक्टर","रोग","औषधि","डेंगु","संक्रमण","खोप"],
    "crime": ["crime","police","arrest","murder","fraud","robbery","theft","court","criminal",
              "investigation","accident","abuse","drug","scam","अपराध","प्रहरी","गिरफ्तार","हत्या",
              "ठगी","चोरी","अदालत","दुर्घटना","अनुसन्धान"],
}

SOURCE_PRIORITY = {
    "onlinekhabar": 12, "setopati": 12, "ratopati": 11, "nagarik": 11,
    "ekantipur": 11, "kantipur": 11, "gorkhapatra": 10, "gorkhapatra online": 10,
    "nepal press": 10, "khabarhub": 10, "baahrakhari": 10, "ujyaalo": 10,
    "naya patrika": 10, "annapurna post": 10, "himalayan times": 9,
    "nepal news": 9, "kathmandu post": 9, "nepali times": 9,
}

def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value))).strip()

def norm_title(title):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u0900-\u097f]+", " ", clean(title).lower())).strip()

def make_id(title, url):
    return hashlib.sha256((norm_title(title) + "|" + clean(url)).encode()).hexdigest()

def parse_date(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

def sentence(summary, title):
    text = clean(summary) or clean(title)
    parts = re.split(r"(?<=[.!?।])\s+", text)
    result = (parts[0] if parts else text).strip()
    if len(result) > 300:
        result = result[:297].rsplit(" ", 1)[0] + "..."
    if result and not result.endswith((".", "!", "?", "।")):
        result += "."
    return result

def source_name(article):
    source = article.get("source") or {}
    if isinstance(source, dict):
        return clean(source.get("name") or source.get("title") or source.get("url")) or "News source"
    return clean(source) or "News source"

def classify(article):
    api_category = clean(article.get("category")).lower()
    api_map = {
        "politics":"politics", "sports":"sports", "business":"business",
        "technology":"technology", "entertainment":"entertainment",
        "health":"health"
    }
    if api_category in api_map:
        return api_map[api_category]

    text = (clean(article.get("title")) + " " + clean(article.get("summary"))).lower()
    scores = {section: sum(1 for word in words if word.lower() in text)
              for section, words in KEYWORDS.items()}

    # A World request should not accidentally become a Nepal category unless
    # the article has a stronger category signal.
    if article.get("_request") == "World":
        scores["world"] += 3

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "national" if clean(article.get("source_country")).lower() == "np" else "world"
    return best

def quality(article):
    published = parse_date(article.get("publish_date") or article.get("published"))
    now = datetime.now(timezone.utc)
    hours = 9999 if published == datetime.min.replace(tzinfo=timezone.utc) else max(0, (now-published).total_seconds()/3600)
    freshness = max(0, 48-hours) / 3
    image_bonus = 4 if clean(article.get("image")) else 0
    source_bonus = SOURCE_PRIORITY.get(source_name(article).lower(), 0)
    category_bonus = 2 if clean(article.get("category")) else 0
    return freshness + image_bonus + source_bonus + category_bonus

def normalize(article, request_name):
    title = clean(article.get("title"))
    url = clean(article.get("url"))
    if not title or not url:
        return None
    published = article.get("publish_date") or article.get("published") or ""
    parsed = parse_date(published)
    return {
        "id": str(article.get("id") or make_id(title, url)),
        "title": title,
        "summary": sentence(article.get("summary") or article.get("text"), title),
        "source": source_name(article),
        "link": url,
        "published": parsed.isoformat() if parsed != datetime.min.replace(tzinfo=timezone.utc) else clean(published),
        "section": classify(article),
        "image": clean(article.get("image")),
        "_request": request_name,
        "_country": clean(article.get("source_country")).lower(),
    }

def fetch(req):
    params = dict(req["params"])
    params["api-key"] = API_KEY
    response = requests.get(
        API_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "NepalNewsTop10/3.0"},
    )
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("news", [])
    print(f"{req['name']}: {len(articles)} articles (available {payload.get('available', '?')})")
    return [normalize(a, req["name"]) for a in articles]

def dedupe(items):
    output = []
    seen_titles, seen_urls = set(), set()
    for item in sorted([x for x in items if x], key=quality, reverse=True):
        title_key = norm_title(item["title"])
        url_key = item["link"].split("#")[0].lower()
        if title_key in seen_titles or url_key in seen_urls:
            continue
        seen_titles.add(title_key)
        seen_urls.add(url_key)
        output.append(item)
    return output

def clean_for_json(item):
    return {k:v for k,v in item.items() if not k.startswith("_")}

def build():
    if not API_KEY:
        raise RuntimeError("NEWS_API_KEY is missing. Add your World News API key to GitHub Secrets.")

    discovered = []
    failures = []
    for req in REQUESTS:
        try:
            discovered.extend(fetch(req))
        except Exception as exc:
            failures.append({"request": req["name"], "error": str(exc)})
            print(f"WARNING: {req['name']} failed: {exc}")

    unique = dedupe(discovered)
    groups = {section: [] for section in SECTIONS}

    for item in unique:
        section = item["section"]
        if section in groups:
            groups[section].append(item)

    for section in SECTIONS:
        groups[section].sort(
            key=lambda x: (
                1 if x.get("_country") == "np" else 0,
                quality(x)
            ),
            reverse=True
        )
        groups[section] = [clean_for_json(x) for x in groups[section][:MAX_PER_CATEGORY]]

    latest = sorted(unique, key=quality, reverse=True)[:10]
    latest = [clean_for_json(x) for x in latest]

    total = sum(len(v) for v in groups.values())
    database = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "provider": "World News API",
        "generator": "Nepal News Top 10",
        "latest": latest,
        "sections": groups,
        "diagnostics": {
            "requests": len(REQUESTS),
            "failed_requests": failures,
            "discovered": len(discovered),
            "unique": len(unique),
            "published": total,
        },
    }

    if total < MIN_TOTAL_ARTICLES:
        print(f"ERROR: only {total} usable articles. Existing news.json will be kept.")
        return False

    temp = OUTPUT_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUTPUT_FILE)

    print("=" * 60)
    print("WORLD NEWS API UPDATE SUCCESS")
    print("=" * 60)
    for section in SECTIONS:
        print(f"{section:16}: {len(groups[section])}")
    print(f"{'TOTAL':16}: {total}")
    print(f"{'LATEST':16}: {len(latest)}")
    print("=" * 60)
    return True

if __name__ == "__main__":
    if not build():
        raise SystemExit(1)
