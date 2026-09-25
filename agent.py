#!/usr/bin/env python3
"""Lean content agent (no n8n). Runs on any free host: GitHub Actions, a laptop, any Linux box with cron.

  python agent.py topics     -> gather signals, rank top 5, send to Telegram, remember them
  python agent.py poll       -> read your Telegram reply ("2 5"), build the 2 decks, send them
  python agent.py decks 2 5  -> build the two decks directly (Tuesday=2, Thursday=5)

Config comes only from environment variables (see README.md). Set DRY_RUN=1 to test offline."""
import os, re, sys, json, time, datetime, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
from deck import build_pdf

HERE = Path(__file__).parent
STATE_FILE = HERE / "state.json"
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
DRY = os.getenv("DRY_RUN") == "1"
MODEL = os.getenv("GEMINI_MODEL", "").strip()   # leave empty: the agent picks a working Flash model itself
GKEY = os.getenv("GEMINI_API_KEY", "").strip()
TTOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TCHAT = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
YTKEY = os.getenv("YOUTUBE_API_KEY", "").strip()
UA = {"User-Agent": "lean-content-agent/1.0 (personal use)"}
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

NEWS_QUERIES = ["lean manufacturing", "operational excellence manufacturing", "process excellence", "TPM total productive maintenance",
                "Hoshin Kanri", "lean six sigma", "lean pharmaceutical manufacturing", "automotive lean manufacturing",
                "power plant operational excellence maintenance", "kaizen"]
REDDIT_QUERIES = ["lean manufacturing", "operational excellence", "TPM maintenance", "six sigma", "kaizen"]
YT_QUERIES = ["lean manufacturing", "operational excellence", "total productive maintenance", "Hoshin Kanri"]


# ---------------- state ----------------
def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))


# ---------------- telegram ----------------
def tg(method, **kw):
    if DRY:
        print(f"[DRY telegram.{method}]", {k: (v if k != "files" else "<file>") for k, v in kw.items()}); return {"result": []}
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{TTOKEN}/{method}", data=kw, files=files, timeout=120)
    r.raise_for_status(); return r.json()

def tg_updates(offset):
    if DRY: return []
    r = requests.get(f"https://api.telegram.org/bot{TTOKEN}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=30)
    r.raise_for_status(); return r.json().get("result", [])


# ---------------- gemini ----------------
_model_cache = {}
def pick_model():
    """Ask the API which models this key can use and pick the newest stable Flash model."""
    if MODEL: return MODEL
    if "m" in _model_cache: return _model_cache["m"]
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 200},
                     headers={"x-goog-api-key": GKEY}, timeout=30)
    r.raise_for_status()
    cands = []
    for m in r.json().get("models", []):
        n = m["name"].split("/")[-1]
        if "generateContent" not in m.get("supportedGenerationMethods", []): continue
        if "flash" not in n or any(x in n for x in ("lite", "image", "tts", "live", "audio", "thinking", "8b", "vision", "robotics", "computer")): continue
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        cands.append((float(v.group(1)) if v else 0, not any(x in n for x in ("preview", "exp")), n))
    if not cands: raise RuntimeError("No Gemini Flash model available for this API key")
    cands.sort(reverse=True)
    _model_cache["m"] = cands[0][2]
    print("using Gemini model:", cands[0][2])
    return cands[0][2]

def gemini(prompt, grounded=False, json_mode=False):
    if DRY: return MOCK.get("ground" if grounded else "json", ""), []
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if grounded: body["tools"] = [{"google_search": {}}]
    if json_mode: body["generationConfig"] = {"responseMimeType": "application/json", "temperature": 0.4}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{pick_model()}:generateContent"
    for attempt in range(4):
        r = requests.post(url, headers={"x-goog-api-key": GKEY, "Content-Type": "application/json"}, json=body, timeout=180)
        if r.status_code in (429, 500, 503):
            time.sleep(8 * (attempt + 1)); continue
        r.raise_for_status(); break
    else:
        raise RuntimeError("Gemini kept failing: " + r.text[:300])
    cand = (r.json().get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", [])).strip()
    seen, sources = set(), []
    for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []):
        w = ch.get("web", {})
        if w.get("uri") and w["uri"] not in seen:
            seen.add(w["uri"]); sources.append({"title": w.get("title") or w["uri"], "uri": w["uri"]})
    if not text: raise RuntimeError("Gemini returned no text")
    return text, sources

def parse_json(txt):
    a, b = txt.find("{"), txt.rfind("}")     # tolerate prose or code fences around the JSON
    if a < 0 or b < a: raise ValueError("No JSON in model reply: " + txt[:200])
    return json.loads(txt[a:b + 1])


# ---------------- free signal sources ----------------
def google_news(q):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d") + "&hl=en-IN&gl=IN&ceid=IN:en"
    root = ET.fromstring(requests.get(url, headers=UA, timeout=30).content)
    return [i.findtext("title", "") for i in root.iter("item")][:8]

def reddit(q):
    url = "https://www.reddit.com/search.rss?q=" + urllib.parse.quote(q) + "&sort=top&t=week"
    root = ET.fromstring(requests.get(url, headers=UA, timeout=30).content)
    ns = "{http://www.w3.org/2005/Atom}"
    return [e.findtext(ns + "title", "") for e in root.iter(ns + "entry")][:6]

def youtube(q):
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    s = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={
        "part": "snippet", "q": q, "type": "video", "order": "viewCount", "publishedAfter": since, "maxResults": 6, "key": YTKEY}).json()
    ids = [i["id"]["videoId"] for i in s.get("items", [])]
    if not ids: return []
    v = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
        "part": "snippet,statistics", "id": ",".join(ids), "key": YTKEY}).json()
    return [f'{i["snippet"]["title"]} ({i["statistics"].get("viewCount", "?")} views)' for i in v.get("items", [])]

def collect_signals():
    out = {"news": [], "reddit": [], "youtube": []}
    jobs = [("news", google_news, NEWS_QUERIES), ("reddit", reddit, REDDIT_QUERIES)]
    if YTKEY: jobs.append(("youtube", youtube, YT_QUERIES))
    for key, fn, qs in jobs:
        for q in qs:
            for attempt in range(2):
                try: out[key] += fn(q); break
                except Exception as e:
                    print(f"signal {key}/{q} failed: {e}"); time.sleep(4)
            time.sleep(2)
        out[key] = list(dict.fromkeys(out[key]))
    return out


# ---------------- commands ----------------
def cmd_topics():
    sig = {"news": [f"mock headline {i}" for i in range(12)], "reddit": [], "youtube": []} if DRY else collect_signals()
    have = sum(len(v) for v in sig.values())
    print("signals collected:", {k: len(v) for k, v in sig.items()})
    if have >= 10:
        blob = "\n".join(f"[{k}] {t}" for k, v in sig.items() for t in v)
        prompt = (f"Today is {TODAY:%d %b %Y}. Below are headlines, Reddit post titles and YouTube videos (with view counts) from the last 7 days about lean manufacturing, "
                  "process excellence and operational excellence. Choose the 5 topics most worth a LinkedIn post by a lean / OpEx professional, spanning automotive, pharma, manufacturing and power where the evidence allows. "
                  'Rank by how much attention they got (repeated headlines, Reddit upvote ranking, YouTube views). Return JSON {"topics":[{"title":string max 8 words,"industry":string,"why":string max 22 words,"evidence":string max 15 words naming the signal}]} with exactly 5 items. Use only the signals below; do not invent numbers.\n\n' + blob)
        txt, _ = gemini(prompt, json_mode=True)
    else:
        print("few signals; falling back to Gemini + Google Search")
        txt, _ = gemini(f'Today is {TODAY:%d %b %Y}. Using Google Search, find the 5 most searched and discussed topics of the last 4 weeks in lean manufacturing, process excellence and operational excellence across automotive, pharma, manufacturing and power. Return ONLY JSON {{"topics":[{{"title":string,"industry":string,"why":string,"evidence":string}}]}} with exactly 5 items.', grounded=True)
    topics = parse_json(txt)["topics"][:5]
    if len(topics) < 5: raise RuntimeError("Expected 5 topics")
    st = load_state(); st["pending"] = {"topics": topics, "sent_at": time.time()}; save_state(st)
    msg = f"Weekly lean / process excellence / OpEx topics ({TODAY:%d %b %Y})\n\n"
    for i, t in enumerate(topics, 1):
        msg += f"{i}. {t['title']} [{t['industry']}]\n   {t['why']}\n   Signal: {t.get('evidence', '')}\n\n"
    msg += 'Reply with TWO numbers, e.g. "1 4".\nFirst = Tuesday deck, second = Thursday deck.'
    tg("sendMessage", chat_id=TCHAT, text=msg)

def make_deck(topic, slot):
    research, sources = gemini(
        f"Research this topic for a LinkedIn knowledge-sharing deck by a lean / operational-excellence professional. Use Google Search. Topic: {topic['title']} (industry focus: {topic['industry']}). Today is {TODAY:%d %b %Y}. "
        "Report: why it matters now; the core concept and lean/OpEx tools involved; what is happening in automotive, in pharma, in general manufacturing and in power/energy; 6 to 8 concrete facts or figures with source names, flagging vendor claims; practical steps; risks and caveats. Report only what sources support; do not invent numbers.",
        grounded=True)
    txt, _ = gemini(
        'Create a LinkedIn knowledge-sharing deck for Kunal Sinha, a lean and operational-excellence professional. Use ONLY the research below. Return JSON exactly like {"topic":string (max 9 words),"subtitle":string (one line),"post_title":string (LinkedIn headline, max 12 words, no emojis),'
        '"caption":string (95 to 105 words, first person, one hook line, plain text, ends with 3 to 4 hashtags),"slides":[{"kicker":string,"title":string (max 8 words),"bullets":[3 to 5 strings, each max 26 words],"note":string (optional one-line caveat)}]}. '
        "Exactly 8 slides in this order: why it matters now; core concept and lean tools; automotive; pharma; general manufacturing; power and energy; evidence and numbers (flag vendor claims as directional); action roadmap and key takeaways. Do not invent statistics. Plain professional English.\n\n"
        f"TOPIC: {topic['title']}\n\nRESEARCH:\n{research}", json_mode=True)
    deck = parse_json(txt)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", deck.get("topic", "Lean"))[:50]
    path = OUT / f"{slot}_{TODAY:%Y-%m-%d}_{safe}.pdf"
    build_pdf(deck, sources, path, f"{TODAY:%B %Y}")
    cap = (f"POST ON {slot.upper()}\n\nTITLE: {deck.get('post_title','')}\n\nCAPTION:\n{deck.get('caption','')}\n\nPlease review. Post manually on LinkedIn.")
    cap = cap if len(cap) <= 1020 else cap[:1015] + "..."
    with open(path, "rb") as f:
        tg("sendDocument", chat_id=TCHAT, caption=cap, files={"document": (path.name, f, "application/pdf")})
    print("sent", path.name)

def cmd_decks(a, b):
    st = load_state(); pend = st.get("pending")
    if not pend: raise SystemExit("No pending topic list. Run: python agent.py topics")
    for slot, n in (("Tuesday", a), ("Thursday", b)):
        try: make_deck(pend["topics"][n - 1], slot)
        except Exception as e:
            tg("sendMessage", chat_id=TCHAT, text=f"Could not build the {slot} deck: {str(e)[:300]}"); raise
    st["pending"] = None; save_state(st)

def cmd_poll():
    st = load_state(); pend = st.get("pending")
    if not pend: print("nothing pending"); return
    ups = tg_updates(st.get("offset", 0))
    if not ups: print("no new messages"); return
    st["offset"] = max(u["update_id"] for u in ups) + 1
    picks = None
    for u in ups:
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != TCHAT or m.get("date", 0) < pend["sent_at"]: continue
        f = re.search(r"([1-5])\D+([1-5])", m.get("text", ""))
        if f and f.group(1) != f.group(2): picks = (int(f.group(1)), int(f.group(2)))
    save_state(st)                       # remember offset even if no valid reply
    if picks:
        cmd_decks(*picks)
    else:
        print("messages seen, no valid pick")


MOCK = {
    "json": json.dumps({"topics": [{"title": f"Mock topic {i}", "industry": "Automotive", "why": "Because tests.", "evidence": "mock"} for i in range(1, 6)],
        "topic": "Mock: AI-Powered Lean", "subtitle": "Offline test deck", "post_title": "Mock title", "caption": "Mock caption " * 30,
        "slides": [{"kicker": f"Section {i}", "title": f"Slide {i} title", "bullets": ["A fairly long bullet that explains one lean idea in plain words. " * 2, "Second point.", "Third point."], "note": "Mock caveat"} for i in range(1, 9)]}),
    "ground": "mock research text",
}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "topics": cmd_topics()
    elif c == "poll": cmd_poll()
    elif c == "decks" and len(sys.argv) == 4: cmd_decks(int(sys.argv[2]), int(sys.argv[3]))
    else: print(__doc__)
