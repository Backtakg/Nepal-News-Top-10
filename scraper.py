import os, re, json, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests

API_URL = "https://api.worldnewsapi.com/search-news"
API_KEY = os.environ.get("NEWS_API_KEY", "").strip()
OUTPUT_FILE = Path("news.json")
MAX_PER_CATEGORY = 10
CANDIDATES_PER_CATEGORY = 40
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 1.5
SECTIONS = ["weather","national","politics","business","sports","technology","entertainment","world","health","crime"]

# Text queries are deliberately Nepal-centric. source-country=np keeps the
# publisher country Nepal, so the site remains primarily based on Nepali portals.
QUERIES = {
 "weather": 'Nepal weather OR rainfall OR monsoon OR flood OR landslide OR storm OR temperature OR climate OR lightning',
 "national": 'Nepal OR Kathmandu OR "government of Nepal" OR ministry OR province OR municipality',
 "politics": 'Nepal politics OR parliament OR government OR minister OR "prime minister" OR president OR election OR party OR coalition OR cabinet OR UML OR "Nepali Congress" OR Maoist',
 "business": 'Nepal business OR economy OR economic OR bank OR banking OR finance OR NEPSE OR stock OR investment OR trade OR tourism OR remittance OR company OR industry',
 "sports": 'Nepal cricket OR football OR sports OR tournament OR athlete OR "national team" OR ICC OR FIFA OR league OR championship',
 "technology": 'Nepal technology OR tech OR "artificial intelligence" OR AI OR digital OR software OR internet OR cyber OR cybersecurity OR startup OR app OR mobile',
 "entertainment": 'Nepal entertainment OR Nepali movie OR Nepali film OR cinema OR music OR actor OR actress OR singer OR concert OR television OR celebrity OR festival',
 "world": 'India OR China OR United States OR Europe OR Middle East OR Ukraine OR Russia OR Israel OR Iran OR Pakistan OR international OR world',
 "health": 'Nepal health OR hospital OR doctor OR disease OR medical OR medicine OR patient OR healthcare OR dengue OR infection OR vaccine OR outbreak OR epidemic',
 "crime": 'Nepal crime OR police OR arrest OR murder OR fraud OR robbery OR theft OR court OR criminal OR investigation OR accident OR abuse OR drug OR scam',
}

KEYWORDS = {
 "weather": ["weather","rain","rainfall","flood","monsoon","landslide","storm","temperature","climate","lightning","snow","heatwave","cold wave"],
 "national": ["nepal","kathmandu","government","ministry","province","municipality","national"],
 "politics": ["politics","political","government","minister","prime minister","president","parliament","election","party","coalition","cabinet","uml","congress","maoist"],
 "business": ["business","economy","economic","bank","banking","finance","nepse","stock","investment","trade","tourism","company","industry","remittance"],
 "sports": ["sports","sport","cricket","football","soccer","match","tournament","league","player","athlete","fifa","icc","championship","olympic"],
 "technology": ["technology","tech","artificial intelligence","ai","digital","software","internet","cyber","cybersecurity","computer","startup","app","mobile"],
 "entertainment": ["entertainment","movie","film","cinema","music","actor","actress","singer","concert","television","celebrity","festival"],
 "world": ["world","international","india","china","america","united states","usa","europe","russia","ukraine","israel","iran","pakistan","middle east"],
 "health": ["health","hospital","doctor","disease","medical","medicine","patient","healthcare","virus","outbreak","dengue","infection","vaccine","epidemic"],
 "crime": ["crime","police","arrest","murder","fraud","robbery","theft","court","criminal","investigation","accident","abuse","drug","scam"],
}

session = requests.Session()
session.headers.update({"User-Agent":"NepalNewsTop10/2.0","Accept":"application/json","x-api-key":API_KEY})

def clean(v):
    if v is None: return ""
    s = re.sub(r"<[^>]+>", " ", str(v))
    return re.sub(r"\s+", " ", s).strip()

def norm_title(s):
    s = clean(s).lower()
    s = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def article_id(title, url):
    return hashlib.sha256((norm_title(title)+"|"+url.lower()).encode()).hexdigest()

def parse_dt(v):
    if not v: return 0
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
    except Exception: return 0

def sentence(text, fallback="Read the original article for the latest information."):
    text = clean(text)
    if not text: return fallback
    text = re.sub(r"^(read more|continue reading)\s*[:\-]?\s*", "", text, flags=re.I)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = parts[0].strip()
    if len(out) < 35 and len(parts)>1: out = (out+" "+parts[1].strip()).strip()
    if len(out)>280: out = out[:277].rsplit(" ",1)[0]+"..."
    if not out.endswith((".","!","?")): out += "."
    return out

def keyword_score(a, section):
    text = (clean(a.get("title"))+" "+clean(a.get("text"))+" "+clean(a.get("summary"))+" "+clean(a.get("description"))).lower()
    title = clean(a.get("title")).lower()
    score=0
    for k in KEYWORDS[section]:
        if k in title: score += 7
        elif k in text: score += 2
    if clean(a.get("source_country")).lower()=="np": score += 5
    if clean(a.get("language")).lower() in ("en","ne"): score += 2
    return score

def quality(a, section):
    score = keyword_score(a,section)
    ts=parse_dt(a.get("publish_date"))
    if ts:
        age=max(0,(datetime.now(timezone.utc).timestamp()-ts)/3600)
        score += 8 if age<6 else 5 if age<24 else 2 if age<72 else 0
    if a.get("image") or a.get("image_url"): score += 2
    if len(clean(a.get("text")))>150: score += 1
    return score

def valid(a):
    return isinstance(a,dict) and bool(clean(a.get("title"))) and clean(a.get("url")).startswith(("http://","https://"))

def fetch_category(section):
    params={
      "text": QUERIES[section],
      "language": "en",
      "source-country": "np",
      "earliest-publish-date": (datetime.now(timezone.utc)-timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
      "number": CANDIDATES_PER_CATEGORY,
      "sort": "publish-time",
      "sort-direction": "DESC",
    }
    print(f"FETCHING {section}: {params['text']}")
    r=session.get(API_URL,params=params,timeout=REQUEST_TIMEOUT)
    if r.status_code!=200:
        try: detail=r.json()
        except Exception: detail=r.text[:500]
        raise RuntimeError(f"World News API {r.status_code}: {detail}")
    data=r.json()
    news=data.get("news",[])
    return news if isinstance(news,list) else []

def convert(a, section):
    title=clean(a.get("title")); url=clean(a.get("url"));
    src=a.get("source_name") or a.get("source") or a.get("source_country") or "Nepal news source"
    if isinstance(src,dict): src=src.get("name","")
    image=clean(a.get("image") or a.get("image_url"))
    pub=clean(a.get("publish_date") or a.get("publishedAt"))
    return {"id":article_id(title,url),"title":title,"summary":sentence(a.get("summary") or a.get("text") or a.get("description") or title),"source":clean(src),"link":url,"published":pub,"section":section,"image":image}

def load_existing():
    try:
        if OUTPUT_FILE.exists():
            with OUTPUT_FILE.open(encoding="utf-8") as f: return json.load(f)
    except Exception: pass
    return None

def build():
    if not API_KEY: raise RuntimeError("NEWS_API_KEY is missing. Add your World News API key to GitHub Actions secrets.")
    sections={s:[] for s in SECTIONS}; diagnostics={"provider":"World News API","successful_categories":[],"failed_categories":[],"api_articles":0,"final_articles":0}
    for i,section in enumerate(SECTIONS):
        try:
            raw=fetch_category(section); diagnostics["api_articles"]+=len(raw)
            seen=set(); candidates=[]
            for a in raw:
                if not valid(a): continue
                u=clean(a.get("url")); t=norm_title(a.get("title")); key=u.lower() or t
                if key in seen: continue
                seen.add(key)
                candidates.append((quality(a,section),parse_dt(a.get("publish_date")),a))
            candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
            sections[section]=[convert(a,section) for _,_,a in candidates[:MAX_PER_CATEGORY]]
            diagnostics["successful_categories"].append(section); diagnostics["final_articles"]+=len(sections[section])
            print(f"{section}: {len(sections[section])} selected from {len(raw)}")
        except Exception as e:
            diagnostics["failed_categories"].append({"section":section,"error":str(e)}); print(f"FAILED {section}: {e}")
        if i<len(SECTIONS)-1: time.sleep(REQUEST_DELAY)
    return sections,diagnostics

def write(sections,diagnostics):
    existing=load_existing()
    counts={s:len(sections[s]) for s in SECTIONS}
    incomplete=[s for s,c in counts.items() if c<MAX_PER_CATEGORY]
    if incomplete:
        print("INCOMPLETE CATEGORIES:",", ".join(f"{s}={counts[s]}" for s in incomplete))
        if existing:
            print("Keeping previous news.json because this run is incomplete.")
            return False
        raise RuntimeError("No previous news.json and categories are incomplete.")
    all_articles=[a for s in SECTIONS for a in sections[s]]
    all_articles.sort(key=lambda a:parse_dt(a.get("published")),reverse=True)
    latest=[]; seen=set()
    for a in all_articles:
        k=a["link"].lower()
        if k in seen: continue
        seen.add(k); latest.append(a)
        if len(latest)==10: break
    output={"updated":datetime.now(timezone.utc).isoformat(),"provider":"World News API","latest":latest,"sections":sections,"diagnostics":diagnostics}
    tmp=Path("news.json.tmp")
    with tmp.open("w",encoding="utf-8") as f: json.dump(output,f,ensure_ascii=False,indent=2)
    tmp.replace(OUTPUT_FILE); print("NEWS DATABASE UPDATED: 100 category articles + latest 10"); return True

def main():
    print("NEPAL NEWS TOP 10 — World News API")
    sections,diag=build(); write(sections,diag)

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("SCRAPER FAILED:",e); raise
